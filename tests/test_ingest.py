from pathlib import Path

from papermind.db.core import connect, init_db
from papermind.pipeline.ingest import import_text

FIXTURE = (Path(__file__).parent / "fixtures" / "论文总结记录.md").read_text(encoding="utf-8")


def _setup():
    init_db()
    return connect()


def test_import_archive_acceptance():
    conn = _setup()
    r = import_text(conn, FIXTURE, filename="论文总结记录.md")
    assert r.new == 19
    assert conn.execute("SELECT COUNT(*) FROM paper").fetchone()[0] == 19
    assert r.non_paper == [1, 27]
    # 04 merged into 05: one paper, with turn 04 kept as an earlier-attempt follow-up
    row = conn.execute("SELECT id FROM paper WHERE title LIKE 'Aperiodic subthalamic%'").fetchone()
    turns = conn.execute("SELECT turn_indexes FROM paper_source WHERE paper_id=?", (row["id"],)).fetchone()[0]
    assert turns == "[4, 5]"
    follow = {
        r["title"][:12]: r["n"]
        for r in conn.execute(
            "SELECT p.title, COUNT(f.id) n FROM paper p JOIN followup f ON f.paper_id=p.id GROUP BY p.id"
        )
    }
    assert sum(follow.values()) == 6  # 7, 9, 11, 12, 19 + the failed turn-04 attempt
    fu = conn.execute("SELECT turn_index, is_correction FROM followup ORDER BY turn_index").fetchall()
    assert [f["turn_index"] for f in fu] == [4, 7, 9, 11, 12, 19]
    assert [f["turn_index"] for f in fu if f["is_correction"]] == [12]


def test_reimport_is_idempotent():
    conn = _setup()
    import_text(conn, FIXTURE)
    again = import_text(conn, FIXTURE)
    assert again.already_imported
    assert conn.execute("SELECT COUNT(*) FROM paper").fetchone()[0] == 19
    # a slightly changed archive (new hash) still must not duplicate papers or follow-ups
    r = import_text(conn, FIXTURE + "\n<!-- edited -->\n")
    assert r.new == 0
    assert conn.execute("SELECT COUNT(*) FROM paper").fetchone()[0] == 19
    assert conn.execute("SELECT COUNT(*) FROM followup").fetchone()[0] == 6


def test_user_edits_survive_reimport():
    conn = _setup()
    import_text(conn, FIXTURE)
    conn.execute("UPDATE paper SET one_liner='MINE', user_edited='[\"one_liner\"]' WHERE title LIKE 'NeuroClaw%'")
    conn.commit()
    import_text(conn, FIXTURE + "\n<!-- v2 -->\n")
    assert conn.execute("SELECT one_liner FROM paper WHERE title LIKE 'NeuroClaw%'").fetchone()[0] == "MINE"


def test_entities_and_sections():
    conn = _setup()
    import_text(conn, FIXTURE)
    ents = {
        (r["type"], r["name"])
        for r in conn.execute("SELECT e.type, e.name FROM entity e JOIN paper_entity pe ON pe.entity_id=e.id")
    }
    assert ("device", "Medtronic Percept") in ents
    assert ("insight", "necessary node ≠ oscillator generator") in ents
    n_sections = conn.execute("SELECT COUNT(DISTINCT paper_id) FROM paper_section").fetchone()[0]
    assert n_sections == 19


def test_paste_single_summary_and_yaml():
    conn = _setup()
    text = """# My Paper On Beta Bursts

背景与问题：测试。
```yaml
paper:
  title: My Paper On Beta Bursts
  doi: 10.1234/abcd
  year: 2026
  paper_type: 综述
  modalities: [EEG]
  one_liner: 一句话
  verification: 全文已读
```
"""
    r = import_text(conn, text)
    assert r.new == 1
    p = conn.execute("SELECT * FROM paper").fetchone()
    assert (p["doi"], p["year"], p["paper_type"], p["verification"]) == ("10.1234/abcd", 2026, "综述", "全文已读")
