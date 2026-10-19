"""Knowledge-graph views (global / paper-centred / concept) and the semantic map."""

from __future__ import annotations

import sqlite3

import networkx as nx
import numpy as np

from papermind.embed.index import load_matrix
from papermind.services import taxonomy

ENTITY_TYPES = ["method", "dataset", "modality", "device", "disease", "species", "insight", "author"]
TYPE_LABEL = {"method": "方法", "dataset": "数据集", "modality": "数据模态", "device": "设备", "disease": "疾病",
              "species": "物种", "insight": "洞见/原则", "author": "作者/团队", "paper": "论文", "topic": "主题"}  # fmt: skip
REL_LABEL = {"similar": "语义相似", "complements": "互补", "contradicts": "矛盾/挑战", "extends": "扩展",
             "alternative": "同一问题的不同回答", "borrows_method": "方法借鉴", "same_dataset": "同数据集",
             "same_device": "同设备", "same_team": "同团队", "cites": "引用"}  # fmt: skip


def communities(conn: sqlite3.Connection) -> dict[int, int]:
    """Louvain communities over papers (relations + shared entities)."""
    G = nx.Graph()
    G.add_nodes_from(r["id"] for r in conn.execute("SELECT id FROM paper"))
    for r in conn.execute("SELECT src_id, dst_id, type, score FROM paper_relation"):
        w = 1.0 if r["type"] != "similar" else float(r["score"] or 0.5)
        if G.has_edge(r["src_id"], r["dst_id"]):
            G[r["src_id"]][r["dst_id"]]["weight"] += w
        else:
            G.add_edge(r["src_id"], r["dst_id"], weight=w)
    for e in conn.execute(
        "SELECT entity_id, GROUP_CONCAT(paper_id) AS ps FROM paper_entity GROUP BY entity_id HAVING COUNT(*) BETWEEN 2 AND 6"
    ):
        ps = [int(x) for x in e["ps"].split(",")]
        for i, a in enumerate(ps):
            for b in ps[i + 1 :]:
                if G.has_edge(a, b):
                    G[a][b]["weight"] += 0.25
                else:
                    G.add_edge(a, b, weight=0.25)
    if G.number_of_edges() == 0:
        return {n: i for i, n in enumerate(G.nodes)}
    comms = nx.algorithms.community.louvain_communities(G, weight="weight", seed=7)
    comms = sorted(comms, key=lambda c: (-len(c), min(c)))
    return {n: i for i, c in enumerate(comms) for n in c}


def _paper_nodes(conn: sqlite3.Connection, ids: set[int] | None, comm: dict[int, int]) -> list[dict]:
    rows = conn.execute("SELECT id, title, paper_type, one_liner FROM paper").fetchall()
    return [
        {"id": f"p{r['id']}", "label": r["title"][:48], "type": "paper", "title": r["title"], "paper_id": r["id"],
         "community": comm.get(r["id"], 0), "one_liner": r["one_liner"], "paper_type": r["paper_type"]}
        for r in rows if ids is None or r["id"] in ids
    ]  # fmt: skip


def build_graph(
    conn: sqlite3.Connection,
    view: str = "global",
    focus: int | None = None,
    types: list[str] | None = None,
    min_papers: int = 2,
) -> dict:
    comm = communities(conn)
    types = types or ["paper", "topic", *ENTITY_TYPES]
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def add_edge(s: str, t: str, etype: str, label: str = "", weight: float = 1.0, evidence: str = "") -> None:
        edges.append(
            {
                "id": f"e{len(edges)}",
                "source": s,
                "target": t,
                "type": etype,
                "label": label or REL_LABEL.get(etype, etype),
                "weight": weight,
                "evidence": evidence,
            }
        )

    if view == "paper" and focus is not None:
        keep = {focus}
        for r in conn.execute(
            "SELECT src_id, dst_id FROM paper_relation WHERE src_id = ? OR dst_id = ?", (focus, focus)
        ):
            keep.update((r["src_id"], r["dst_id"]))
        direct = set(keep)
        # second hop: papers related to a direct neighbour by a typed (non-similarity) relation
        for r in conn.execute("SELECT src_id, dst_id FROM paper_relation WHERE type != 'similar'"):
            if r["src_id"] in direct or r["dst_id"] in direct:
                keep.update((r["src_id"], r["dst_id"]))
        paper_ids: set[int] | None = keep
    else:
        paper_ids = None
    if "paper" in types:
        for n in _paper_nodes(conn, paper_ids, comm):
            nodes[n["id"]] = n
    for r in conn.execute("SELECT src_id, dst_id, type, score, evidence FROM paper_relation"):
        s, d = f"p{r['src_id']}", f"p{r['dst_id']}"
        if s in nodes and d in nodes and view != "concept":
            if (
                view == "paper"
                and focus is not None
                and focus not in (r["src_id"], r["dst_id"])
                and r["type"] == "similar"
            ):
                continue
            add_edge(s, d, r["type"], weight=float(r["score"] or 1.0), evidence=r["evidence"] or "")
    present = {n["paper_id"] for n in nodes.values() if n["type"] == "paper"}

    if "topic" in types and view != "concept":
        cats = {c["id"]: c for c in taxonomy.flat(conn)}
        for r in conn.execute("SELECT paper_id, category_id FROM paper_category"):
            if r["paper_id"] in present and r["category_id"] in cats:
                cid = f"c{r['category_id']}"
                nodes.setdefault(
                    cid,
                    {
                        "id": cid,
                        "label": cats[r["category_id"]]["name"],
                        "type": "topic",
                        "category_id": r["category_id"],
                    },
                )
                add_edge(f"p{r['paper_id']}", cid, "belongs", "属于")
    ent_types = [t for t in ENTITY_TYPES if t in types]
    if view == "concept":
        ent_types = [t for t in ent_types if t in ("method", "insight", "dataset", "device")] or ent_types
    if ent_types:
        q = ("SELECT e.id, e.type, e.name, GROUP_CONCAT(pe.paper_id) AS ps FROM entity e JOIN paper_entity pe ON pe.entity_id = e.id "
             f"WHERE e.type IN ({','.join('?' * len(ent_types))}) GROUP BY e.id")  # fmt: skip
        for e in conn.execute(q, ent_types):
            ps = [int(x) for x in e["ps"].split(",") if int(x) in present]
            threshold = 1 if (view == "paper" or e["type"] == "insight") else min_papers
            if len(ps) < threshold:
                continue
            eid = f"e{e['id']}"
            nodes[eid] = {"id": eid, "label": e["name"], "type": e["type"], "entity_id": e["id"], "n_papers": len(ps)}
            for p in ps:
                add_edge(f"p{p}", eid, "has_" + e["type"], TYPE_LABEL[e["type"]])
    if view == "paper" and focus is not None:
        # entities should only remain when they link the focus paper to something
        linked = {e["target"] for e in edges if e["source"] == f"p{focus}"} | {
            e["source"] for e in edges if e["target"] == f"p{focus}"
        }
        edges = [e for e in edges if not (e["type"].startswith("has_") and e["target"] not in linked)]
        used = {e["source"] for e in edges} | {e["target"] for e in edges}
        nodes = {k: v for k, v in nodes.items() if k in used or k == f"p{focus}"}
    return {"nodes": list(nodes.values()), "edges": edges, "communities": len(set(comm.values()))}


def semantic_map(conn: sqlite3.Connection, model: str) -> list[dict]:
    ids, mat = load_matrix(conn, model)
    if not ids:
        return []
    xy = tsne(mat)
    comm = communities(conn)
    cat = {
        r["paper_id"]: r["name"]
        for r in conn.execute(
            "SELECT pc.paper_id, c.name FROM paper_category pc JOIN category c ON c.id = pc.category_id ORDER BY pc.is_primary"
        )
    }
    titles = {r["id"]: r["title"] for r in conn.execute("SELECT id, title FROM paper")}
    return [{"id": pid, "title": titles.get(pid, ""), "x": float(xy[i, 0]), "y": float(xy[i, 1]), "community": comm.get(pid, 0), "category": cat.get(pid, "未分类")} for i, pid in enumerate(ids)]  # fmt: skip


def tsne(X: np.ndarray, perplexity: float | None = None, iters: int = 500, seed: int = 0) -> np.ndarray:
    """Small exact t-SNE (numpy only; fine for the <= few thousand papers this app targets)."""
    n = X.shape[0]
    if n == 1:
        return np.zeros((1, 2))
    if n < 4:  # not enough points for t-SNE: fall back to PCA
        return _pca(X)
    perplexity = perplexity or max(2.0, min(30.0, (n - 1) / 3.0))
    sq = np.maximum(2 - 2 * (X @ X.T), 0)  # embeddings are unit vectors
    P = np.zeros((n, n))
    target = np.log(perplexity)
    for i in range(n):
        lo, hi, beta = 1e-10, 1e10, 1.0
        d = np.delete(sq[i], i)
        for _ in range(50):
            w = np.exp(-(d - d.min()) * beta)
            h = np.log(w.sum()) + beta * (d - d.min()) @ w / w.sum()
            if abs(h - target) < 1e-4:
                break
            if h > target:
                lo = beta
                beta = beta * 2 if hi >= 1e10 else (beta + hi) / 2
            else:
                hi = beta
                beta = (beta + lo) / 2
        w = w / w.sum()
        P[i, np.arange(n) != i] = w
    P = (P + P.T) / (2 * n)
    P = np.maximum(P, 1e-12)
    Y = _pca(X) * 1e-2 + np.random.default_rng(seed).normal(0, 1e-4, (n, 2))
    gains, vel = np.ones_like(Y), np.zeros_like(Y)
    for it in range(iters):
        num = 1.0 / (1.0 + ((Y[:, None, :] - Y[None, :, :]) ** 2).sum(-1))
        np.fill_diagonal(num, 0)
        Q = np.maximum(num / num.sum(), 1e-12)
        PQ = (4.0 if it < 100 else 1.0) * P - Q
        grad = 4 * ((PQ * num)[:, :, None] * (Y[:, None, :] - Y[None, :, :])).sum(1)
        gains = np.where(np.sign(grad) != np.sign(vel), gains + 0.2, gains * 0.8).clip(0.01)
        vel = (0.5 if it < 250 else 0.8) * vel - max(50.0, n / 12.0) * gains * grad
        Y = Y + vel
        Y -= Y.mean(0)
    return Y


def _pca(X: np.ndarray) -> np.ndarray:
    Xc = X - X.mean(0)
    u, s, _ = np.linalg.svd(Xc, full_matrices=False)
    out = u[:, :2] * s[:2]
    if out.shape[1] < 2:
        out = np.pad(out, ((0, 0), (0, 2 - out.shape[1])))
    return out
