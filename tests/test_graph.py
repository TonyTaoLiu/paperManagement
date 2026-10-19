from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from papermind.db.core import connect, init_db
from papermind.main import create_app
from papermind.pipeline.ingest import import_text
from papermind.services import digest, graph, relations, taxonomy

FIXTURE = (Path(__file__).parent / "fixtures" / "论文总结记录.md").read_text(encoding="utf-8")


@pytest.fixture
def conn():
    init_db()
    c = connect()
    import_text(c, FIXTURE)
    return c


def _pid(conn, prefix):
    return conn.execute("SELECT id FROM paper WHERE title LIKE ?", (prefix + "%",)).fetchone()[0]


def test_shared_entity_relations_and_insights(conn):
    relations.rebuild_relations(conn, None, None)
    rel = {(r["src_id"], r["dst_id"], r["type"]) for r in conn.execute("SELECT * FROM paper_relation")}
    adbs, dir_adbs = _pid(conn, "Activity-dependent"), _pid(conn, "Directional Adaptive")
    assert (min(adbs, dir_adbs), max(adbs, dir_adbs), "same_device") in rel  # both use Medtronic Percept
    names = {
        r["name"]: r["n"]
        for r in conn.execute(
            "SELECT e.name, COUNT(*) n FROM entity e JOIN paper_entity pe ON pe.entity_id = e.id WHERE e.type='insight' GROUP BY e.id"
        )
    }
    for p in ("necessary node ≠ generator", "temporal precedence ≠ causality", "association ≠ mediation"):
        assert names.get(p, 0) >= 2, p


def test_global_paper_and_concept_graphs(conn):
    relations.rebuild_relations(conn, None, None)
    g = graph.build_graph(conn, "global")
    types = {n["type"] for n in g["nodes"]}
    assert {"paper", "method", "device"} <= types
    assert sum(n["type"] == "paper" for n in g["nodes"]) == 19
    aperiodic = [_pid(conn, t) for t in ("Aperiodic subthalamic", "Potential mechanisms", "Phenotypic and Movement")]
    comm = {n["paper_id"]: n["community"] for n in g["nodes"] if n["type"] == "paper"}
    assert len({comm[p] for p in aperiodic}) == 1  # the three aperiodic papers form one cluster
    focus = _pid(conn, "Directional Adaptive")
    pg = graph.build_graph(conn, "paper", focus)
    assert f"p{focus}" in {n["id"] for n in pg["nodes"]} and len(pg["nodes"]) < len(g["nodes"])
    cg = graph.build_graph(conn, "concept")
    assert any(n["type"] == "insight" for n in cg["nodes"])
    assert not any(e["type"] in ("similar", "same_device") for e in cg["edges"])


def test_every_digest_statement_is_traceable(conn):
    taxonomy.seed_preset(conn)
    cats = taxonomy.flat(conn)
    for i, p in enumerate(conn.execute("SELECT id FROM paper").fetchall()):
        conn.execute(
            "INSERT INTO paper_category(paper_id, category_id, is_primary) VALUES (?,?,1)", (p["id"], cats[i % 4]["id"])
        )
    conn.commit()
    relations.rebuild_relations(conn, None, None)
    for c in cats[:4]:
        prop = digest.propose(conn, c["id"], None)
        assert prop["content_md"]
        lines = [ln for ln in prop["content_md"].splitlines() if ln.startswith("- ")]
        assert lines and all("](#/paper/" in ln for ln in lines)  # each statement cites a source paper
    # LLM drafts: statements citing non-members are dropped
    d = digest.validate_draft(
        {"core_question": [{"text": "x", "sources": [999]}, {"text": "y", "sources": [1, 999]}]}, {1, 2}
    )
    assert d["core_question"] == [{"text": "y", "sources": [1]}]


def test_tsne_and_api(conn):
    rng = np.random.default_rng(0)
    X = np.concatenate([rng.normal(0, 0.05, (6, 8)) + 1, rng.normal(0, 0.05, (6, 8)) - 1])
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    Y = graph.tsne(X, iters=250)
    d = np.linalg.norm(Y[:, None] - Y[None], axis=-1)
    np.fill_diagonal(d, np.inf)
    nearest = d.argmin(1)
    purity = np.mean([(nearest[i] < 6) == (i < 6) for i in range(12)])
    assert purity >= 0.8  # nearest neighbours stay inside their own cluster
    client = TestClient(create_app())
    assert client.get("/api/graph?view=global").status_code == 200
    tl = client.get("/api/timeline").json()
    assert len(tl) == 19 and tl[0]["title"].startswith("Decoding alignment")
    cid = taxonomy.create(conn, "T", "d")
    pid = _pid(conn, "NeuroClaw")
    conn.execute("INSERT INTO paper_category(paper_id, category_id) VALUES (?,?)", (pid, cid))
    conn.commit()
    d = client.get(f"/api/digests/{cid}").json()
    assert d["version"] == 1 and not d["stale"]
