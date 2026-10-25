"""Paper-paper relations: semantic neighbours, shared-entity edges and LLM-typed relations."""

from __future__ import annotations

import itertools
import sqlite3
from collections.abc import Callable

import numpy as np

from papermind.embed.index import load_matrix
from papermind.llm.schemas import RELATION_SYSTEM, RelationJudgement, relation_user_prompt

KNN = 3
MIN_SIM = 0.35
LLM_MIN_CONF = 0.6
LABEL_TO_TYPE = {
    "互补": "complements", "矛盾/挑战": "contradicts", "扩展": "extends",
    "同一问题的不同回答": "alternative", "方法借鉴": "borrows_method",
}  # fmt: skip
SYMMETRIC = {"similar", "complements", "contradicts", "alternative", "same_dataset", "same_team", "same_device"}
SHARED_TYPES = {"dataset": "same_dataset", "device": "same_device", "author": "same_team"}


def _pair(a: int, b: int, rtype: str) -> tuple[int, int]:
    return (min(a, b), max(a, b)) if rtype in SYMMETRIC else (a, b)


def _put(conn: sqlite3.Connection, a: int, b: int, rtype: str, score: float, evidence: str, origin: str) -> None:
    s, d = _pair(a, b, rtype)
    conn.execute(
        "INSERT INTO paper_relation(src_id, dst_id, type, score, evidence, origin) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(src_id, dst_id, type) DO UPDATE SET score=excluded.score, evidence=excluded.evidence "
        "WHERE paper_relation.origin != 'user'",
        (s, d, rtype, score, evidence, origin),
    )


def semantic_neighbours(conn: sqlite3.Connection, model: str, k: int = KNN) -> list[tuple[int, int, float]]:
    ids, mat = load_matrix(conn, model)
    if len(ids) < 2:
        return []
    sims = mat @ mat.T
    out: dict[tuple[int, int], float] = {}
    for i in range(len(ids)):
        order = [j for j in np.argsort(-sims[i]) if j != i][:k]
        for j in order:
            if sims[i, j] >= MIN_SIM:
                key = (min(ids[i], ids[j]), max(ids[i], ids[j]))
                out[key] = max(out.get(key, 0.0), float(sims[i, j]))
    return [(a, b, s) for (a, b), s in out.items()]


def shared_entity_pairs(conn: sqlite3.Connection) -> list[tuple[int, int, str, str]]:
    """Pairs of papers sharing a dataset/device/author entity: (a, b, relation type, entity name)."""
    out = []
    for etype, rtype in SHARED_TYPES.items():
        for e in conn.execute("SELECT id, name FROM entity WHERE type = ?", (etype,)):
            papers = [
                r["paper_id"]
                for r in conn.execute("SELECT DISTINCT paper_id FROM paper_entity WHERE entity_id = ?", (e["id"],))
            ]
            for a, b in itertools.combinations(sorted(papers), 2):
                out.append((a, b, rtype, e["name"]))
    return out


def _brief(conn: sqlite3.Connection, pid: int) -> dict:
    p = conn.execute("SELECT title, one_liner FROM paper WHERE id = ?", (pid,)).fetchone()
    secs = {
        r["kind"]: r["content_md"]
        for r in conn.execute("SELECT kind, content_md FROM paper_section WHERE paper_id = ?", (pid,))
    }
    return {
        "title": p["title"],
        "one_liner": p["one_liner"] or "",
        "results": secs.get("results", ""),
        "critique": secs.get("critique", ""),
    }


def rebuild_relations(
    conn: sqlite3.Connection,
    embed_model: str | None,
    llm_client=None,
    progress: Callable[[float, str], None] | None = None,
) -> dict:
    """Recompute auto relations (user-created ones are kept). Returns counts."""
    conn.execute("DELETE FROM paper_relation WHERE origin = 'auto'")
    counts = {"similar": 0, "shared": 0, "llm": 0}
    neighbours = semantic_neighbours(conn, embed_model) if embed_model else []
    for a, b, s in neighbours:
        _put(conn, a, b, "similar", s, "语义相似", "auto")
        counts["similar"] += 1
    for a, b, rtype, name in shared_entity_pairs(conn):
        _put(conn, a, b, rtype, 1.0, f"共同：{name}", "auto")
        counts["shared"] += 1
    if llm_client is not None:
        pairs = {(a, b) for a, b, _ in neighbours} | {(a, b) for a, b, _, _ in shared_entity_pairs(conn)}
        for i, (a, b) in enumerate(sorted(pairs)):
            try:
                r = llm_client.chat(
                    [{"role": "system", "content": RELATION_SYSTEM}, {"role": "user", "content": relation_user_prompt(_brief(conn, a), _brief(conn, b))}],
                    schema=RelationJudgement, max_tokens=200, retries=1,
                )  # fmt: skip
            except Exception:  # noqa: BLE001 - one failed pair must not abort the batch
                continue
            j: RelationJudgement = r.parsed  # type: ignore[assignment]
            if j.relation != "无明显关系" and j.confidence >= LLM_MIN_CONF:
                _put(conn, a, b, LABEL_TO_TYPE[j.relation], j.confidence, j.explanation, "auto")
                counts["llm"] += 1
            if progress:
                progress((i + 1) / max(1, len(pairs)), f"判定论文关系 {i + 1}/{len(pairs)}")
    conn.commit()
    return counts
