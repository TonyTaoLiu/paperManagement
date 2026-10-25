import numpy as np
import pytest
from fastapi.testclient import TestClient
from papermind.db.core import connect, init_db
from papermind.embed.index import ensure_paper_embeddings
from papermind.main import create_app
from papermind.runtime.catalog import ModelSpec
from papermind.services import classify, router, taxonomy
from papermind.services.models import models

VOCAB = ["beta", "burst", "aperiodic", "exponent", "sleep", "spindle", "gait", "freezing", "adbs", "closed-loop"]
SPEC = ModelSpec("fake-embed", "embed", "x/y", "z.gguf", 0.0)


class FakeEmbed:
    def embed(self, texts):
        out = []
        for t in texts:
            low = t.lower()
            v = np.array([low.count(w) for w in VOCAB], dtype=float) + 0.01
            out.append((v / np.linalg.norm(v)).tolist())
        return out


@pytest.fixture
def conn(monkeypatch):
    init_db()
    c = connect()
    for name, desc in [
        ("Beta", "beta burst beta"),
        ("Aperiodic", "aperiodic exponent aperiodic"),
        ("Sleep", "sleep spindle sleep"),
        ("Gait", "gait freezing gait"),
    ]:
        taxonomy.create(c, name, desc)
    monkeypatch.setattr(models, "embedder", lambda: (FakeEmbed(), SPEC))
    return c


def _paper(conn, title, one_liner=""):
    cur = conn.execute(
        "INSERT INTO paper(title, title_norm, one_liner) VALUES (?,?,?)", (title, title.lower(), one_liner)
    )
    conn.commit()
    return cur.lastrowid


def test_zero_shot_routing_and_decisions(conn):
    a = _paper(conn, "Aperiodic exponent changes", "aperiodic exponent aperiodic")
    s = _paper(conn, "Sleep spindle detection", "sleep spindle sleep")
    mixed = _paper(conn, "Gait and beta", "gait beta")
    ensure_paper_embeddings(conn, FakeEmbed(), SPEC)
    ra = router.route_paper(conn, a, FakeEmbed(), SPEC)
    assert ra.suggestions[0].name == "Aperiodic" and ra.decision == "auto"
    assert router.route_paper(conn, s, FakeEmbed(), SPEC).suggestions[0].name == "Sleep"
    rm = router.route_paper(conn, mixed, FakeEmbed(), SPEC)
    assert {x.name for x in rm.suggestions[:2]} == {"Gait", "Beta"}
    assert rm.decision in ("inbox", "auto")


def test_knn_and_rejection_and_learning(conn):
    ids = [_paper(conn, f"Beta paper {i}", "beta burst") for i in range(3)]
    ensure_paper_embeddings(conn, FakeEmbed(), SPEC)
    beta = conn.execute("SELECT id FROM category WHERE name='Beta'").fetchone()[0]
    for i in ids[:2]:
        classify.set_categories(conn, i, [beta])
    res = router.route_paper(conn, ids[2], FakeEmbed(), SPEC)
    assert res.suggestions[0].category_id == beta and res.suggestions[0].parts["knn"] == 1.0
    classify.decide(conn, ids[2], "reject", beta)
    res2 = router.route_paper(conn, ids[2], FakeEmbed(), SPEC)
    assert all(s.category_id != beta for s in res2.suggestions)


def test_hierarchy_rule_and_inbox_api(conn):
    beta = conn.execute("SELECT id FROM category WHERE name='Beta'").fetchone()[0]
    child = taxonomy.create(conn, "Beta bursts", "beta burst burst", beta)
    p = _paper(conn, "Beta burst study", "beta burst beta burst")
    ensure_paper_embeddings(conn, FakeEmbed(), SPEC)
    res = router.route_paper(conn, p, FakeEmbed(), SPEC)
    assert res.suggestions[0].category_id in (beta, child)
    # tree edit guards
    with pytest.raises(ValueError):
        taxonomy.update(conn, beta, parent_id=child)

    client = TestClient(create_app())
    router.apply_result(conn, p, router.RouteResult("inbox", res.suggestions[:3], "x"))
    inbox = client.get("/api/inbox").json()
    assert [i["id"] for i in inbox] == [p]
    r = client.post(f"/api/inbox/{p}/decision", json={"action": "confirm", "category_id": beta})
    assert r.status_code == 200
    assert client.get("/api/inbox").json() == []
    assert client.get(f"/api/papers/{p}").json()["categories"][0]["name"] == "Beta"
