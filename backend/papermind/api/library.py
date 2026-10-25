from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from papermind.api.deps import get_conn
from papermind.services import backup, export, review

router = APIRouter(prefix="/api")


@router.get("/stats")
def stats(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    one = lambda q: conn.execute(q).fetchone()[0]  # noqa: E731
    return {
        "papers": one("SELECT COUNT(*) FROM paper"), "followups": one("SELECT COUNT(*) FROM followup"),
        "inbox": one("SELECT COUNT(*) FROM inbox"), "categories": one("SELECT COUNT(*) FROM category"),
        "entities": one("SELECT COUNT(*) FROM entity"), "due_cards": review.due_count(conn),
    }  # fmt: skip


@router.get("/export")
def export_all(format: str = "json", conn: sqlite3.Connection = Depends(get_conn)):
    if format == "json":
        return JSONResponse(
            export.export_json(conn), headers={"Content-Disposition": 'attachment; filename="papermind-export.json"'}
        )
    if format == "md":
        return PlainTextResponse(
            export.export_markdown(conn), headers={"Content-Disposition": 'attachment; filename="papermind.md"'}
        )
    if format == "bibtex":
        return PlainTextResponse(
            export.export_bibtex(conn), headers={"Content-Disposition": 'attachment; filename="papermind.bib"'}
        )
    if format == "obsidian":
        return Response(
            export.export_obsidian(conn),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="papermind-obsidian.zip"'},
        )
    raise HTTPException(400, "format must be json, md, obsidian or bibtex")


@router.post("/import/json")
async def import_json(file: UploadFile = File(...), conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    try:
        data = json.loads((await file.read()).decode("utf-8"))
        backup.create_backup()  # replacing the library: keep a safety copy first
        return {"counts": export.import_json(conn, data)}
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e)) from e


@router.get("/backups")
def backups() -> list[dict]:
    return backup.list_backups()


@router.post("/backups")
def make_backup() -> dict:
    return {"name": backup.create_backup()}


@router.get("/review/due")
def review_due(limit: int = 20, conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    return review.due_cards(conn, limit)


@router.post("/review/{paper_id}")
def review_answer(paper_id: int, rating: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    try:
        return review.answer_card(conn, paper_id, rating)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e)) from e
