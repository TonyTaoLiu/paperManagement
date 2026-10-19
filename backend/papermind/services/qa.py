"""Ask-your-library Q&A: hybrid retrieval -> grounded answer with [P<id>] citations."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator

import httpx

from papermind.embed.index import nearest
from papermind.services import search

NO_ANSWER = "库中没有相关内容。"
MIN_SEMANTIC = 0.30  # below this cosine (and with no keyword hit) the question is considered out of scope
SYSTEM = (
    "你是研究者个人论文库的问答助手。只能根据给出的论文笔记回答；笔记里没有依据时必须回答“库中没有相关内容”，不要猜测。"
    "每个论点后面用 [P编号] 标注来源论文，只能引用给出的编号。用中文回答，简洁。"
)


def retrieve(conn: sqlite3.Connection, question: str, k: int = 5) -> list[dict]:
    kw = search.keyword_search(conn, question, 20)
    # natural-language questions rarely match as a phrase: also try individual salient tokens
    if not kw:
        toks = [t for t in re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}|[一-鿿]{3,}", question)]
        seen: dict[int, float] = {}
        for t in toks:
            for pid, _s in search.keyword_search(conn, t, 10):
                seen[pid] = seen.get(pid, 0) + 1
        kw = sorted(seen.items(), key=lambda kv: -kv[1])
    kw_hit = bool(kw)
    sem = search.semantic_search(conn, question, 20)
    best_sem = sem[0][1] if sem else 0.0
    scores: dict[int, float] = {}
    for ranked in (kw, sem):
        for rank, (pid, _) in enumerate(ranked):
            scores[pid] = scores.get(pid, 0.0) + 1.0 / (60 + rank)
    top = sorted(scores, key=lambda p: -scores[p])[:k]
    # graph neighbours of the best hit give relevant context (same topic / typed relations)
    if top:
        for r in conn.execute("SELECT CASE WHEN src_id = ? THEN dst_id ELSE src_id END AS o FROM paper_relation WHERE (src_id = ? OR dst_id = ?) AND type != 'similar' LIMIT 2", (top[0], top[0], top[0])):  # fmt: skip
            if r["o"] not in top:
                top.append(r["o"])
    out = []
    for pid in top:
        p = conn.execute("SELECT id, title, one_liner FROM paper WHERE id = ?", (pid,)).fetchone()
        secs = {
            r["kind"]: r["content_md"]
            for r in conn.execute("SELECT kind, content_md FROM paper_section WHERE paper_id = ?", (pid,))
        }
        fups = [
            f"问：{r['question']}\n答：{r['answer_md'][:400]}"
            for r in conn.execute("SELECT question, answer_md FROM followup WHERE paper_id = ? LIMIT 3", (pid,))
        ]
        out.append(
            {
                "id": pid,
                "title": p["title"],
                "one_liner": p["one_liner"] or "",
                "sections": secs,
                "followups": fups,
                "sem": best_sem,
                "kw": kw_hit,
            }
        )
    return out


def in_scope(conn: sqlite3.Connection, question: str, ctx: list[dict]) -> bool:
    if not ctx:
        return False
    return bool(ctx[0]["kw"]) or ctx[0]["sem"] >= MIN_SEMANTIC


def build_context(ctx: list[dict]) -> str:
    blocks = []
    for c in ctx:
        s = c["sections"]
        body = "\n".join(
            filter(
                None,
                [
                    f"结论：{c['one_liner']}",
                    f"背景：{s.get('background', '')[:300]}",
                    f"结果：{s.get('results', '')[:600]}",
                    f"批判：{s.get('critique', '')[:400]}",
                    *c["followups"],
                ],
            )
        )
        blocks.append(f"[P{c['id']}] {c['title']}\n{body}")
    return "\n\n".join(blocks)


def clean_citations(answer: str, allowed: set[int]) -> tuple[str, list[int]]:
    """Drop citations that are not retrieved papers; return (answer, cited ids in order)."""
    cited: list[int] = []

    def fix(m: re.Match) -> str:
        pid = int(m.group(1))
        if pid not in allowed:
            return ""
        if pid not in cited:
            cited.append(pid)
        return m.group(0)

    return re.sub(r"\[P(\d+)\]", fix, answer), cited


def extractive_answer(ctx: list[dict]) -> str:
    lines = ["（未启用 LLM，以下是库中最相关的笔记片段）"]
    for c in ctx[:3]:
        lines.append(f"- {c['one_liner'] or c['title']} [P{c['id']}]")
    return "\n".join(lines)


def answer(conn: sqlite3.Connection, question: str, llm=None) -> dict:
    ctx = retrieve(conn, question)
    if not in_scope(conn, question, ctx):
        return {"answer": NO_ANSWER, "sources": [], "used_llm": False}
    allowed = {c["id"] for c in ctx}
    if llm is None:
        text = extractive_answer(ctx)
        used = False
    else:
        r = llm.chat(
            [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"论文笔记：\n{build_context(ctx)}\n\n问题：{question}"},
            ],
            max_tokens=700,
        )
        text, used = r.text.strip(), True
    text, cited = clean_citations(text, allowed)
    if used and not cited and NO_ANSWER[:-1] not in text:
        text += "\n（提示：该回答没有引用来源，请对照下方相关论文核实。）"
    shown = cited or ([] if NO_ANSWER[:-1] in text else [c["id"] for c in ctx[:3]])
    return {
        "answer": text,
        "sources": [{"id": c["id"], "title": c["title"]} for c in ctx if c["id"] in shown],
        "used_llm": used,
    }


def stream_answer(conn: sqlite3.Connection, question: str, llm=None) -> Iterator[str]:
    """SSE lines: `data: {"delta": ...}` ... then `data: {"done": true, sources: [...]}`."""
    ctx = retrieve(conn, question)
    allowed = {c["id"] for c in ctx}
    if not in_scope(conn, question, ctx) or llm is None:
        res = answer(conn, question, None)
        yield f"data: {json.dumps({'delta': res['answer']}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'done': True, 'sources': res['sources'], 'used_llm': False}, ensure_ascii=False)}\n\n"
        return
    body = {"model": llm.model, "stream": True, "max_tokens": 700, "temperature": 0.1,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"论文笔记：\n{build_context(ctx)}\n\n问题：{question}"}]}  # fmt: skip
    full = ""
    with httpx.stream("POST", f"{llm.base_url}/chat/completions", json=body, headers=llm.headers, timeout=900) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line.startswith("data: ") or line.endswith("[DONE]"):
                continue
            delta = json.loads(line[6:])["choices"][0]["delta"].get("content") or ""
            if delta:
                full += delta
                yield f"data: {json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
    cleaned, cited = clean_citations(full, allowed)
    shown = cited or [c["id"] for c in ctx[:3]]
    srcs = [{"id": c["id"], "title": c["title"]} for c in ctx if c["id"] in shown]
    yield f"data: {json.dumps({'done': True, 'sources': srcs, 'answer': cleaned, 'used_llm': True}, ensure_ascii=False)}\n\n"


def related_ids(conn: sqlite3.Connection, model: str, vec, k: int = 5) -> list[int]:  # kept for API symmetry
    return [i for i, _ in nearest(conn, model, vec, k)]
