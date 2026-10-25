"""External paper sources. Each fetcher returns normalised candidate dicts and never raises on network errors.

Candidate: {ext_id, title, abstract, authors[list], year, url, doi, venue, source, published, refs[list], author_ids[list]}
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import date, timedelta

import httpx

from papermind.config import load_settings
from papermind.services.metadata import abstract_from_index

UA = {"User-Agent": "PaperMind/0.1 (local research tool)"}
OA = "https://api.openalex.org"
ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def _get(
    client: httpx.Client, url: str, params: dict | None = None, headers: dict | None = None, retries: int = 3
) -> httpx.Response | None:
    """GET with exponential back-off on 429/5xx (Semantic Scholar and OpenAlex rate-limit aggressively)."""
    for attempt in range(retries):
        try:
            r = client.get(url, params=params, headers={**UA, **(headers or {})}, timeout=25, follow_redirects=True)
        except httpx.HTTPError:
            time.sleep(1.5**attempt)
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2.0 ** (attempt + 1) if attempt < retries - 1 else 0)
            continue
        return r if r.status_code == 200 else None
    return None


def _cand(**kw) -> dict:
    base = {"ext_id": "", "title": "", "abstract": "", "authors": [], "year": None, "url": "", "doi": "", "venue": "", "source": "",
            "published": "", "refs": [], "author_ids": []}  # fmt: skip
    base.update(kw)
    base["doi"] = re.sub(r"^https?://(dx\.)?doi\.org/", "", base["doi"] or "").lower()
    return base


# ---- OpenAlex -----------------------------------------------------------------------------------
def openalex_params() -> dict:
    s = load_settings()
    out = {}
    if s.get("openalex_api_key"):
        out["api_key"] = s["openalex_api_key"]
    if s.get("contact_email"):
        out["mailto"] = s["contact_email"]
    return out


OA_SELECT = "id,doi,title,publication_year,publication_date,primary_location,abstract_inverted_index,authorships,cited_by_count,referenced_works"


def parse_openalex_work(w: dict) -> dict:
    src = (w.get("primary_location") or {}).get("source") or {}
    return _cand(
        ext_id=w.get("id", ""), title=(w.get("title") or "").strip(), abstract=abstract_from_index(w.get("abstract_inverted_index")),
        authors=[(a.get("author") or {}).get("display_name", "") for a in w.get("authorships") or []],
        author_ids=[(a.get("author") or {}).get("id", "") for a in w.get("authorships") or []],
        year=w.get("publication_year"), url=w.get("doi") or w.get("id", ""), doi=w.get("doi") or "", venue=src.get("display_name") or "",
        source="openalex", published=w.get("publication_date") or "", refs=w.get("referenced_works") or [],
    )  # fmt: skip


def openalex_search(client: httpx.Client, query: str, since: date, limit: int = 25) -> list[dict]:
    r = _get(client, f"{OA}/works", {"search": query, "filter": f"from_publication_date:{since.isoformat()}", "per-page": limit, "select": OA_SELECT, **openalex_params()})  # fmt: skip
    return [parse_openalex_work(w) for w in (r.json().get("results", []) if r else []) if w.get("title")]


def openalex_by_authors(client: httpx.Client, author_ids: list[str], since: date, limit: int = 25) -> list[dict]:
    if not author_ids:
        return []
    ids = "|".join(a.rsplit("/", 1)[-1] for a in author_ids[:20])
    r = _get(client, f"{OA}/works", {"filter": f"author.id:{ids},from_publication_date:{since.isoformat()}", "per-page": limit, "select": OA_SELECT, **openalex_params()})  # fmt: skip
    return [parse_openalex_work(w) for w in (r.json().get("results", []) if r else []) if w.get("title")]


def openalex_by_ids(client: httpx.Client, work_ids: list[str]) -> list[dict]:
    out: list[dict] = []
    for i in range(0, len(work_ids), 40):
        chunk = "|".join(w.rsplit("/", 1)[-1] for w in work_ids[i : i + 40])
        r = _get(
            client,
            f"{OA}/works",
            {"filter": f"openalex:{chunk}", "per-page": 50, "select": OA_SELECT, **openalex_params()},
        )
        out += [parse_openalex_work(w) for w in (r.json().get("results", []) if r else []) if w.get("title")]
    return out


# ---- arXiv --------------------------------------------------------------------------------------
def parse_arxiv(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    out = []
    for e in root.findall("a:entry", ATOM):
        aid = (e.findtext("a:id", "", ATOM) or "").rsplit("/abs/", 1)[-1]
        aid = re.sub(r"v\d+$", "", aid)
        published = (e.findtext("a:published", "", ATOM) or "")[:10]
        out.append(_cand(
            ext_id=f"arxiv:{aid}", title=re.sub(r"\s+", " ", e.findtext("a:title", "", ATOM)).strip(),
            abstract=re.sub(r"\s+", " ", e.findtext("a:summary", "", ATOM)).strip(),
            authors=[a.findtext("a:name", "", ATOM) for a in e.findall("a:author", ATOM)],
            year=int(published[:4]) if published else None, url=f"https://arxiv.org/abs/{aid}", venue="arXiv",
            source="arxiv", published=published, doi=e.findtext("arxiv:doi", "", ATOM) or "",
        ))  # fmt: skip
    return out


def arxiv_search(client: httpx.Client, query: str, limit: int = 25, categories: list[str] | None = None) -> list[dict]:
    q = f'all:"{query}"' if " " in query else f"all:{query}"
    if categories:
        q = f"({q}) AND (" + " OR ".join(f"cat:{c}" for c in categories) + ")"
    r = _get(client, "https://export.arxiv.org/api/query", {"search_query": q, "sortBy": "submittedDate", "sortOrder": "descending", "max_results": limit})  # fmt: skip
    try:
        return parse_arxiv(r.text) if r else []
    except ET.ParseError:
        return []


# ---- bioRxiv / medRxiv --------------------------------------------------------------------------
def parse_biorxiv(data: dict, server: str) -> list[dict]:
    out = []
    for x in data.get("collection", []):
        doi = x.get("doi", "")
        out.append(_cand(
            ext_id=f"{server}:{doi}", title=(x.get("title") or "").strip(), abstract=(x.get("abstract") or "").strip(),
            authors=[a.strip() for a in (x.get("authors") or "").split(";") if a.strip()], year=int((x.get("date") or "0000")[:4]) or None,
            url=f"https://www.{server}.org/content/{doi}v{x.get('version', 1)}", doi=doi, venue=server, source=server, published=x.get("date", ""),
        ))  # fmt: skip
    return out


def biorxiv_recent(
    client: httpx.Client, server: str, since: date, categories: list[str], max_pages: int = 3
) -> list[dict]:
    out: list[dict] = []
    for cat in categories:
        for page in range(max_pages):
            r = _get(
                client,
                f"https://api.biorxiv.org/details/{server}/{since.isoformat()}/{date.today().isoformat()}/{page * 100}",
                {"category": cat},
            )
            if not r:
                break
            data = r.json()
            out += parse_biorxiv(data, server)
            if len(data.get("collection", [])) < 100:
                break
    return out


# ---- PubMed -------------------------------------------------------------------------------------
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def parse_pubmed(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    out = []
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID", "")
        year = (
            art.findtext(".//JournalIssue/PubDate/Year")
            or (art.findtext(".//JournalIssue/PubDate/MedlineDate") or "")[:4]
        )
        doi = next((e.text for e in art.findall(".//ArticleId") if e.get("IdType") == "doi"), "") or ""
        abstract = " ".join("".join(t.itertext()) for t in art.findall(".//Abstract/AbstractText"))
        authors = [
            f"{a.findtext('ForeName', '')} {a.findtext('LastName', '')}".strip()
            for a in art.findall(".//Author")
            if a.findtext("LastName")
        ]
        out.append(_cand(
            ext_id=f"pmid:{pmid}", title="".join(art.find(".//ArticleTitle").itertext()).strip(" ."), abstract=abstract, authors=authors,
            year=int(year) if year.isdigit() else None, url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", doi=doi,
            venue=art.findtext(".//Journal/Title", ""), source="pubmed", published=f"{year}" if year else "",
        ))  # fmt: skip
    return out


def pubmed_search(client: httpx.Client, query: str, since: date, limit: int = 25) -> list[dict]:
    r = _get(client, f"{EUTILS}/esearch.fcgi", {"db": "pubmed", "term": query, "retmax": limit, "sort": "date", "retmode": "json", "datetype": "pdat", "mindate": since.strftime("%Y/%m/%d"), "maxdate": date.today().strftime("%Y/%m/%d")})  # fmt: skip
    if not r:
        return []
    ids = r.json().get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    f = _get(client, f"{EUTILS}/efetch.fcgi", {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"})
    try:
        return parse_pubmed(f.text) if f else []
    except ET.ParseError:
        return []


# ---- Semantic Scholar ---------------------------------------------------------------------------
S2 = "https://api.semanticscholar.org"
S2_FIELDS = "title,abstract,year,externalIds,authors,url,venue,publicationDate"


def parse_s2(items: list[dict]) -> list[dict]:
    out = []
    for p in items:
        ext = p.get("externalIds") or {}
        out.append(_cand(
            ext_id=f"s2:{p.get('paperId', '')}", title=(p.get("title") or "").strip(), abstract=p.get("abstract") or "",
            authors=[a.get("name", "") for a in p.get("authors") or []], year=p.get("year"), url=p.get("url") or "",
            doi=ext.get("DOI") or "", venue=p.get("venue") or "", source="semanticscholar", published=p.get("publicationDate") or "",
        ))  # fmt: skip
    return [c for c in out if c["title"]]


def s2_recommend(client: httpx.Client, positive_dois: list[str], limit: int = 25) -> list[dict]:
    """Recommendations seeded with library papers (needs DOIs). Rate-limited without a key: best effort."""
    key = load_settings().get("s2_api_key", "")
    headers = {"x-api-key": key} if key else {}
    ids = [f"DOI:{d}" for d in positive_dois[:20]]
    if not ids:
        return []
    try:
        r = client.post(f"{S2}/recommendations/v1/papers", json={"positivePaperIds": ids}, params={"fields": S2_FIELDS, "limit": limit}, headers={**UA, **headers}, timeout=25)  # fmt: skip
    except httpx.HTTPError:
        return []
    return parse_s2(r.json().get("recommendedPapers", [])) if r.status_code == 200 else []


def s2_search(client: httpx.Client, query: str, limit: int = 25) -> list[dict]:
    key = load_settings().get("s2_api_key", "")
    r = _get(
        client,
        f"{S2}/graph/v1/paper/search",
        {"query": query, "limit": limit, "fields": S2_FIELDS},
        {"x-api-key": key} if key else {},
    )
    return parse_s2(r.json().get("data", [])) if r else []


def fetch_all(client: httpx.Client, queries: list[str], since: date, followed_author_ids: list[str], library_dois: list[str],
              progress: Callable[[str], None] | None = None) -> list[dict]:  # fmt: skip
    """Run every configured source; one failing source never blocks the others."""
    out: list[dict] = []

    def run(name: str, fn: Callable[[], list[dict]]) -> None:
        try:
            got = fn()
        except Exception:  # noqa: BLE001 - sources are best effort
            got = []
        if progress:
            progress(f"{name}: {len(got)} 篇")
        out.extend(got)

    for q in queries:
        run(f"OpenAlex[{q}]", lambda q=q: openalex_search(client, q, since))
        run(
            f"arXiv[{q}]",
            lambda q=q: arxiv_search(client, q, 15, ["q-bio.NC", "eess.SP", "cs.LG", "stat.ML", "physics.bio-ph"]),
        )
        run(f"PubMed[{q}]", lambda q=q: pubmed_search(client, q, since))
    run("medRxiv", lambda: biorxiv_recent(client, "medrxiv", since, ["neurology"]))
    run("bioRxiv", lambda: biorxiv_recent(client, "biorxiv", since, ["neuroscience"]))
    run("OpenAlex[关注作者]", lambda: openalex_by_authors(client, followed_author_ids, since))
    run("SemanticScholar[推荐]", lambda: s2_recommend(client, library_dois))
    return out


def default_window(days: int = 21) -> date:
    return date.today() - timedelta(days=days)
