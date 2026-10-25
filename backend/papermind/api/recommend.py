from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from papermind.api.deps import get_conn
from papermind.db.core import connect
from papermind.resources.prompts import IMPROVED_PROMPT
from papermind.services import qa, recommend
from papermind.services.models import models
from papermind.services.tasks import start_task

router = APIRouter(prefix="/api")


@router.post("/recommendations/refresh")
def refresh(use_llm: bool = True) -> dict:
    def run(task):
        if not models.embed_available():
            raise RuntimeError("嵌入模型尚未就绪，请先在设置页下载模型")
        conn = connect()
        try:
            client, spec = models.embedder()
            llm = models.llm() if (use_llm and models.llm_available()) else None
            return recommend.refresh(conn, client, spec, llm, progress=lambda p, m: task.update(p, m))
        finally:
            conn.close()

    return start_task("recommend", run).as_dict()


@router.get("/recommendations")
def list_recs(
    group: str = "", status: str = "new", limit: int = 50, conn: sqlite3.Connection = Depends(get_conn)
) -> list[dict]:
    return recommend.list_candidates(conn, group, status, limit)


class Feedback(BaseModel):
    value: int  # 1 like, -1 dislike, 0 already read


@router.post("/recommendations/{cid}/feedback")
def feedback(cid: int, body: Feedback, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    if body.value not in (1, -1, 0):
        raise HTTPException(400, "value must be 1, -1 or 0")
    if conn.execute("SELECT 1 FROM candidate WHERE id = ?", (cid,)).fetchone() is None:
        raise HTTPException(404, "candidate not found")
    model = models.selected("embed").id if models.embed_available() else None
    recommend.give_feedback(conn, cid, body.value, model)
    return {"ok": True}


@router.get("/prompt")
def prompt(paper_url: str = "") -> dict:
    text = IMPROVED_PROMPT + (f"\n\n论文：{paper_url}" if paper_url else "")
    return {"prompt": text}


class AuthorIn(BaseModel):
    name: str


@router.get("/authors")
def authors(followed: bool = False, conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    q = "SELECT a.*, COUNT(pa.paper_id) AS n_papers FROM author a LEFT JOIN paper_author pa ON pa.author_id = a.id"
    if followed:
        q += " WHERE a.followed = 1"
    return [dict(r) for r in conn.execute(q + " GROUP BY a.id ORDER BY a.followed DESC, n_papers DESC, a.name")]


@router.post("/authors")
def add_author(body: AuthorIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    name = body.name.strip()
    row = conn.execute("SELECT id FROM author WHERE name = ?", (name,)).fetchone()
    if row:
        conn.execute("UPDATE author SET followed = 1 WHERE id = ?", (row["id"],))
    else:
        conn.execute("INSERT INTO author(name, followed) VALUES (?, 1)", (name,))
    conn.commit()
    return {"ok": True}


@router.post("/authors/{aid}/follow")
def follow(aid: int, value: bool = True, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    conn.execute("UPDATE author SET followed = ? WHERE id = ?", (int(value), aid))
    conn.commit()
    return {"ok": True}


class QABody(BaseModel):
    question: str
    use_llm: bool = True
    stream: bool = False


@router.post("/qa")
def ask(body: QABody):
    conn = connect()
    llm = None
    if body.use_llm and models.llm_available():
        try:
            llm = models.llm()
        except Exception:  # noqa: BLE001
            llm = None
    if body.stream:

        def gen():
            try:
                yield from qa.stream_answer(conn, body.question, llm)
            finally:
                conn.close()

        return StreamingResponse(gen(), media_type="text/event-stream")
    try:
        return qa.answer(conn, body.question, llm)
    finally:
        conn.close()
