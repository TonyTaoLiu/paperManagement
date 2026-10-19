"""Keyword (FTS5 trigram), semantic (embeddings) and hybrid (RRF) paper search."""

from __future__ import annotations

import re
import sqlite3

from papermind.embed.index import nearest
from papermind.services.models import models


def keyword_search(conn: sqlite3.Connection, q: str, limit: int = 50) -> list[tuple[int, float]]:
    tokens = [t for t in re.split(r"\s+", q.strip()) if t]
    if not tokens:
        return []
    if all(len(t) >= 3 for t in tokens):
        match = " AND ".join('"' + t.replace('"', '""') + '"' for t in tokens)
        rows = conn.execute(
            "SELECT rowid, bm25(paper_fts, 4.0, 1.0) AS s FROM paper_fts WHERE paper_fts MATCH ? ORDER BY s LIMIT ?",
            (match, limit),
        ).fetchall()
        return [(r["rowid"], -r["s"]) for r in rows]
    # trigram FTS cannot match 1-2 character tokens; LIKE falls back to a scan (fine for <5k papers)
    where = " AND ".join("(title LIKE ? OR body LIKE ?)" for _ in tokens)
    params = [p for t in tokens for p in (f"%{t}%", f"%{t}%")]
    rows = conn.execute(f"SELECT rowid FROM paper_fts WHERE {where} LIMIT ?", (*params, limit)).fetchall()
    return [(r["rowid"], 1.0) for r in rows]


def semantic_search(conn: sqlite3.Connection, q: str, limit: int = 50) -> list[tuple[int, float]]:
    if not models.embed_available():
        return []
    client, spec = models.embedder()
    vec = client.embed([spec.query_prefix + q])[0]
    return nearest(conn, spec.id, vec, limit)


def hybrid_search(conn: sqlite3.Connection, q: str, limit: int = 50, mode: str = "hybrid") -> list[tuple[int, float]]:
    if mode == "keyword":
        return keyword_search(conn, q, limit)
    if mode == "semantic":
        return semantic_search(conn, q, limit)
    kw, sem = keyword_search(conn, q, limit), semantic_search(conn, q, limit)
    scores: dict[int, float] = {}
    for ranked in (kw, sem):
        for rank, (pid, _) in enumerate(ranked):
            scores[pid] = scores.get(pid, 0.0) + 1.0 / (60 + rank)
    return sorted(scores.items(), key=lambda kv: -kv[1])[:limit]
