"""Read/write helpers for papers shared by the API routes."""

from __future__ import annotations

import json
import sqlite3

from papermind.pipeline.ingest import reindex_fts, title_norm

EDITABLE = {"title", "doi", "url", "code_url", "year", "venue", "abstract", "paper_type", "one_liner", "verification", "read_at"}  # fmt: skip
SECTION_KINDS = ["background", "methods", "results", "team", "critique", "key_numbers"]
VERIFICATIONS = ["全文已读", "部分章节", "仅摘要", "无法访问", "未核实"]


def paper_summary(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    cats = conn.execute(
        "SELECT c.id, c.name, pc.confidence, pc.origin, pc.is_primary FROM paper_category pc "
        "JOIN category c ON c.id = pc.category_id WHERE pc.paper_id = ? ORDER BY pc.is_primary DESC, pc.confidence DESC",
        (row["id"],),
    ).fetchall()
    n_follow = conn.execute("SELECT COUNT(*), COALESCE(SUM(is_correction),0) FROM followup WHERE paper_id=?", (row["id"],)).fetchone()  # fmt: skip
    return {
        "id": row["id"], "title": row["title"], "year": row["year"], "venue": row["venue"],
        "doi": row["doi"], "url": row["url"], "paper_type": row["paper_type"],
        "one_liner": row["one_liner"], "verification": row["verification"], "status": row["status"],
        "has_correction": bool(n_follow[1]), "followup_count": n_follow[0],
        "categories": [dict(c) for c in cats],
    }  # fmt: skip


def paper_detail(conn: sqlite3.Connection, pid: int) -> dict | None:
    row = conn.execute("SELECT * FROM paper WHERE id = ?", (pid,)).fetchone()
    if row is None:
        return None
    d = paper_summary(conn, row)
    d.update({k: row[k] for k in ("arxiv_id", "code_url", "abstract", "citation_count", "read_at", "created_at")})
    d["user_edited"] = json.loads(row["user_edited"])
    d["sections"] = {
        r["kind"]: {"content_md": r["content_md"], "origin": r["origin"]}
        for r in conn.execute("SELECT * FROM paper_section WHERE paper_id = ?", (pid,))
    }
    d["followups"] = [
        dict(r)
        for r in conn.execute(
            "SELECT id, question, answer_md, is_correction, turn_index FROM followup WHERE paper_id=? ORDER BY turn_index, id", (pid,)
        )
    ]  # fmt: skip
    ents: dict[str, list[str]] = {}
    for r in conn.execute(
        "SELECT e.type, e.name FROM entity e JOIN paper_entity pe ON pe.entity_id = e.id WHERE pe.paper_id = ? ORDER BY e.type, e.name",
        (pid,),
    ):
        ents.setdefault(r["type"], []).append(r["name"])
    d["entities"] = ents
    d["authors"] = [
        r["name"]
        for r in conn.execute(
            "SELECT a.name FROM author a JOIN paper_author pa ON pa.author_id=a.id WHERE pa.paper_id=? ORDER BY pa.position", (pid,)
        )
    ]  # fmt: skip
    return d


def update_paper(conn: sqlite3.Connection, pid: int, fields: dict, sections: dict) -> bool:
    row = conn.execute("SELECT user_edited FROM paper WHERE id = ?", (pid,)).fetchone()
    if row is None:
        return False
    edited = set(json.loads(row["user_edited"]))
    for k, v in fields.items():
        if k not in EDITABLE:
            continue
        conn.execute(f"UPDATE paper SET {k} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (v, pid))
        edited.add(k)
        if k == "title":
            conn.execute("UPDATE paper SET title_norm = ? WHERE id = ?", (title_norm(v), pid))
    for kind, text in sections.items():
        if kind not in SECTION_KINDS:
            continue
        conn.execute(
            "INSERT INTO paper_section(paper_id, kind, content_md, origin) VALUES (?,?,?, 'user') "
            "ON CONFLICT(paper_id, kind) DO UPDATE SET content_md=excluded.content_md, origin='user'",
            (pid, kind, text),
        )
    conn.execute("UPDATE paper SET user_edited = ? WHERE id = ?", (json.dumps(sorted(edited)), pid))
    reindex_fts(conn, pid)
    conn.commit()
    return True
