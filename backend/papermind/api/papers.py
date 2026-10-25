from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from papermind.api.deps import get_conn
from papermind.embed.index import from_blob, nearest
from papermind.services import papers as svc
from papermind.services.models import models
from papermind.services.search import hybrid_search

router = APIRouter(prefix="/api")


@router.get("/papers")
def list_papers(
    q: str = "",
    mode: str = Query("hybrid", pattern="^(hybrid|keyword|semantic)$"),
    paper_type: str = "",
    verification: str = "",
    category: int | None = None,
    entity: str = "",
    limit: int = Query(50, le=500),
    offset: int = 0,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    where, params = ["1=1"], []
    if paper_type:
        where.append("p.paper_type = ?")
        params.append(paper_type)
    if verification:
        where.append("p.verification = ?")
        params.append(verification)
    if category is not None:
        where.append("p.id IN (SELECT paper_id FROM paper_category WHERE category_id = ?)")
        params.append(category)
    if entity:
        where.append(
            "p.id IN (SELECT pe.paper_id FROM paper_entity pe JOIN entity e ON e.id=pe.entity_id WHERE e.name = ?)"
        )
        params.append(entity)
    sql = f"SELECT p.* FROM paper p WHERE {' AND '.join(where)}"
    if q.strip():
        ranked = hybrid_search(conn, q, 200, mode)
        order = {pid: i for i, (pid, _) in enumerate(ranked)}
        rows = [r for r in conn.execute(sql, params) if r["id"] in order]
        rows.sort(key=lambda r: order[r["id"]])
    else:
        rows = conn.execute(sql + " ORDER BY p.id", params).fetchall()
    total = len(rows)
    return {"total": total, "items": [svc.paper_summary(conn, r) for r in rows[offset : offset + limit]]}


@router.get("/papers/{pid}")
def get_paper(pid: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    d = svc.paper_detail(conn, pid)
    if d is None:
        raise HTTPException(404, "paper not found")
    return d


class PaperPatch(BaseModel):
    fields: dict = {}
    sections: dict = {}


@router.patch("/papers/{pid}")
def patch_paper(pid: int, body: PaperPatch, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    if not svc.update_paper(conn, pid, body.fields, body.sections):
        raise HTTPException(404, "paper not found")
    return svc.paper_detail(conn, pid)  # type: ignore[return-value]


@router.delete("/papers/{pid}")
def delete_paper(pid: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    conn.execute("DELETE FROM paper_fts WHERE rowid = ?", (pid,))
    conn.execute("DELETE FROM embedding WHERE owner_type = 'paper' AND owner_id = ?", (pid,))
    conn.execute("DELETE FROM paper WHERE id = ?", (pid,))
    conn.commit()
    return {"ok": True}


@router.get("/papers/{pid}/related")
def related(pid: int, k: int = 8, conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    out: list[dict] = []
    seen: set[int] = set()
    for r in conn.execute(
        "SELECT pr.*, CASE WHEN pr.src_id = ? THEN pr.dst_id ELSE pr.src_id END AS other FROM paper_relation pr "
        "WHERE (pr.src_id = ? OR pr.dst_id = ?) ORDER BY pr.score DESC",
        (pid, pid, pid),
    ):
        p = conn.execute("SELECT id, title, one_liner FROM paper WHERE id = ?", (r["other"],)).fetchone()
        out.append({**dict(p), "relation": r["type"], "evidence": r["evidence"], "score": r["score"]})
        seen.add(r["other"])
    if models.embed_available():
        spec = models.selected("embed")
        row = conn.execute(
            "SELECT vector FROM embedding WHERE owner_type='paper' AND owner_id=? AND model=?", (pid, spec.id)
        ).fetchone()
        if row:
            for other, score in nearest(conn, spec.id, from_blob(row["vector"]), k + len(seen), exclude=pid):
                if other in seen:
                    continue
                p = conn.execute("SELECT id, title, one_liner FROM paper WHERE id = ?", (other,)).fetchone()
                out.append({**dict(p), "relation": "similar", "evidence": "语义相似", "score": score})
    return out[: k + len(seen)]
