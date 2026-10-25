"""Embedding storage (SQLite BLOB) and brute-force cosine search."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable

import numpy as np

from papermind.llm.client import LLMClient
from papermind.runtime.catalog import ModelSpec


def to_blob(vec: list[float] | np.ndarray) -> bytes:
    v = np.asarray(vec, dtype=np.float32)
    n = np.linalg.norm(v)
    return (v / n if n else v).tobytes()


def from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def paper_text(conn: sqlite3.Connection, paper_id: int, limit: int = 1500) -> str:
    p = conn.execute("SELECT title, one_liner FROM paper WHERE id = ?", (paper_id,)).fetchone()
    parts = [p["title"], p["one_liner"] or ""]
    for kind in ("background", "results", "critique"):
        r = conn.execute(
            "SELECT content_md FROM paper_section WHERE paper_id=? AND kind=?", (paper_id, kind)
        ).fetchone()
        if r:
            parts.append(r["content_md"])
    return "\n".join(x for x in parts if x)[:limit]


def ensure_paper_embeddings(
    conn: sqlite3.Connection,
    client: LLMClient,
    spec: ModelSpec,
    progress: Callable[[float, str], None] | None = None,
) -> int:
    """Embed papers whose text changed or that have no vector yet. Returns the number embedded."""
    ids = [r["id"] for r in conn.execute("SELECT id FROM paper ORDER BY id")]
    todo: list[tuple[int, str, str]] = []
    for pid in ids:
        text = paper_text(conn, pid)
        h = hashlib.sha256(text.encode()).hexdigest()[:16]
        row = conn.execute(
            "SELECT text_hash FROM embedding WHERE owner_type='paper' AND owner_id=? AND model=?", (pid, spec.id)
        ).fetchone()
        if row is None or row["text_hash"] != h:
            todo.append((pid, text, h))
    for i, (pid, text, h) in enumerate(todo):
        vec = client.embed([spec.doc_prefix + text])[0]
        conn.execute(
            "INSERT OR REPLACE INTO embedding(owner_type, owner_id, model, text_hash, dim, vector) VALUES ('paper',?,?,?,?,?)",
            (pid, spec.id, h, len(vec), to_blob(vec)),
        )
        if progress:
            progress((i + 1) / len(todo), f"向量化 {i + 1}/{len(todo)}")
    conn.commit()
    return len(todo)


def load_matrix(conn: sqlite3.Connection, model: str, owner_type: str = "paper") -> tuple[list[int], np.ndarray]:
    rows = conn.execute(
        "SELECT e.owner_id, e.vector FROM embedding e WHERE e.owner_type=? AND e.model=? "
        "AND (e.owner_type != 'paper' OR e.owner_id IN (SELECT id FROM paper)) ORDER BY e.owner_id",
        (owner_type, model),
    ).fetchall()
    if not rows:
        return [], np.zeros((0, 0), dtype=np.float32)
    return [r["owner_id"] for r in rows], np.stack([from_blob(r["vector"]) for r in rows])


def nearest(
    conn: sqlite3.Connection, model: str, vec, k: int = 10, exclude: int | None = None
) -> list[tuple[int, float]]:
    ids, mat = load_matrix(conn, model)
    if not ids:
        return []
    q = from_blob(to_blob(vec))
    sims = mat @ q
    order = np.argsort(-sims)
    out = [(ids[i], float(sims[i])) for i in order if ids[i] != exclude]
    return out[:k]
