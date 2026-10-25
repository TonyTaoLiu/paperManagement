from pathlib import Path

from papermind.importers.archive_md import parse_archive, split_sections

FIXTURE = Path(__file__).parent / "fixtures" / "论文总结记录.md"


def test_segmentation_matches_acceptance_criteria():
    r = parse_archive(FIXTURE.read_text(encoding="utf-8"))
    assert len(r.papers) == 19
    assert [t.index for t in r.non_paper_turns] == [1, 27]
    by_first = {p.turns[0].index: p for p in r.papers}
    # turn 04 (inaccessible PDF) merged into turn 05 via the shared DOI
    assert [t.index for t in by_first[4].turns] == [4, 5]
    assert 5 not in by_first
    followups = {p.turns[0].index: [t.index for t in p.followups] for p in r.papers if p.followups}
    assert followups == {6: [7], 8: [9], 10: [11, 12], 18: [19]}


def test_titles_and_identifiers():
    r = parse_archive(FIXTURE.read_text(encoding="utf-8"))
    by_first = {p.turns[0].index: p for p in r.papers}
    assert by_first[2].title.startswith("Decoding alignment without encoding alignment")
    assert by_first[2].arxiv_id == "2605.05907"
    assert by_first[4].title.startswith("Aperiodic subthalamic activity")
    assert by_first[4].doi == "10.64898/2026.05.11.26352836"
    assert by_first[8].title == "NeuroClaw Technical Report"
    assert by_first[18].title.startswith("Generative deep learning reconstructs")
    assert by_first[18].code_url.endswith("ECoGSTNDecoding")
    assert by_first[25].title.startswith("Generation mechanisms")
    assert all(p.title for p in r.papers)


def test_section_split():
    r = parse_archive(FIXTURE.read_text(encoding="utf-8"))
    s = split_sections(r.papers[1].turns[0].assistant)
    assert "background" in s and "critique" in s
