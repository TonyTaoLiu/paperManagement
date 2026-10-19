from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from papermind.api.deps import get_conn
from papermind.db.core import connect
from papermind.embed.index import ensure_paper_embeddings
from papermind.services import digest as digest_svc
from papermind.services import graph, relations
from papermind.services.models import models
from papermind.services.tasks import start_task

router = APIRouter(prefix="/api")


@router.get("/graph")
def get_graph(
    view: str = Query("global", pattern="^(global|paper|concept)$"),
    focus: int | None = None,
    types: str = "",
    min_papers: int = 2,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    return graph.build_graph(conn, view, focus, [t for t in types.split(",") if t] or None, min_papers)


@router.get("/map")
def get_map(conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    spec = models.selected("embed")
    return graph.semantic_map(conn, spec.id)


@router.get("/timeline")
def timeline(conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    """Papers in reading order: explicit read_at first, otherwise the order they appear in the import."""
    import json

    first_turn = {
        r["paper_id"]: min(json.loads(r["turn_indexes"]) or [0])
        for r in conn.execute("SELECT paper_id, turn_indexes FROM paper_source")
    }
    rows = conn.execute("SELECT id, title, one_liner, read_at, year FROM paper").fetchall()
    rows = sorted(rows, key=lambda r: (r["read_at"] or "9999", first_turn.get(r["id"], 10**6), r["id"]))
    return [{"id": r["id"], "title": r["title"], "one_liner": r["one_liner"], "read_at": r["read_at"], "year": r["year"], "order": i + 1} for i, r in enumerate(rows)]  # fmt: skip


@router.post("/relations/rebuild")
def rebuild(use_llm: bool = True) -> dict:
    def run(task):
        conn = connect()
        try:
            model = None
            if models.embed_available():
                client, spec = models.embedder()
                task.update(0.05, "向量化 ...")
                ensure_paper_embeddings(conn, client, spec)
                model = spec.id
            llm = models.llm() if (use_llm and models.llm_available()) else None
            return relations.rebuild_relations(conn, model, llm, lambda p, m: task.update(0.1 + 0.9 * p, m))
        finally:
            conn.close()

    return start_task("relations", run).as_dict()


class EntityMerge(BaseModel):
    keep_id: int
    merge_ids: list[int]


@router.get("/entities")
def list_entities(type: str = "", conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    q = "SELECT e.*, COUNT(pe.paper_id) AS n_papers FROM entity e LEFT JOIN paper_entity pe ON pe.entity_id = e.id"
    params: list = []
    if type:
        q += " WHERE e.type = ?"
        params.append(type)
    return [dict(r) for r in conn.execute(q + " GROUP BY e.id ORDER BY n_papers DESC, e.name", params)]


@router.post("/entities/merge")
def merge_entities(body: EntityMerge, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    import json

    keep = conn.execute("SELECT * FROM entity WHERE id = ?", (body.keep_id,)).fetchone()
    if keep is None:
        raise HTTPException(404, "entity not found")
    aliases = set(json.loads(keep["aliases"]))
    for mid in body.merge_ids:
        if mid == body.keep_id:
            continue
        m = conn.execute("SELECT * FROM entity WHERE id = ?", (mid,)).fetchone()
        if m is None or m["type"] != keep["type"]:
            continue
        aliases.add(m["name"])
        aliases.update(json.loads(m["aliases"]))
        conn.execute("UPDATE OR IGNORE paper_entity SET entity_id = ? WHERE entity_id = ?", (body.keep_id, mid))
        conn.execute("DELETE FROM entity WHERE id = ?", (mid,))
    conn.execute(
        "UPDATE entity SET aliases = ? WHERE id = ?", (json.dumps(sorted(aliases), ensure_ascii=False), body.keep_id)
    )
    conn.commit()
    return {"ok": True}


@router.get("/digests/{cid}")
def get_digest(cid: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    d = digest_svc.get_digest(conn, cid)
    if d is None:
        prop = digest_svc.propose(conn, cid, None)
        if not prop["content_md"]:
            raise HTTPException(404, "no papers in this topic")
        d = digest_svc.save_digest(conn, cid, prop["content_md"], prop["source_paper_ids"])
    return d


class DigestAccept(BaseModel):
    content_md: str
    source_paper_ids: list[int]


@router.post("/digests/{cid}/propose")
def propose_digest(cid: int, use_llm: bool = True, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    client = None
    if use_llm and models.llm_available():
        try:
            client = models.llm()
        except Exception:  # noqa: BLE001
            client = None
    prop = digest_svc.propose(conn, cid, client)
    old = digest_svc.get_digest(conn, cid)
    prop["diff"] = digest_svc.diff(old["content_md"], prop["content_md"]) if old else ""
    return prop


@router.post("/digests/{cid}/accept")
def accept_digest(cid: int, body: DigestAccept, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    return digest_svc.save_digest(conn, cid, body.content_md, body.source_paper_ids)


@router.get("/digests/{cid}/health")
def digest_health(cid: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    return digest_svc.health_check(conn, cid)
