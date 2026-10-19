import json
import zipfile
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from papermind.db.core import connect, init_db
from papermind.main import create_app
from papermind.pipeline.ingest import import_text
from papermind.services import backup, export, relations, review, taxonomy

FIXTURE = (Path(__file__).parent / "fixtures" / "论文总结记录.md").read_text(encoding="utf-8")


@pytest.fixture
def conn():
    init_db()
    c = connect()
    import_text(c, FIXTURE)
    taxonomy.seed_preset(c)
    cat = c.execute("SELECT id FROM category LIMIT 1").fetchone()[0]
    c.execute("INSERT INTO paper_category(paper_id, category_id, is_primary, origin) VALUES (1, ?, 1, 'user')", (cat,))
    c.execute("UPDATE paper SET user_edited = '[\"one_liner\"]', one_liner = 'edited' WHERE id = 2")
    c.commit()
    relations.rebuild_relations(c, None, None)
    return c


def test_json_roundtrip_is_lossless(conn, tmp_path, monkeypatch):
    before = export.export_json(conn)
    # fresh library in another data dir
    monkeypatch.setenv("PAPERMIND_DATA_DIR", str(tmp_path / "other"))
    init_db()
    other = connect()
    assert other.execute("SELECT COUNT(*) FROM paper").fetchone()[0] == 0
    export.import_json(other, json.loads(json.dumps(before)))
    after = export.export_json(other)
    assert after == before
    # search index is rebuilt too
    assert other.execute("SELECT COUNT(*) FROM paper_fts").fetchone()[0] == 19
    assert other.execute("SELECT one_liner FROM paper WHERE id = 2").fetchone()[0] == "edited"


def test_other_export_formats(conn):
    md = export.export_markdown(conn)
    assert md.count("\n# ") >= 19 and "追问记录" in md
    z = zipfile.ZipFile(BytesIO(export.export_obsidian(conn)))
    names = z.namelist()
    assert sum(n.startswith("Papers/") for n in names) == 19 and any(n.startswith("Topics/") for n in names)
    assert any(n.startswith("Insights/") for n in names)
    paper = z.read(next(n for n in names if "Directional Adaptive" in n)).decode()
    assert paper.startswith("---") and "[[" in paper
    bib = export.export_bibtex(conn)
    assert bib.count("@article{") == 19 and "title = {" in bib


def test_api_export_import_and_stats(conn):
    client = TestClient(create_app())
    assert client.get("/api/stats").json()["papers"] == 19
    r = client.get("/api/export?format=json")
    assert r.status_code == 200
    n = len(r.json()["tables"]["paper"])
    assert n == 19
    up = client.post("/api/import/json", files={"file": ("x.json", r.content, "application/json")})
    assert up.status_code == 200 and up.json()["counts"]["paper"] == 19
    bad = client.post("/api/import/json", files={"file": ("x.json", b'{"format": "nope"}', "application/json")})
    assert bad.status_code == 400
    assert client.get("/api/export?format=bibtex").status_code == 200
    assert client.get("/api/export?format=zip").status_code == 400


def test_backups_retention(conn):
    for _ in range(9):
        backup.create_backup()
    assert len(backup.list_backups()) == backup.KEEP
    backup.startup_backup()
    assert len(backup.list_backups()) == backup.KEEP


def test_fsrs_scheduler(conn):
    assert review.due_count(conn) == 19
    first = review.due_cards(conn, 5)[0]
    pid = first["paper_id"]
    good = review.answer_card(conn, pid, 3)
    assert good["interval_days"] >= 1 and review.due_count(conn) == 18
    # growing stability on repeated success; an "again" shrinks it
    s1 = good["stability"]
    conn.execute(
        "UPDATE review_card SET due_at = ? WHERE paper_id = ?",
        ((datetime.now(UTC) - timedelta(days=1)).isoformat(), pid),
    )
    conn.commit()
    s2 = review.answer_card(conn, pid, 3)["stability"]
    assert s2 > s1
    conn.execute(
        "UPDATE review_card SET due_at = ? WHERE paper_id = ?",
        ((datetime.now(UTC) - timedelta(days=1)).isoformat(), pid),
    )
    conn.commit()
    s3 = review.answer_card(conn, pid, 1)["stability"]
    assert s3 < s2
    assert review.retrievability(0, 5) == pytest.approx(1.0) and 0.89 < review.retrievability(5, 5) < 0.91
    with pytest.raises(ValueError):
        review.answer_card(conn, pid, 7)


def test_deleting_a_paper_drops_its_embedding(conn):
    from papermind.embed.index import load_matrix, to_blob

    for pid in (1, 2):
        conn.execute(
            "INSERT INTO embedding(owner_type, owner_id, model, text_hash, dim, vector) VALUES ('paper',?,'m','',2,?)",
            (pid, to_blob([1.0, 0.0])),
        )  # noqa: E501
    conn.commit()
    client = TestClient(create_app())
    assert client.delete("/api/papers/1").status_code == 200
    assert load_matrix(conn, "m")[0] == [2]
    conn.execute(
        "INSERT INTO embedding(owner_type, owner_id, model, text_hash, dim, vector) VALUES ('paper',999,'m','',2,?)",
        (to_blob([0.0, 1.0]),),
    )  # stale
    conn.commit()
    assert load_matrix(conn, "m")[0] == [2]  # orphans never reach relation building
