import httpx
from papermind.db.core import connect, init_db
from papermind.services.metadata import abstract_from_index, enrich_paper

WORK = {
    "id": "https://openalex.org/W123",
    "doi": "https://doi.org/10.1234/abcd",
    "title": "Some Paper About Beta",
    "publication_year": 2026,
    "primary_location": {"source": {"display_name": "Nature Testing"}},
    "abstract_inverted_index": {"Beta": [0], "bursts": [1], "matter": [2]},
    "authorships": [
        {
            "author": {"id": "https://openalex.org/A1", "display_name": "Ada Lovelace"},
            "institutions": [{"display_name": "UCSF"}],
        },
    ],
    "cited_by_count": 7,
    "referenced_works": ["https://openalex.org/W9"],
}


def _client(calls):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "/works/doi:10.1234/abcd" in str(request.url):
            return httpx.Response(200, json=WORK)
        if "search=" in str(request.url):
            return httpx.Response(200, json={"results": [WORK]})
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_abstract_inverted_index():
    assert abstract_from_index(WORK["abstract_inverted_index"]) == "Beta bursts matter"


def test_enrich_by_doi_and_title_fallback():
    init_db()
    conn = connect()
    conn.execute("INSERT INTO paper(title, title_norm, doi) VALUES ('Some Paper About Beta', 'x', '10.1234/abcd')")
    conn.execute("INSERT INTO paper(title, title_norm) VALUES ('Some paper about beta.', 'y')")
    conn.execute(
        "INSERT INTO paper(title, title_norm, user_edited, venue) VALUES ('Some Paper About Beta', 'z', '[\"venue\"]', 'Mine')"
    )
    conn.commit()
    calls: list[str] = []
    c = _client(calls)
    assert enrich_paper(conn, 1, c) and enrich_paper(conn, 2, c) and enrich_paper(conn, 3, c)
    p = conn.execute("SELECT * FROM paper WHERE id = 1").fetchone()
    assert (p["year"], p["venue"], p["citation_count"]) == (2026, "Nature Testing", 7)
    assert p["abstract"] == "Beta bursts matter"
    assert conn.execute("SELECT name FROM author").fetchone()[0] == "Ada Lovelace"
    assert conn.execute("SELECT venue FROM paper WHERE id = 3").fetchone()[0] == "Mine"  # user edit preserved
    assert conn.execute("SELECT year FROM paper WHERE id = 2").fetchone()[0] == 2026  # found via title search
