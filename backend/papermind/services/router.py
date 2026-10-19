"""Automatic category routing (docs 6.3): embedding centroid + kNN vote + LLM confidence."""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field

import numpy as np

from papermind.embed.index import from_blob, to_blob
from papermind.llm.schemas import CLASSIFY_SYSTEM, category_schema, classify_user_prompt
from papermind.services import taxonomy

W_SIM, W_KNN, W_LLM = 0.3, 0.2, 0.5  # tuned on the 19-paper set (docs/模型评测.md): LLM-heavy fusion
AUTO_T, INBOX_T = 0.75, 0.5
SOFTMAX_TAU = 0.02  # calibrated on the 19-paper set: sharper values keep auto-assignments precise
KNN_K = 5
FEW_SHOT = 3


@dataclass
class Suggestion:
    category_id: int
    name: str
    score: float
    parts: dict = field(default_factory=dict)


@dataclass
class RouteResult:
    decision: str  # auto | inbox | new
    suggestions: list[Suggestion]
    reason: str = ""


def _softmax(x: np.ndarray, tau: float) -> np.ndarray:
    z = (x - x.max()) / tau
    e = np.exp(z)
    return e / e.sum()


def category_vectors(conn: sqlite3.Connection, client, spec) -> dict[int, np.ndarray]:
    """Description vectors (embedded lazily and cached)."""
    out: dict[int, np.ndarray] = {}
    for c in taxonomy.flat(conn):
        row = conn.execute(
            "SELECT vector FROM embedding WHERE owner_type='category' AND owner_id=? AND model=?", (c["id"], spec.id)
        ).fetchone()
        if row is None:
            vec = client.embed([spec.doc_prefix + f"{c['name']}：{c['description']}"])[0]
            blob = to_blob(vec)
            conn.execute(
                "INSERT OR REPLACE INTO embedding(owner_type, owner_id, model, text_hash, dim, vector) VALUES ('category',?,?,?,?,?)",
                (c["id"], spec.id, "desc", len(vec), blob),
            )
            conn.commit()
        else:
            blob = row["vector"]
        out[c["id"]] = from_blob(blob)
    return out


def paper_vectors(conn: sqlite3.Connection, model: str) -> dict[int, np.ndarray]:
    return {
        r["owner_id"]: from_blob(r["vector"])
        for r in conn.execute("SELECT owner_id, vector FROM embedding WHERE owner_type='paper' AND model=?", (model,))
    }


def memberships(conn: sqlite3.Connection, exclude: int | None = None) -> dict[int, set[int]]:
    """paper -> categories it belongs to (direct assignments plus their ancestors)."""
    out: dict[int, set[int]] = {}
    cache: dict[int, list[int]] = {}
    for r in conn.execute("SELECT paper_id, category_id FROM paper_category"):
        if r["paper_id"] == exclude:
            continue
        chain = cache.setdefault(r["category_id"], taxonomy.ancestors(conn, r["category_id"]))
        out.setdefault(r["paper_id"], set()).update([r["category_id"], *chain])
    return out


def centroids(
    desc: dict[int, np.ndarray], pvecs: dict[int, np.ndarray], member: dict[int, set[int]]
) -> dict[int, np.ndarray]:
    out = {}
    for cid, d in desc.items():
        vs = [pvecs[p] for p, cats in member.items() if cid in cats and p in pvecs]
        if not vs:
            out[cid] = d
            continue
        alpha = 1.0 / (1.0 + len(vs) / 3.0)  # the description matters less as confirmed papers accumulate
        c = alpha * d + (1 - alpha) * np.mean(vs, axis=0)
        out[cid] = c / (np.linalg.norm(c) or 1.0)
    return out


def few_shot_examples(
    conn: sqlite3.Connection, cid: int, cent: np.ndarray, pvecs: dict[int, np.ndarray], exclude: int
) -> list[str]:
    cands = []
    for r in conn.execute("SELECT p.id, p.title FROM paper p JOIN paper_category pc ON pc.paper_id = p.id WHERE pc.category_id = ? AND p.id != ?", (cid, exclude)):  # fmt: skip
        if r["id"] in pvecs:
            cands.append((float(pvecs[r["id"]] @ cent), r["title"]))
    return [t for _, t in sorted(cands, reverse=True)[:FEW_SHOT]]


def llm_scores(conn, client, paper, cats, examples: dict[int, list[str]]) -> dict[int, float]:
    ids = [str(c["id"]) for c in cats]
    lines = []
    for c in cats:
        ex = examples.get(c["id"])
        extra = f"（已有论文如：{'；'.join(ex)}）" if ex else ""
        lines.append((str(c["id"]), c["name"], c["description"] + extra))
    secs = conn.execute("SELECT kind, content_md FROM paper_section WHERE paper_id=? AND kind IN ('background','results')", (paper["id"],)).fetchall()  # fmt: skip
    text = (paper["one_liner"] or "") + "\n" + "\n".join(s["content_md"] for s in secs)
    r = client.chat(
        [{"role": "system", "content": CLASSIFY_SYSTEM}, {"role": "user", "content": classify_user_prompt(lines, paper["title"], text[:3000])}],
        schema=category_schema(ids), max_tokens=80, retries=1, temperature=0.0,
    )  # fmt: skip
    rank = [int(x) for x in r.parsed.ranking[:3]]
    conf = min(max(r.parsed.confidence, 0.0), 1.0)
    shares = [conf, (1 - conf) * 0.65, (1 - conf) * 0.35]
    return {cid: shares[i] for i, cid in enumerate(rank)}


def route_paper(conn, paper_id: int, embed_client, spec, llm_client=None) -> RouteResult:
    paper = conn.execute("SELECT * FROM paper WHERE id = ?", (paper_id,)).fetchone()
    cats = taxonomy.flat(conn)
    if not cats:
        return RouteResult("new", [], "尚未建立分类体系")
    pvecs = paper_vectors(conn, spec.id)
    if paper_id not in pvecs:
        raise RuntimeError("paper has no embedding yet")
    desc = category_vectors(conn, embed_client, spec)
    member = memberships(conn, exclude=paper_id)
    cent = centroids(desc, pvecs, member)
    ids = [c["id"] for c in cats]
    v = pvecs[paper_id]
    sims = np.array([float(v @ cent[i]) for i in ids])
    p_sim = _softmax(sims, SOFTMAX_TAU)

    knn = {i: 0.0 for i in ids}
    others = [(float(v @ pvecs[p]), p) for p in member if p in pvecs]
    others.sort(reverse=True)
    top = others[:KNN_K]
    if top:
        for _, p in top:
            for cid in member[p]:
                if cid in knn:
                    knn[cid] += 1.0 / len(top)

    llm = {}
    if llm_client is not None:
        order = np.argsort(-p_sim)[:12]
        shortlist = [cats[i] for i in order]
        examples = {c["id"]: few_shot_examples(conn, c["id"], cent[c["id"]], pvecs, paper_id) for c in shortlist}
        try:
            llm = llm_scores(conn, llm_client, paper, shortlist, examples)
        except Exception:  # noqa: BLE001 - routing degrades gracefully without the LLM
            llm = {}

    w = {"sim": W_SIM, "knn": W_KNN if top else 0.0, "llm": W_LLM if llm else 0.0}
    total = sum(w.values())
    rejected = {
        r["category_id"]
        for r in conn.execute("SELECT category_id FROM category_rejection WHERE paper_id=?", (paper_id,))
    }
    sugg: list[Suggestion] = []
    for k, cid in enumerate(ids):
        if cid in rejected:
            continue
        parts = {"sim": float(p_sim[k]), "knn": knn[cid], "llm": llm.get(cid, 0.0)}
        score = sum(w[n] * parts[n] for n in w) / total
        name = next(c["name"] for c in cats if c["id"] == cid)
        sugg.append(Suggestion(cid, name, score, parts))
    sugg.sort(key=lambda s: -s.score)
    sugg = _apply_hierarchy(conn, sugg)
    best = sugg[0].score if sugg else 0.0
    if best >= AUTO_T:
        return RouteResult("auto", sugg[:3])
    top2 = sum(s.score for s in sugg[:2])
    if best >= INBOX_T or top2 >= 0.7:  # a clean two-way split is still a confirmation, not a new category
        return RouteResult("inbox", sugg[:3], "置信度中等，请确认")
    return RouteResult("new", sugg[:3], "没有足够匹配的类别，可新建")


def _apply_hierarchy(conn, sugg: list[Suggestion]) -> list[Suggestion]:
    """If a parent already scores high, do not additionally propose its children (PaperRouter rule)."""
    drop: set[int] = set()
    by_id = {s.category_id: s for s in sugg}
    for s in sugg:
        if s.score >= AUTO_T:
            for a in taxonomy.ancestors(conn, s.category_id):
                if a in by_id and by_id[a].score < s.score:
                    continue
            for c in conn.execute("SELECT id FROM category WHERE parent_id = ?", (s.category_id,)):
                if c["id"] in by_id and by_id[c["id"]].score < AUTO_T:
                    drop.add(c["id"])
    return [s for s in sugg if s.category_id not in drop]


def apply_result(conn, paper_id: int, res: RouteResult) -> None:
    """Persist routing: auto-assign, or park in the inbox with the top suggestions."""
    if res.decision == "auto":
        for s in res.suggestions[:1]:
            conn.execute(
                "INSERT OR REPLACE INTO paper_category(paper_id, category_id, confidence, origin, rationale, is_primary) "
                "VALUES (?,?,?, 'auto', ?, 1)",
                (paper_id, s.category_id, s.score, json.dumps(s.parts)),
            )
        conn.execute("DELETE FROM inbox WHERE paper_id = ?", (paper_id,))
    else:
        conn.execute(
            "INSERT OR REPLACE INTO inbox(paper_id, suggestions, reason) VALUES (?,?,?)",
            (paper_id, json.dumps([s.__dict__ for s in res.suggestions]), res.reason),
        )
    conn.commit()


def softmax_entropy(x: np.ndarray) -> float:  # kept for tests/diagnostics
    p = _softmax(x, SOFTMAX_TAU)
    return float(-(p * np.log(p + 1e-12)).sum() / math.log(len(p)))
