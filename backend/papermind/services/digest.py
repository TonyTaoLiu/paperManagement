"""Topic digests (综述页): every statement carries source paper ids."""

from __future__ import annotations

import difflib
import json
import sqlite3
from datetime import UTC, datetime

from papermind.llm.schemas import DIGEST_SYSTEM, DigestDraft
from papermind.services import taxonomy

SECTIONS = [
    ("core_question", "核心问题"), ("relations", "论文之间的关系"), ("consensus", "共识"),
    ("disputes", "分歧与争议"), ("method_notes", "方法学注意点"), ("open_questions", "开放问题"),
]  # fmt: skip


def category_paper_ids(conn: sqlite3.Connection, cid: int) -> list[int]:
    ids = [cid]
    stack = [cid]
    while stack:  # include sub-categories
        for r in conn.execute("SELECT id FROM category WHERE parent_id = ?", (stack.pop(),)):
            ids.append(r["id"])
            stack.append(r["id"])
    q = f"SELECT DISTINCT paper_id FROM paper_category WHERE category_id IN ({','.join('?' * len(ids))}) ORDER BY paper_id"
    return [r["paper_id"] for r in conn.execute(q, ids)]


def _section_text(conn: sqlite3.Connection, pid: int, kind: str) -> str:
    r = conn.execute("SELECT content_md FROM paper_section WHERE paper_id=? AND kind=?", (pid, kind)).fetchone()
    return r["content_md"] if r else ""


def render(draft: dict[str, list[dict]]) -> str:
    out: list[str] = []
    for key, title in SECTIONS:
        items = draft.get(key) or []
        if not items:
            continue
        out.append(f"## {title}")
        for st in items:
            cites = " ".join(f"[P{s}](#/paper/{s})" for s in st["sources"])
            out.append(f"- {st['text']} {cites}")
        out.append("")
    return "\n".join(out).strip() + "\n"


def rule_draft(conn: sqlite3.Connection, pids: list[int]) -> dict[str, list[dict]]:
    """No-LLM digest: composed from stored one-liners, typed relations, principles and critiques."""
    pset = set(pids)
    d: dict[str, list[dict]] = {k: [] for k, _ in SECTIONS}
    for pid in pids:
        p = conn.execute("SELECT title, one_liner FROM paper WHERE id = ?", (pid,)).fetchone()
        text = f"《{p['title'][:60]}》：{p['one_liner']}" if p["one_liner"] else f"《{p['title'][:60]}》"
        d["core_question"].append({"text": text, "sources": [pid]})
    for r in conn.execute(
        "SELECT src_id, dst_id, type, evidence FROM paper_relation WHERE type != 'similar' ORDER BY score DESC"
    ):
        if r["src_id"] in pset and r["dst_id"] in pset:
            label = {"complements": "互补", "contradicts": "存在矛盾/挑战", "extends": "扩展", "alternative": "给出不同回答", "borrows_method": "方法借鉴",
                     "same_dataset": "共享数据集", "same_device": "共享设备", "same_team": "同一团队"}.get(r["type"], r["type"])  # fmt: skip
            item = {"text": f"P{r['src_id']} 与 P{r['dst_id']} {label}：{r['evidence'] or ''}".strip("：") , "sources": [r["src_id"], r["dst_id"]]}  # fmt: skip
            key = "disputes" if r["type"] in ("contradicts", "alternative") else "relations"
            d[key].append(item)
    seen: dict[str, list[int]] = {}
    for r in conn.execute(
        "SELECT pe.paper_id, e.name FROM paper_entity pe JOIN entity e ON e.id = pe.entity_id WHERE e.type = 'insight'"
    ):
        if r["paper_id"] in pset:
            seen.setdefault(r["name"], []).append(r["paper_id"])
    for name, ps in seen.items():
        d["method_notes"].append({"text": f"`{name}`", "sources": sorted(ps)[:4]})
    for pid in pids:
        crit = _section_text(conn, pid, "critique")
        first = next((ln.lstrip("-* ").strip() for ln in crit.splitlines() if ln.strip()), "")
        if first:
            d["open_questions"].append({"text": first[:180], "sources": [pid]})
    return {k: v[:6] for k, v in d.items()}


def llm_draft(conn: sqlite3.Connection, pids: list[int], client) -> dict[str, list[dict]]:
    lines = []
    for pid in pids:
        p = conn.execute("SELECT title, one_liner FROM paper WHERE id = ?", (pid,)).fetchone()
        res = _section_text(conn, pid, "results")[:350]
        crit = _section_text(conn, pid, "critique")[:250]
        lines.append(f"[P{pid}] {p['title']}\n  结论：{p['one_liner']}\n  结果：{res}\n  批判：{crit}")
    rel = []
    pset = set(pids)
    for r in conn.execute("SELECT src_id, dst_id, type, evidence FROM paper_relation WHERE type != 'similar'"):
        if r["src_id"] in pset and r["dst_id"] in pset:
            rel.append(f"P{r['src_id']}–P{r['dst_id']} {r['type']}：{r['evidence']}")
    prompt = (
        "论文笔记：\n"
        + "\n".join(lines)
        + ("\n\n已知论文关系：\n" + "\n".join(rel) if rel else "")
        + "\n\n请写综述，sources 填论文编号（数字）。"
    )
    r = client.chat(
        [{"role": "system", "content": DIGEST_SYSTEM}, {"role": "user", "content": prompt}],
        schema=DigestDraft, max_tokens=1500, retries=1,
    )  # fmt: skip
    return validate_draft(r.parsed.model_dump(), pset)  # type: ignore[union-attr]


def validate_draft(draft: dict, allowed: set[int]) -> dict[str, list[dict]]:
    """Keep only statements whose sources are real papers of this topic (traceability rule)."""
    out: dict[str, list[dict]] = {}
    for key, _ in SECTIONS:
        kept = []
        for st in draft.get(key, []):
            srcs = [s for s in st["sources"] if s in allowed]
            if srcs and st["text"].strip():
                kept.append({"text": st["text"].strip(), "sources": srcs})
        out[key] = kept
    return out


def propose(conn: sqlite3.Connection, cid: int, client=None) -> dict:
    pids = category_paper_ids(conn, cid)
    if not pids:
        return {"content_md": "", "source_paper_ids": [], "used_llm": False}
    draft, used = None, False
    if client is not None:
        try:
            draft = llm_draft(conn, pids, client)
            used = sum(len(v) for v in draft.values()) >= 3
        except Exception:  # noqa: BLE001
            draft = None
    if not used:
        draft = rule_draft(conn, pids)
    return {"content_md": render(draft), "source_paper_ids": pids, "used_llm": used}


def get_digest(conn: sqlite3.Connection, cid: int) -> dict | None:
    r = conn.execute("SELECT * FROM digest WHERE category_id = ?", (cid,)).fetchone()
    if r is None:
        return None
    current = category_paper_ids(conn, cid)
    return {"category_id": cid, "content_md": r["content_md"], "version": r["version"], "updated_at": r["updated_at"],
            "source_paper_ids": json.loads(r["source_paper_ids"]), "stale": sorted(current) != sorted(json.loads(r["source_paper_ids"]))}  # fmt: skip


def save_digest(conn: sqlite3.Connection, cid: int, content_md: str, pids: list[int]) -> dict:
    old = conn.execute("SELECT version FROM digest WHERE category_id = ?", (cid,)).fetchone()
    version = (old["version"] + 1) if old else 1
    conn.execute(
        "INSERT OR REPLACE INTO digest(category_id, content_md, version, updated_at, source_paper_ids) VALUES (?,?,?,?,?)",
        (cid, content_md, version, datetime.now(UTC).isoformat(timespec="seconds"), json.dumps(pids)),
    )
    conn.commit()
    return get_digest(conn, cid)  # type: ignore[return-value]


def diff(old: str, new: str) -> str:
    return "\n".join(difflib.unified_diff(old.splitlines(), new.splitlines(), "旧版", "新版", lineterm="", n=1))


def health_check(conn: sqlite3.Connection, cid: int) -> dict:
    """Flag cited papers that no longer belong to the topic and contradictions between members."""
    d = get_digest(conn, cid)
    if d is None:
        return {"issues": ["还没有综述"]}
    current = set(category_paper_ids(conn, cid))
    issues = []
    import re

    cited = {int(x) for x in re.findall(r"\[P(\d+)\]", d["content_md"])}
    for pid in sorted(cited - current):
        issues.append(f"引用了已不属于本主题的论文 P{pid}")
    for pid in sorted(current - set(d["source_paper_ids"])):
        issues.append(f"论文 P{pid} 是新加入的，综述尚未覆盖")
    n_contra = conn.execute(
        f"SELECT COUNT(*) FROM paper_relation WHERE type='contradicts' AND src_id IN ({','.join('?' * len(current) or '0')}) AND dst_id IN ({','.join('?' * len(current) or '0')})",
        [*current, *current],
    ).fetchone()[0] if current else 0  # fmt: skip
    if n_contra and "分歧" not in d["content_md"]:
        issues.append(f"主题内有 {n_contra} 对相互矛盾的论文，但综述没有「分歧与争议」部分")
    return {"issues": issues}


def ensure_taxonomy_digests(conn: sqlite3.Connection, client=None) -> int:
    n = 0
    for c in taxonomy.flat(conn):
        if get_digest(conn, c["id"]) is None:
            prop = propose(conn, c["id"], client)
            if prop["content_md"]:
                save_digest(conn, c["id"], prop["content_md"], prop["source_paper_ids"])
                n += 1
    return n
