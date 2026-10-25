"""Recommendation pipeline: fetch -> dedupe -> embed -> score -> (optional) LLM refine -> store."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from datetime import UTC, date, datetime

import httpx
import numpy as np
from pydantic import BaseModel, Field

from papermind.config import load_settings
from papermind.embed.index import from_blob, to_blob
from papermind.pipeline.ingest import title_norm
from papermind.pipeline.lexicon import EN_QUERY
from papermind.recommend import ranker, sources

NEW_DAYS = 21


class Refine(BaseModel):
    score: int = Field(ge=1, le=5, description="与研究者兴趣的相关度 1-5")
    reason: str = Field(max_length=100, description="一句话中文推荐理由")


def derive_queries(conn: sqlite3.Connection, limit: int = 5) -> list[str]:
    qs = list(load_settings().get("rec_keywords") or [])
    rows = conn.execute(
        "SELECT e.name, e.type, COUNT(*) n FROM entity e JOIN paper_entity pe ON pe.entity_id = e.id "
        "WHERE e.type IN ('method','device','modality','disease') GROUP BY e.id ORDER BY n DESC"
    ).fetchall()
    for r in rows:
        q = EN_QUERY.get(r["name"]) or (
            r["name"] if re.fullmatch(r"[A-Za-z0-9 +\-–/']+", r["name"]) and len(r["name"]) > 3 else ""
        )
        if q and q not in qs and r["type"] != "species":
            qs.append(q)
        if len(qs) >= limit:
            break
    return qs[:limit] or ["Parkinson's disease deep brain stimulation"]


def library_state(conn: sqlite3.Connection, model: str) -> dict:
    """Library vectors (most recent first), per-paper references and followed author names."""
    order = conn.execute("SELECT id FROM paper ORDER BY COALESCE(read_at, ''), id").fetchall()
    ids = [r["id"] for r in reversed(order)]
    vec = {
        r["owner_id"]: from_blob(r["vector"])
        for r in conn.execute("SELECT owner_id, vector FROM embedding WHERE owner_type='paper' AND model=?", (model,))
    }
    ids = [i for i in ids if i in vec]
    refs = {
        r["id"]: set(json.loads(r["refs"] or "[]"))
        for r in conn.execute("SELECT id, refs FROM paper")
        if r["id"] in vec
    }
    refs_oa = {
        r["openalex_id"]: r["id"]
        for r in conn.execute("SELECT id, openalex_id FROM paper WHERE openalex_id IS NOT NULL")
    }
    followed = {ranker.norm_name(r["name"]) for r in conn.execute("SELECT name FROM author WHERE followed = 1")}
    dois = [r["doi"] for r in conn.execute("SELECT doi FROM paper WHERE doi IS NOT NULL AND doi != ''")]
    titles = {
        r["title_norm"][:60] for r in conn.execute("SELECT title_norm FROM paper")
    }  # prefix key tolerates truncated titles
    return {"ids": ids, "vecs": np.stack([vec[i] for i in ids]) if ids else np.zeros((0, 1)), "refs": refs, "followed": followed, "dois": dois, "titles": titles, "oa": refs_oa}  # fmt: skip


def _known_title(tn: str, lib_titles: set[str]) -> bool:
    """Library titles are stored as 60-char prefixes; a candidate may carry a truncated or a longer title."""
    if tn[:60] in lib_titles:
        return True
    return len(tn) >= 30 and any(t.startswith(tn) for t in lib_titles)


def store_candidates(
    conn: sqlite3.Connection, cands: list[dict], lib_titles: set[str], lib_dois: set[str]
) -> list[int]:
    ids: list[int] = []
    seen: set[str] = set()
    for c in cands:
        tn = title_norm(c["title"])
        if not tn or _known_title(tn, lib_titles) or (c["doi"] and c["doi"] in lib_dois) or tn in seen:
            continue
        seen.add(tn)
        existing = conn.execute(
            "SELECT id FROM candidate WHERE ext_id = ? OR (doi != '' AND doi = ?)", (c["ext_id"], c["doi"])
        ).fetchone()
        if existing is None:
            # preprint and journal versions of one paper arrive with different ids: dedupe by title as well
            for r in conn.execute("SELECT id, title FROM candidate"):
                if title_norm(r["title"]) == tn:
                    existing = r
                    break
        payload = json.dumps(
            {"refs": c["refs"], "author_ids": c["author_ids"], "published": c["published"]}, ensure_ascii=False
        )
        if existing is None:
            cur = conn.execute(
                "INSERT INTO candidate(ext_id, title, abstract, authors, year, url, doi, venue, source, payload) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (c["ext_id"], c["title"], c["abstract"], json.dumps(c["authors"], ensure_ascii=False), c["year"], c["url"], c["doi"], c["venue"], c["source"], payload),
            )  # fmt: skip
            ids.append(cur.lastrowid)
        else:
            ids.append(existing["id"])
    conn.commit()
    return ids


def embed_candidates(conn: sqlite3.Connection, client, spec, ids: list[int]) -> None:
    todo = [
        i
        for i in ids
        if conn.execute(
            "SELECT 1 FROM embedding WHERE owner_type='candidate' AND owner_id=? AND model=?", (i, spec.id)
        ).fetchone()
        is None
    ]
    for i in range(0, len(todo), 8):
        batch = todo[i : i + 8]
        rows = [conn.execute("SELECT title, abstract FROM candidate WHERE id = ?", (b,)).fetchone() for b in batch]
        vecs = client.embed([spec.doc_prefix + f"{r['title']}\n{(r['abstract'] or '')[:1000]}" for r in rows])
        for cid, v in zip(batch, vecs, strict=True):
            conn.execute("INSERT OR REPLACE INTO embedding(owner_type, owner_id, model, text_hash, dim, vector) VALUES ('candidate',?,?,'',?,?)", (cid, spec.id, len(v), to_blob(v)))  # fmt: skip
    conn.commit()


def _reason(conn: sqlite3.Connection, s: ranker.Signals, extra: str = "") -> str:
    parts = []
    if s.near:
        names = "、".join(
            f"《{conn.execute('SELECT title FROM paper WHERE id=?', (pid,)).fetchone()[0][:36]}》"
            for pid, sim in s.near
            if sim > 0
        )
        parts.append(f"与你读过的{names}相似（余弦 {s.near[0][1]:.2f}）")
    if s.cited_by_lib:
        parts.append(f"被你库中 {s.cited_by_lib} 篇论文引用")
    elif s.coupled:
        parts.append(f"与你的库共享 {s.coupled} 篇参考文献")
    if s.authors:
        parts.append(f"你关注的作者：{'、'.join(s.authors[:2])}")
    if s.cls > 0.7:
        parts.append("与你点赞过的论文接近")
    if extra:
        parts.append(extra)
    return "；".join(parts) or "语义上与你的论文库相关"


def rescore(conn: sqlite3.Connection, model: str, llm=None, top_refine: int = 20) -> int:
    """Recompute scores/reasons/groups for all `new` candidates from stored vectors."""
    lib = library_state(conn, model)
    rows = conn.execute("SELECT * FROM candidate WHERE status = 'new'").fetchall()
    vecs = {
        r["owner_id"]: from_blob(r["vector"])
        for r in conn.execute(
            "SELECT owner_id, vector FROM embedding WHERE owner_type='candidate' AND model=?", (model,)
        )
    }
    rows = [r for r in rows if r["id"] in vecs]
    if not rows:
        return 0
    V = np.stack([vecs[r["id"]] for r in rows])
    fb = {r["candidate_id"]: r["value"] for r in conn.execute("SELECT candidate_id, value FROM feedback")}
    liked = (
        np.stack([vecs[i] for i, v in fb.items() if v > 0 and i in vecs])
        if any(v > 0 and i in vecs for i, v in fb.items())
        else np.zeros((0, V.shape[1]))
    )
    disliked = (
        np.stack([vecs[i] for i, v in fb.items() if v < 0 and i in vecs])
        if any(v < 0 and i in vecs for i, v in fb.items())
        else np.zeros((0, V.shape[1]))
    )
    for st in ("liked", "disliked"):  # candidates whose status already encodes feedback
        for r in conn.execute("SELECT id FROM candidate WHERE status = ?", (st,)):
            if r["id"] in vecs and r["id"] not in fb:
                arr = vecs[r["id"]][None]
                liked, disliked = (
                    (np.vstack([liked, arr]), disliked) if st == "liked" else (liked, np.vstack([disliked, arr]))
                )
    payloads = [json.loads(r["payload"] or "{}") for r in rows]
    sigs = ranker.compute_signals(
        V, lib["vecs"], lib["ids"], liked, disliked, [p.get("refs", []) for p in payloads], [r["ext_id"] for r in rows],
        lib["refs"], [json.loads(r["authors"] or "[]") for r in rows], lib["followed"],
    )  # fmt: skip
    order = sorted(range(len(rows)), key=lambda i: -ranker.final_score(sigs[i]))
    refined: dict[int, tuple[float, str]] = {}
    if llm is not None:
        for i in order[:top_refine]:
            r = rows[i]
            near = "；".join(
                conn.execute("SELECT title FROM paper WHERE id = ?", (pid,)).fetchone()[0] for pid, _ in sigs[i].near
            )
            try:
                out = llm.chat(
                    [{"role": "system", "content": "你是神经科学文献推荐助手，判断候选论文与研究者已读论文的相关度，并用一句中文说明理由。"},
                     {"role": "user", "content": f"研究者读过：{near}\n候选标题：{r['title']}\n候选摘要：{(r['abstract'] or '')[:700]}"}],
                    schema=Refine, max_tokens=160, retries=1,
                )  # fmt: skip
                refined[i] = (out.parsed.score / 5.0, out.parsed.reason)  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                continue
    today = date.today()
    for i, r in enumerate(rows):
        s = sigs[i]
        score = ranker.final_score(s)
        extra = ""
        if i in refined:
            score = 0.7 * score + 0.3 * refined[i][0]
            extra = f"LLM：{refined[i][1]}"
        pub = (payloads[i].get("published") or "")[:10]
        recent = bool(pub) and len(pub) == 10 and (today - date.fromisoformat(pub)).days <= NEW_DAYS
        group = "team" if s.authors else "classic" if s.cited_by_lib >= 2 else "new" if recent else "topic"
        conn.execute(
            "UPDATE candidate SET score = ?, reason = ?, group_name = ? WHERE id = ?",
            (score, _reason(conn, s, extra), group, r["id"]),
        )
    conn.commit()
    return len(rows)


def missing_classics(conn: sqlite3.Connection, http: httpx.Client, min_cited: int = 2, limit: int = 15) -> list[dict]:
    """Works referenced by >= min_cited library papers but not in the library (OpenAlex ids)."""
    lib = library_state(conn, "")
    counts: dict[str, int] = {}
    for refs in lib["refs"].values():
        for w in refs:
            counts[w] = counts.get(w, 0) + 1
    have = set(lib["oa"])
    want = [w for w, n in sorted(counts.items(), key=lambda kv: -kv[1]) if n >= min_cited and w not in have][:limit]
    return sources.openalex_by_ids(http, want) if want else []


def refresh(
    conn: sqlite3.Connection,
    embed_client,
    spec,
    llm=None,
    http: httpx.Client | None = None,
    progress: Callable[[float, str], None] | None = None,
    days: int = 21,
) -> dict:
    own = http is None
    http = http or httpx.Client()
    try:
        lib = library_state(conn, spec.id)
        authors = [
            r["openalex_id"]
            for r in conn.execute("SELECT openalex_id FROM author WHERE followed = 1 AND openalex_id IS NOT NULL")
        ]
        queries = derive_queries(conn)
        say = (lambda m: progress and progress(0.3, m)) if progress else None
        cands = sources.fetch_all(http, queries, sources.default_window(days), authors, lib["dois"], say)
        try:
            cands += missing_classics(conn, http)
        except Exception:  # noqa: BLE001
            pass
    finally:
        if own:
            http.close()
    if progress:
        progress(0.55, f"去重并向量化 {len(cands)} 篇候选 ...")
    ids = store_candidates(conn, cands, lib["titles"], set(lib["dois"]))
    embed_candidates(conn, embed_client, spec, ids)
    if progress:
        progress(0.85, "打分排序 ...")
    n = rescore(conn, spec.id, llm)
    return {
        "fetched": len(cands),
        "stored": len(ids),
        "ranked": n,
        "queries": queries,
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def list_candidates(conn: sqlite3.Connection, group: str = "", status: str = "new", limit: int = 50) -> list[dict]:
    q = "SELECT * FROM candidate WHERE status = ?"
    params: list = [status]
    if group:
        q += " AND group_name = ?"
        params.append(group)
    rows = conn.execute(q + " ORDER BY score DESC LIMIT ?", (*params, limit)).fetchall()
    out = []
    for r in rows:
        d = {
            k: r[k]
            for k in (
                "id",
                "title",
                "abstract",
                "year",
                "url",
                "doi",
                "venue",
                "source",
                "score",
                "reason",
                "group_name",
                "status",
            )
        }
        d["authors"] = json.loads(r["authors"] or "[]")
        out.append(d)
    return out


def give_feedback(conn: sqlite3.Connection, cid: int, value: int, model: str | None = None) -> None:
    status = {1: "liked", -1: "disliked", 0: "read"}[value]
    conn.execute("UPDATE candidate SET status = ? WHERE id = ?", (status, cid))
    conn.execute("INSERT INTO feedback(candidate_id, value) VALUES (?,?)", (cid, value))
    conn.commit()
    if model:
        rescore(conn, model)
