"""Exports (Markdown / Obsidian / BibTeX / JSON) and lossless JSON re-import."""

from __future__ import annotations

import io
import json
import re
import sqlite3
import zipfile

from papermind.pipeline.ingest import reindex_fts

# Tables that make up user data (embeddings are derived and rebuilt on demand).
TABLES = [
    "source", "paper", "paper_source", "paper_section", "followup", "author", "paper_author", "category",
    "paper_category", "category_rejection", "inbox", "entity", "paper_entity", "paper_relation", "digest",
    "review_card", "candidate", "feedback",
]  # fmt: skip
SECTION_TITLES = {
    "background": "研究背景与问题", "methods": "研究方法与数据", "results": "重要结果与结论",
    "team": "团队与前后文献", "critique": "批判性思考", "key_numbers": "关键数字",
}  # fmt: skip


def export_json(conn: sqlite3.Connection) -> dict:
    data = {"format": "papermind-export", "version": 1, "tables": {}}
    for t in TABLES:
        rows = conn.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall()
        data["tables"][t] = [dict(r) for r in rows]
    return data


def import_json(conn: sqlite3.Connection, data: dict) -> dict:
    """Replace the library with the exported data (caller makes a backup first)."""
    if data.get("format") != "papermind-export":
        raise ValueError("not a PaperMind export")
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        for t in reversed(TABLES):
            conn.execute(f"DELETE FROM {t}")
        conn.execute("DELETE FROM embedding")
        conn.execute("DELETE FROM paper_fts")
        counts = {}
        for t in TABLES:
            rows = data["tables"].get(t, [])
            for r in rows:
                cols = list(r)
                conn.execute(
                    f"INSERT INTO {t}({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [r[c] for c in cols]
                )
            counts[t] = len(rows)
        for p in conn.execute("SELECT id FROM paper").fetchall():
            reindex_fts(conn, p["id"])
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    return counts


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|#^\[\]]+', " ", name).strip()[:90] or "untitled"


def _paper_md(conn: sqlite3.Connection, p: sqlite3.Row, obsidian: bool) -> str:
    secs = {
        r["kind"]: r["content_md"]
        for r in conn.execute("SELECT kind, content_md FROM paper_section WHERE paper_id = ?", (p["id"],))
    }
    cats = [
        r["name"]
        for r in conn.execute(
            "SELECT c.name FROM paper_category pc JOIN category c ON c.id = pc.category_id WHERE pc.paper_id = ?",
            (p["id"],),
        )
    ]
    ents: dict[str, list[str]] = {}
    for r in conn.execute(
        "SELECT e.type, e.name FROM entity e JOIN paper_entity pe ON pe.entity_id = e.id WHERE pe.paper_id = ?",
        (p["id"],),
    ):
        ents.setdefault(r["type"], []).append(r["name"])
    lines: list[str] = []
    if obsidian:
        lines += ["---", f"title: {json.dumps(p['title'], ensure_ascii=False)}", f"doi: {p['doi'] or ''}", f"year: {p['year'] or ''}",
                  f"type: {p['paper_type'] or ''}", f"verification: {p['verification']}",
                  "tags: [" + ", ".join(json.dumps(c, ensure_ascii=False) for c in cats) + "]", "---"]  # fmt: skip
    lines += [f"# {p['title']}", ""]
    if p["one_liner"]:
        lines += [f"> {p['one_liner']}", ""]
    meta = [f"核实状态：{p['verification']}", f"类型：{p['paper_type'] or '—'}"]
    if p["url"]:
        meta.append(f"原文：<{p['url']}>")
    if p["code_url"]:
        meta.append(f"代码：<{p['code_url']}>")
    lines += ["；".join(meta), ""]
    for kind, title in SECTION_TITLES.items():
        if secs.get(kind):
            lines += [f"## {title}", "", secs[kind], ""]
    fups = conn.execute(
        "SELECT question, answer_md, is_correction FROM followup WHERE paper_id = ? ORDER BY turn_index, id", (p["id"],)
    ).fetchall()
    if fups:
        lines += ["## 追问记录", ""]
        for f in fups:
            lines += [f"**问{'（纠错）' if f['is_correction'] else ''}：** {f['question']}", "", f["answer_md"], ""]
    if ents:
        lines += ["## 实体", ""]
        for t, names in ents.items():
            links = ", ".join(f"[[{n}]]" if obsidian and t == "insight" else n for n in names)
            lines.append(f"- {t}：{links}")
        lines.append("")
    if obsidian:
        rel = conn.execute(
            "SELECT p2.title, pr.type, pr.evidence FROM paper_relation pr JOIN paper p2 ON p2.id = CASE WHEN pr.src_id = ? THEN pr.dst_id ELSE pr.src_id END "
            "WHERE (pr.src_id = ? OR pr.dst_id = ?) AND pr.type != 'similar'", (p["id"], p["id"], p["id"]),
        ).fetchall()  # fmt: skip
        if rel:
            lines += ["## 相关论文", ""]
            lines += [f"- [[{_safe(r['title'])}]] — {r['type']}：{r['evidence'] or ''}" for r in rel]
            lines.append("")
    return "\n".join(lines)


def export_markdown(conn: sqlite3.Connection) -> str:
    parts = ["# PaperMind 导出", ""]
    for p in conn.execute("SELECT * FROM paper ORDER BY id"):
        parts += [_paper_md(conn, p, False), "\n---\n"]
    return "\n".join(parts)


def export_obsidian(conn: sqlite3.Connection) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in conn.execute("SELECT * FROM paper ORDER BY id"):
            z.writestr(f"Papers/{_safe(p['title'])}.md", _paper_md(conn, p, True))
        for c in conn.execute("SELECT * FROM category WHERE facet = 'topic'"):
            ps = [
                r["title"]
                for r in conn.execute(
                    "SELECT p.title FROM paper p JOIN paper_category pc ON pc.paper_id = p.id WHERE pc.category_id = ?",
                    (c["id"],),
                )
            ]
            d = conn.execute("SELECT content_md FROM digest WHERE category_id = ?", (c["id"],)).fetchone()
            body = f"# {c['name']}\n\n{c['description']}\n\n## 论文\n\n" + "\n".join(f"- [[{_safe(t)}]]" for t in ps)
            if d:
                body += "\n\n## 综述\n\n" + re.sub(r"\[P(\d+)\]\(#/paper/\d+\)", r"P\1", d["content_md"])
            z.writestr(f"Topics/{_safe(c['name'])}.md", body)
        for e in conn.execute("SELECT * FROM entity WHERE type = 'insight'"):
            ps = [
                r["title"]
                for r in conn.execute(
                    "SELECT p.title FROM paper p JOIN paper_entity pe ON pe.paper_id = p.id WHERE pe.entity_id = ?",
                    (e["id"],),
                )
            ]
            z.writestr(
                f"Insights/{_safe(e['name'])}.md",
                f"# {e['name']}\n\n例证论文：\n\n" + "\n".join(f"- [[{_safe(t)}]]" for t in ps),
            )
    return buf.getvalue()


def export_bibtex(conn: sqlite3.Connection) -> str:
    out = []
    for p in conn.execute("SELECT * FROM paper ORDER BY id"):
        authors = [
            r["name"]
            for r in conn.execute(
                "SELECT a.name FROM author a JOIN paper_author pa ON pa.author_id = a.id WHERE pa.paper_id = ? ORDER BY pa.position",
                (p["id"],),
            )
        ]
        first = re.sub(r"[^A-Za-z]", "", authors[0].split()[-1]) if authors else "paper"
        word = re.sub(r"[^a-z]", "", (re.findall(r"[A-Za-z]{4,}", p["title"]) or ["x"])[0].lower())
        key = f"{first.lower()}{p['year'] or ''}{word}{p['id']}"
        fields = {
            "title": "{" + p["title"] + "}",
            "author": " and ".join(authors),
            "journal": p["venue"],
            "year": p["year"],
            "doi": p["doi"],
            "url": p["url"],
        }
        body = ",\n".join(f"  {k} = {{{v}}}" if k != "title" else f"  title = {v}" for k, v in fields.items() if v)
        out.append(f"@article{{{key},\n{body}\n}}")
    return "\n\n".join(out) + "\n"
