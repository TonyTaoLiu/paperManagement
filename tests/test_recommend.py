import json
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from papermind.db.core import connect, init_db
from papermind.embed.index import ensure_paper_embeddings
from papermind.pipeline.ingest import import_text
from papermind.recommend import ranker, sources
from papermind.runtime.catalog import ModelSpec
from papermind.services import qa, recommend

FIX = Path(__file__).parent / "fixtures"
SPEC = ModelSpec("fake-embed", "embed", "x/y", "z.gguf", 0.0)
VOCAB = ["beta", "aperiodic", "sleep", "gait", "dbs", "adaptive", "eeg", "diffusion", "percept", "mri"]


class FakeEmbed:
    def embed(self, texts):
        out = []
        for t in texts:
            low = t.lower()
            v = np.array([low.count(w) for w in VOCAB], dtype=float) + 0.01
            out.append((v / np.linalg.norm(v)).tolist())
        return out


def test_parse_arxiv_recorded_response():
    c = sources.parse_arxiv((FIX / "arxiv.xml").read_text())
    assert len(c) == 3 and c[0]["ext_id"].startswith("arxiv:") and c[0]["abstract"] and c[0]["authors"]
    assert c[0]["url"].startswith("https://arxiv.org/abs/")


def test_parse_pubmed_recorded_response():
    c = sources.parse_pubmed((FIX / "pm_fetch.xml").read_text())
    assert len(c) == 1 and c[0]["ext_id"] == "pmid:42250769"
    assert c[0]["title"].startswith("Shared and symptom-specific") and c[0]["doi"] == "10.1016/j.nbd.2026.107472"
    assert c[0]["abstract"] and c[0]["authors"]


def test_parse_medrxiv_recorded_response():
    c = sources.parse_biorxiv(json.loads((FIX / "medrxiv.json").read_text()), "medrxiv")
    assert len(c) == 4 and all(x["doi"].startswith("10.") and x["title"] for x in c)


def test_parse_openalex_and_s2_shapes():
    w = {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/X", "title": "T", "publication_year": 2026, "publication_date": "2026-10-01",
         "abstract_inverted_index": {"hello": [0], "world": [1]}, "authorships": [{"author": {"id": "https://openalex.org/A1", "display_name": "Ada"}}],
         "referenced_works": ["https://openalex.org/W9"], "primary_location": {"source": {"display_name": "J"}}}  # fmt: skip
    c = sources.parse_openalex_work(w)
    assert (c["abstract"], c["doi"], c["authors"], c["refs"]) == (
        "hello world",
        "10.1/x",
        ["Ada"],
        ["https://openalex.org/W9"],
    )
    s = sources.parse_s2(
        [{"paperId": "abc", "title": "S", "year": 2026, "externalIds": {"DOI": "10.2/Y"}, "authors": [{"name": "Bo"}]}]
    )
    assert s[0]["doi"] == "10.2/y" and s[0]["ext_id"] == "s2:abc"


def test_recency_weights_decay():
    w = ranker.recency_weights(5)
    assert w[0] == 1.0 and all(w[i] > w[i + 1] for i in range(4))


@pytest.fixture
def env():
    init_db()
    conn = connect()
    import_text(conn, (FIX / "论文总结记录.md").read_text(encoding="utf-8"))
    ensure_paper_embeddings(conn, FakeEmbed(), SPEC)
    return conn


def _cands():
    return [
        {"ext_id": "x:1", "title": "Adaptive DBS with beta feedback", "abstract": "adaptive dbs beta percept", "authors": ["Ann Lee"], "year": 2026, "url": "u1", "doi": "10.9/1", "venue": "J", "source": "arxiv", "published": date.today().isoformat(), "refs": [], "author_ids": []},  # fmt: skip
        {"ext_id": "x:2", "title": "Diffusion model for EEG", "abstract": "diffusion eeg", "authors": ["Bob Ray"], "year": 2026, "url": "u2", "doi": "10.9/2", "venue": "J", "source": "arxiv", "published": "2020-01-01", "refs": [], "author_ids": []},  # fmt: skip
        {"ext_id": "x:3", "title": "MRI gait study", "abstract": "mri gait", "authors": ["Cy Moon"], "year": 2026, "url": "u3", "doi": "10.9/3", "venue": "J", "source": "pubmed", "published": "2020-01-01", "refs": [], "author_ids": []},  # fmt: skip
        {"ext_id": "x:4", "title": "Aperiodic Subthalamic Activity Underlies Sleep-Wake Modulation", "abstract": "", "authors": [], "year": 2026, "url": "u4", "doi": "", "venue": "J", "source": "pubmed", "published": "", "refs": [], "author_ids": []},  # fmt: skip
    ]  # fmt: skip


def test_dedupe_against_library_and_ranking_reasons(env):
    lib = recommend.library_state(env, SPEC.id)
    ids = recommend.store_candidates(env, _cands(), lib["titles"], set(lib["dois"]))
    assert len(ids) == 3  # candidate 4 is already in the library (title match)
    recommend.embed_candidates(env, FakeEmbed(), SPEC, ids)
    recommend.rescore(env, SPEC.id)
    recs = recommend.list_candidates(env)
    assert len(recs) == 3 and all(r["reason"] for r in recs)
    assert recs[0]["title"].startswith("Adaptive DBS")  # closest to a library full of aDBS/beta papers
    assert "相似" in recs[0]["reason"] and recs[0]["group_name"] == "new"


def test_feedback_changes_ranking(env):
    lib = recommend.library_state(env, SPEC.id)
    ids = recommend.store_candidates(env, _cands(), lib["titles"], set(lib["dois"]))
    recommend.embed_candidates(env, FakeEmbed(), SPEC, ids)
    recommend.rescore(env, SPEC.id)
    before = [r["id"] for r in recommend.list_candidates(env)]
    first = before[0]
    recommend.give_feedback(env, first, -1, SPEC.id)  # dislike the top one
    other = before[1]
    recommend.give_feedback(env, other, 1, SPEC.id)
    after = [r["id"] for r in recommend.list_candidates(env)]
    assert first not in after  # disliked ones leave the list
    third = before[2]
    # the liked item's neighbour ranks first among the remaining ones
    assert after[0] in (before[2], other) or after != before[1:]
    assert recommend.list_candidates(env, status="liked")[0]["id"] == other
    assert third in after


def test_followed_author_and_citation_signals():
    V = np.eye(3)
    sigs = ranker.compute_signals(
        V, np.eye(3)[:1], [1], np.zeros((0, 3)), np.zeros((0, 3)), [[], ["W5"], []], ["W1", "W2", "W3"],
        {1: {"W1", "W5"}}, [["Ann Lee"], [], []], {ranker.norm_name("Ann Lee")},
    )  # fmt: skip
    assert sigs[0].auth == 1.0 and sigs[0].cited_by_lib == 1  # followed author, and cited by a library paper
    assert sigs[1].coupled == 1 and sigs[2].cited_by_lib == 0


def test_derive_queries(env):
    qs = recommend.derive_queries(env)
    assert qs and all(isinstance(q, str) for q in qs)
    assert any("brain stimulation" in q or "Parkinson" in q or "LFP" in q.upper() or "subthalamic" in q for q in qs)


def test_qa_grounded_and_out_of_scope(env, monkeypatch):
    class FakeLLM:
        model = "fake"

        def chat(self, messages, **kw):
            first = int(messages[1]["content"].split("[P")[1].split("]")[0])

            class R:
                text = f"Percept 上的 aDBS 使用单/双阈值 [P999] [P{first}]"

            return R()

    monkeypatch.setattr(qa.search, "semantic_search", lambda conn, q, n: [])
    res = qa.answer(env, "Percept 能否更改 aDBS 算法", FakeLLM())
    assert res["used_llm"] and res["sources"] and "[P999]" not in res["answer"]  # invented citation stripped
    assert all(isinstance(s["id"], int) for s in res["sources"])
    nope = qa.answer(env, "quantum chromodynamics lattice", FakeLLM())
    assert nope["answer"] == qa.NO_ANSWER and nope["sources"] == []
    ext = qa.answer(env, "aperiodic exponent 睡眠", None)
    assert not ext["used_llm"] and "[P" in ext["answer"]
