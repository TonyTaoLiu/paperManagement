"""Batch classification, taxonomy proposal and inbox decisions."""

from __future__ import annotations

import json
import sqlite3

import numpy as np

from papermind.embed.index import ensure_paper_embeddings
from papermind.llm.schemas import TAXONOMY_SYSTEM, TaxonomyProposal, taxonomy_user_prompt
from papermind.services import router, taxonomy
from papermind.services.models import models
from papermind.services.tasks import Task


def classify_papers(
    conn: sqlite3.Connection, paper_ids: list[int] | None = None, task: Task | None = None, use_llm: bool = True
) -> dict:
    """Route papers that have no category yet (or the given ids). Returns counts."""
    client, spec = models.embedder()
    ensure_paper_embeddings(conn, client, spec)
    if paper_ids is None:
        paper_ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM paper WHERE id NOT IN (SELECT paper_id FROM paper_category) AND id NOT IN (SELECT paper_id FROM inbox)"
            )
        ]
    llm = None
    if use_llm and models.llm_available():
        try:
            llm = models.llm()
        except Exception:  # noqa: BLE001
            llm = None
    out = {"auto": 0, "inbox": 0, "new": 0, "used_llm": llm is not None}
    for i, pid in enumerate(paper_ids):
        res = router.route_paper(conn, pid, client, spec, llm)
        router.apply_result(conn, pid, res)
        out[res.decision] += 1
        if task:
            task.update((i + 1) / max(1, len(paper_ids)), f"分类 {i + 1}/{len(paper_ids)}")
    return out


def propose_taxonomy(conn: sqlite3.Connection) -> dict:
    papers = [
        (r["title"], r["one_liner"] or "") for r in conn.execute("SELECT title, one_liner FROM paper ORDER BY id")
    ]
    if not papers:
        return {"categories": []}
    client = models.llm()
    r = client.chat(
        [{"role": "system", "content": TAXONOMY_SYSTEM}, {"role": "user", "content": taxonomy_user_prompt(papers)}],
        schema=TaxonomyProposal, max_tokens=1800, retries=1,
    )  # fmt: skip
    return r.parsed.model_dump()  # type: ignore[union-attr]


def apply_proposal(conn: sqlite3.Connection, proposal: dict) -> list[int]:
    ids = []
    for top in proposal.get("categories", []):
        pid = taxonomy.create(conn, top["name"], top.get("description", ""), None, "ai")
        ids.append(pid)
        for ch in top.get("children", []):
            ids.append(taxonomy.create(conn, ch["name"], ch.get("description", ""), pid, "ai"))
    return ids


def set_categories(
    conn: sqlite3.Connection, paper_id: int, category_ids: list[int], primary: int | None = None, origin: str = "user"
) -> None:
    conn.execute("DELETE FROM paper_category WHERE paper_id = ?", (paper_id,))
    for cid in category_ids:
        conn.execute(
            "INSERT INTO paper_category(paper_id, category_id, confidence, origin, is_primary) VALUES (?,?,1.0,?,?)",
            (paper_id, cid, origin, int(cid == (primary or category_ids[0]))),
        )
        conn.execute("DELETE FROM category_rejection WHERE paper_id=? AND category_id=?", (paper_id, cid))
    conn.execute("DELETE FROM inbox WHERE paper_id = ?", (paper_id,))
    conn.commit()


def inbox_items(conn: sqlite3.Connection) -> list[dict]:
    from papermind.services.papers import paper_summary

    out = []
    for r in conn.execute("SELECT * FROM inbox ORDER BY created_at, paper_id"):
        p = conn.execute("SELECT * FROM paper WHERE id = ?", (r["paper_id"],)).fetchone()
        out.append({**paper_summary(conn, p), "suggestions": json.loads(r["suggestions"]), "reason": r["reason"]})
    return out


def decide(
    conn: sqlite3.Connection,
    paper_id: int,
    action: str,
    category_id: int | None = None,
    new_name: str = "",
    new_description: str = "",
) -> dict:
    if action in ("confirm", "change"):
        assert category_id is not None
        set_categories(conn, paper_id, [category_id])
        return {"ok": True}
    if action == "new":
        cid = taxonomy.create(conn, new_name, new_description, None, "user")
        set_categories(conn, paper_id, [cid])
        return {"ok": True, "category_id": cid}
    if action == "reject":
        assert category_id is not None
        conn.execute(
            "INSERT OR IGNORE INTO category_rejection(paper_id, category_id) VALUES (?,?)", (paper_id, category_id)
        )
        conn.commit()
        client, spec = models.embedder()
        res = router.route_paper(conn, paper_id, client, spec, None)
        router.apply_result(conn, paper_id, res) if res.decision != "auto" else None
        return {"ok": True, "suggestions": [s.__dict__ for s in res.suggestions]}
    raise ValueError(f"unknown action {action}")


def suggest_split(conn: sqlite3.Connection, category_id: int, k: int = 2) -> dict:
    """Cluster a large category's papers into k groups (k-means on embeddings) to suggest sub-categories."""
    client, spec = models.embedder()
    ensure_paper_embeddings(conn, client, spec)
    pvecs = router.paper_vectors(conn, spec.id)
    ids = [r["paper_id"] for r in conn.execute("SELECT paper_id FROM paper_category WHERE category_id = ?", (category_id,)) if r["paper_id"] in pvecs]  # fmt: skip
    if len(ids) < max(4, k * 2):
        return {"clusters": []}
    X = np.stack([pvecs[i] for i in ids])
    rng = np.random.default_rng(0)
    cent = X[rng.choice(len(ids), k, replace=False)]
    labels = np.zeros(len(ids), dtype=int)
    for _ in range(25):
        labels = np.argmax(X @ cent.T, axis=1)
        for j in range(k):
            if (labels == j).any():
                c = X[labels == j].mean(axis=0)
                cent[j] = c / (np.linalg.norm(c) or 1)
    clusters = []
    for j in range(k):
        members = [ids[i] for i in range(len(ids)) if labels[i] == j]
        titles = [conn.execute("SELECT title FROM paper WHERE id = ?", (m,)).fetchone()[0] for m in members]
        clusters.append({"paper_ids": members, "titles": titles})
    return {"clusters": clusters}
