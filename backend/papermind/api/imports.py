from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from papermind.db.core import connect
from papermind.embed.index import ensure_paper_embeddings
from papermind.pipeline.ingest import import_text
from papermind.services.models import models
from papermind.services.tasks import Task, get_task, start_task

router = APIRouter(prefix="/api")


def run_import(task: Task, raw: str, filename: str, kind: str | None, use_llm: bool) -> dict:
    conn = connect()
    try:
        task.update(0.02, "解析并抽取 ...")
        client = None
        if use_llm and models.llm_available():
            try:
                client = models.llm()
            except Exception as e:  # noqa: BLE001 - fall back to rule extraction
                task.update(message=f"LLM 不可用，改用规则抽取：{e}")
        report = import_text(
            conn, raw, filename=filename, kind=kind, llm_client=client,
            progress=lambda p, m: task.update(0.05 + 0.75 * p, m),
        )  # fmt: skip
        out = report.as_dict()
        if models.embed_available():
            task.update(0.85, "生成向量 ...")
            try:
                c, spec = models.embedder()
                out["embedded"] = ensure_paper_embeddings(conn, c, spec, lambda p, m: task.update(0.85 + 0.1 * p, m))
            except Exception as e:  # noqa: BLE001
                out["embed_error"] = str(e)
        out["used_llm"] = client is not None
        return out
    finally:
        conn.close()


class PasteBody(BaseModel):
    text: str
    filename: str = "paste"
    kind: str | None = None
    use_llm: bool = True


@router.post("/import/text")
def import_pasted(body: PasteBody) -> dict:
    if not body.text.strip():
        raise HTTPException(400, "empty text")
    return start_task("import", lambda t: run_import(t, body.text, body.filename, body.kind, body.use_llm)).as_dict()


@router.post("/import/file")
async def import_file(file: UploadFile = File(...), use_llm: bool = Form(True)) -> dict:
    raw = (await file.read()).decode("utf-8", errors="replace")
    name = file.filename or "upload"
    return start_task("import", lambda t: run_import(t, raw, name, None, use_llm)).as_dict()


@router.get("/import/{task_id}")
def import_status(task_id: str) -> dict:
    t = get_task(task_id)
    if t is None:
        raise HTTPException(404, "task not found")
    return t.as_dict()
