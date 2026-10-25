from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from papermind.api.deps import get_conn
from papermind.db.core import connect
from papermind.services import classify, taxonomy
from papermind.services.tasks import start_task

router = APIRouter(prefix="/api")


class CategoryIn(BaseModel):
    name: str
    description: str = ""
    parent_id: int | None = None


class CategoryPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    parent_id: int | None = None
    move: bool = False  # set true to apply parent_id (even when null = make top-level)


@router.get("/categories")
def tree(conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    return taxonomy.list_tree(conn)


@router.post("/categories")
def create(body: CategoryIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    return {"id": taxonomy.create(conn, body.name, body.description, body.parent_id)}


@router.patch("/categories/{cid}")
def patch(cid: int, body: CategoryPatch, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    fields = {k: v for k, v in body.model_dump(exclude={"move", "parent_id"}).items() if v is not None}
    if body.move:
        fields["parent_id"] = body.parent_id
    try:
        taxonomy.update(conn, cid, **fields)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}


@router.delete("/categories/{cid}")
def delete(cid: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    taxonomy.delete(conn, cid)
    return {"ok": True}


@router.post("/categories/preset")
def preset(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    if taxonomy.flat(conn):
        raise HTTPException(409, "taxonomy is not empty")
    return {"ids": taxonomy.seed_preset(conn)}


@router.post("/categories/propose")
def propose() -> dict:
    def run(task):
        conn = connect()
        try:
            return classify.propose_taxonomy(conn)
        finally:
            conn.close()

    return start_task("propose-taxonomy", run).as_dict()


class ProposalIn(BaseModel):
    categories: list[dict]


@router.post("/categories/apply-proposal")
def apply_proposal(body: ProposalIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    return {"ids": classify.apply_proposal(conn, body.model_dump())}


@router.get("/categories/{cid}/split")
def split(cid: int, k: int = 2, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    return classify.suggest_split(conn, cid, k)


class ClassifyIn(BaseModel):
    paper_ids: list[int] | None = None
    use_llm: bool = True


@router.post("/classify")
def classify_all(body: ClassifyIn) -> dict:
    def run(task):
        conn = connect()
        try:
            return classify.classify_papers(conn, body.paper_ids, task, body.use_llm)
        finally:
            conn.close()

    return start_task("classify", run).as_dict()


class SetCategories(BaseModel):
    category_ids: list[int]
    primary: int | None = None


@router.put("/papers/{pid}/categories")
def set_cats(pid: int, body: SetCategories, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    classify.set_categories(conn, pid, body.category_ids, body.primary)
    return {"ok": True}


@router.get("/inbox")
def inbox(conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    return classify.inbox_items(conn)


class Decision(BaseModel):
    action: str  # confirm | change | reject | new
    category_id: int | None = None
    new_name: str = ""
    new_description: str = ""


@router.post("/inbox/{pid}/decision")
def decision(pid: int, body: Decision, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    try:
        return classify.decide(conn, pid, body.action, body.category_id, body.new_name, body.new_description)
    except (AssertionError, ValueError) as e:
        raise HTTPException(400, str(e)) from e
