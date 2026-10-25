"""Import pipeline: parse -> segment -> extract -> dedup/merge -> store (idempotent)."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field

from papermind.config import data_dir
from papermind.importers import chatgpt_json, plain_text
from papermind.importers.archive_md import (
    ArchiveParse,
    PaperSession,
    Turn,
    normalize_doi,
    parse_turns,
    segment,
)
from papermind.pipeline.extract import (
    Extracted,
    is_correction,
    llm_extract,
    main_turn,
    rule_extract,
)
from papermind.pipeline.lexicon import normalize_entity
from papermind.pipeline.yaml_meta import meta_to_fields, parse_yaml_block

SECTION_ORDER = ["background", "methods", "results", "team", "critique", "key_numbers"]
ENTITY_RELATION = {"dataset": "evaluates", "device": "uses"}


def title_norm(title: str) -> str:
    return re.sub(r"[\W_]+", "", title.casefold())


@dataclass
class ImportReport:
    source_id: int | None = None
    already_imported: bool = False
    new: int = 0
    merged: int = 0
    followups: int = 0
    inbox: int = 0
    non_paper: list[int] = field(default_factory=list)
    papers: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:24]


def find_existing(conn: sqlite3.Connection, doi: str, arxiv_id: str, tnorm: str) -> int | None:
    if doi:
        row = conn.execute("SELECT id FROM paper WHERE doi = ?", (doi,)).fetchone()
        if row:
            return row["id"]
    if arxiv_id:
        row = conn.execute("SELECT id FROM paper WHERE arxiv_id = ?", (arxiv_id,)).fetchone()
        if row:
            return row["id"]
    if tnorm:
        row = conn.execute("SELECT id FROM paper WHERE title_norm = ?", (tnorm,)).fetchone()
        if row:
            return row["id"]
    return None


def _edited(conn: sqlite3.Connection, paper_id: int) -> set[str]:
    row = conn.execute("SELECT user_edited FROM paper WHERE id = ?", (paper_id,)).fetchone()
    return set(json.loads(row["user_edited"])) if row else set()


def upsert_entities(conn: sqlite3.Connection, paper_id: int, ex: Extracted) -> None:
    pairs = [(t, n) for t, names in ex.entities.items() for n in names]
    pairs += [("insight", p) for p in ex.principles]
    for etype, name in pairs:
        name = normalize_entity(etype, name)
        if not name:
            continue
        conn.execute("INSERT OR IGNORE INTO entity(type, name) VALUES (?, ?)", (etype, name))
        eid = conn.execute("SELECT id FROM entity WHERE type = ? AND name = ?", (etype, name)).fetchone()["id"]
        relation = "illustrates" if etype == "insight" else ENTITY_RELATION.get(etype, "uses")
        conn.execute(
            "INSERT OR IGNORE INTO paper_entity(paper_id, entity_id, relation, origin) VALUES (?,?,?, 'ai')",
            (paper_id, eid, relation),
        )


def reindex_fts(conn: sqlite3.Connection, paper_id: int) -> None:
    p = conn.execute("SELECT title, one_liner, abstract FROM paper WHERE id = ?", (paper_id,)).fetchone()
    if p is None:
        return
    secs = [
        r["content_md"] for r in conn.execute("SELECT content_md FROM paper_section WHERE paper_id = ?", (paper_id,))
    ]
    fups = [
        f"{r['question']}\n{r['answer_md']}"
        for r in conn.execute("SELECT * FROM followup WHERE paper_id = ?", (paper_id,))
    ]
    ents = [r["name"] for r in conn.execute("SELECT e.name FROM entity e JOIN paper_entity pe ON pe.entity_id = e.id WHERE pe.paper_id = ?", (paper_id,))]  # fmt: skip
    body = "\n".join([p["one_liner"] or "", p["abstract"] or "", *secs, *fups, *ents])
    conn.execute("DELETE FROM paper_fts WHERE rowid = ?", (paper_id,))
    conn.execute("INSERT INTO paper_fts(rowid, title, body) VALUES (?, ?, ?)", (paper_id, p["title"], body))


def _store_sections(conn: sqlite3.Connection, paper_id: int, ex: Extracted) -> None:
    sections = dict(ex.sections)
    if ex.key_numbers:
        sections["key_numbers"] = "\n".join(f"- {n}" for n in ex.key_numbers)
    for kind in SECTION_ORDER:
        content = sections.get(kind)
        if not content:
            continue
        row = conn.execute("SELECT origin, content_md FROM paper_section WHERE paper_id=? AND kind=?", (paper_id, kind)).fetchone()  # fmt: skip
        if row is None:
            conn.execute("INSERT INTO paper_section(paper_id, kind, content_md, origin) VALUES (?,?,?, 'ai')", (paper_id, kind, content))  # fmt: skip
        elif row["origin"] == "ai" and len(content) > len(row["content_md"]):
            conn.execute("UPDATE paper_section SET content_md=? WHERE paper_id=? AND kind=?", (content, paper_id, kind))


def _upsert_paper(conn: sqlite3.Connection, s: PaperSession, ex: Extracted, fields: dict) -> tuple[int, bool]:
    """Insert or merge one paper. Returns (paper_id, merged_into_existing)."""
    title = fields.get("title") or s.title or ex.title
    doi = normalize_doi(fields.get("doi") or s.doi)
    tnorm = title_norm(title)
    pid = find_existing(conn, doi, s.arxiv_id, tnorm)
    values = {
        "title": title, "doi": doi or None, "arxiv_id": s.arxiv_id or None,
        "url": fields.get("url") or s.url or None, "code_url": fields.get("code_url") or s.code_url or None,
        "year": fields.get("year"), "venue": fields.get("venue") or None,
        "paper_type": ex.paper_type, "one_liner": ex.one_liner, "verification": ex.verification,
    }  # fmt: skip
    if pid is None:
        cur = conn.execute(
            "INSERT INTO paper(title, title_norm, doi, arxiv_id, url, code_url, year, venue, paper_type, one_liner, verification)"
            " VALUES (:title, :tn, :doi, :arxiv_id, :url, :code_url, :year, :venue, :paper_type, :one_liner, :verification)",
            {**values, "tn": tnorm},
        )  # fmt: skip
        return cur.lastrowid, False
    locked = _edited(conn, pid)
    row = conn.execute("SELECT * FROM paper WHERE id = ?", (pid,)).fetchone()
    for col, val in values.items():
        if col in locked or val in (None, ""):
            continue
        if row[col] in (None, "") or col in ("one_liner", "paper_type"):
            if col == "verification" and row[col] != "未核实":
                continue
            conn.execute(f"UPDATE paper SET {col} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (val, pid))
    return pid, True


def _followup(conn: sqlite3.Connection, pid: int, source_id: int, t: Turn) -> bool:
    h = _hash(t.user, t.assistant)
    answer = re.sub(r"^\*\*助手回复[^*]*\*\*\s*", "", t.assistant).strip()
    cur = conn.execute(
        "INSERT OR IGNORE INTO followup(paper_id, question, answer_md, is_correction, source_id, turn_index, content_hash)"
        " VALUES (?,?,?,?,?,?,?)",
        (pid, t.user, answer, int(is_correction(t)), source_id, t.index, h),
    )  # fmt: skip
    return cur.rowcount > 0


def ingest_sessions(
    conn: sqlite3.Connection,
    parse: ArchiveParse,
    source_id: int,
    *,
    llm_client=None,
    progress: Callable[[float, str], None] | None = None,
) -> ImportReport:
    report = ImportReport(source_id=source_id, non_paper=[t.index for t in parse.non_paper_turns])
    total = max(1, len(parse.papers))
    for i, s in enumerate(parse.papers):
        main = main_turn(s)
        meta = parse_yaml_block(main.assistant)
        fields = meta_to_fields(meta) if meta else {}
        ex = rule_extract(s)
        if fields:
            _apply_meta(ex, fields)
        elif llm_client is not None:
            ex = llm_extract(s, llm_client, ex)
        pid, merged = _upsert_paper(conn, s, ex, fields)
        _store_sections(conn, pid, ex)
        upsert_entities(conn, pid, ex)
        conn.execute(
            "INSERT OR REPLACE INTO paper_source(paper_id, source_id, turn_indexes) VALUES (?,?,?)",
            (pid, source_id, json.dumps(s.turn_indexes)),
        )  # fmt: skip
        n_follow = sum(
            _followup(conn, pid, source_id, t) for t in [*s.followups, *[t for t in s.turns if t is not main]]
        )
        report.followups += n_follow
        if merged or len(s.turns) > 1:
            report.merged += 1
        if not merged:
            report.new += 1
        report.papers.append(
            {"id": pid, "title": s.title or ex.title, "turns": s.turn_indexes,
             "action": "merged" if merged else "new", "followups": n_follow}
        )  # fmt: skip
        reindex_fts(conn, pid)
        if progress:
            progress((i + 1) / total, f"已处理 {i + 1}/{total}：{(s.title or '')[:40]}")
    conn.commit()
    return report


def _apply_meta(ex: Extracted, f: dict) -> None:
    ex.paper_type = f["paper_type"] or ex.paper_type
    ex.one_liner = f["one_liner"] or ex.one_liner
    ex.verification = f["verification"] or ex.verification
    ex.sample_size = f["sample_size"] or ex.sample_size
    for etype, names in f["entities"].items():
        cur = ex.entities.setdefault(etype, [])
        cur.extend(n for n in names if n not in cur)
    ex.principles.extend(p for p in f["principles"] if p not in ex.principles)


def import_text(
    conn: sqlite3.Connection,
    raw: str,
    *,
    filename: str = "paste",
    kind: str | None = None,
    llm_client=None,
    progress: Callable[[float, str], None] | None = None,
) -> ImportReport:
    sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    existing = conn.execute("SELECT id FROM source WHERE sha256 = ?", (sha,)).fetchone()
    if existing:
        return ImportReport(source_id=existing["id"], already_imported=True)

    force_first = False
    if kind == "chatgpt_json" or (kind is None and chatgpt_json.looks_like_chatgpt_export(raw)):
        kind = "chatgpt_json"
        convs = chatgpt_json.parse_conversations(raw)
        turns_groups = [t for _, t in convs]
    elif kind == "archive_md" or (kind is None and plain_text.is_archive(raw)):
        kind = "archive_md"
        turns_groups = [parse_turns(raw)]
    else:
        chat = plain_text.parse_chat(raw)
        kind = "paste"
        turns_groups = [chat if chat is not None else plain_text.single_summary(raw)]
        force_first = True

    raw_dir = data_dir() / "raw"
    raw_dir.mkdir(exist_ok=True)
    raw_path = raw_dir / f"{sha[:16]}.{'json' if kind == 'chatgpt_json' else 'md'}"
    raw_path.write_text(raw, encoding="utf-8")  # raw imports are never modified afterwards
    cur = conn.execute("INSERT INTO source(kind, filename, sha256, raw_path) VALUES (?,?,?,?)", (kind, filename, sha, str(raw_path)))  # fmt: skip
    source_id = cur.lastrowid

    merged = ImportReport(source_id=source_id)
    for turns in turns_groups:
        parse = segment(turns, force_first=force_first)
        r = ingest_sessions(conn, parse, source_id, llm_client=llm_client, progress=progress)
        merged.new += r.new
        merged.merged += r.merged
        merged.followups += r.followups
        merged.non_paper += r.non_paper
        merged.papers += r.papers
    conn.execute(
        "UPDATE source SET report = ? WHERE id = ?", (json.dumps(merged.as_dict(), ensure_ascii=False), source_id)
    )
    conn.commit()
    return merged
