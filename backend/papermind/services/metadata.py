"""Metadata enrichment from OpenAlex (free, no key). Failures are never fatal."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import sqlite3
import time

import httpx

from papermind.config import data_dir
from papermind.pipeline.ingest import reindex_fts

API = "https://api.openalex.org"
SELECT = (
    "id,doi,title,publication_year,primary_location,abstract_inverted_index,authorships,cited_by_count,referenced_works"
)


class EnrichUnavailable(RuntimeError):
    """The metadata service could not be reached (offline, rate limited)."""


def _cache_path(key: str):
    d = data_dir() / "cache" / "openalex"
    d.mkdir(parents=True, exist_ok=True)
    return d / (hashlib.sha256(key.encode()).hexdigest()[:24] + ".json")


def _get(client: httpx.Client, path: str, params: dict | None = None, retries: int = 3) -> dict | None:
    from papermind.config import load_settings

    s = load_settings()
    extra = {k: v for k, v in (("api_key", s.get("openalex_api_key")), ("mailto", s.get("contact_email"))) if v}
    key = path + json.dumps(params or {}, sort_keys=True)
    params = {**(params or {}), **extra}
    cp = _cache_path(key)
    if cp.exists():
        return json.loads(cp.read_text(encoding="utf-8"))
    for attempt in range(retries):
        try:
            r = client.get(API + path, params=params, timeout=15)
        except httpx.HTTPError:
            time.sleep(1.5**attempt)
            continue
        if r.status_code == 404:
            return None
        if r.status_code in (429, 500, 502, 503):
            time.sleep(1.5 ** (attempt + 1))
            continue
        if r.status_code != 200:
            return None
        data = r.json()
        cp.write_text(json.dumps(data), encoding="utf-8")
        return data
    raise EnrichUnavailable(path)


def abstract_from_index(inv: dict | None) -> str:
    if not inv:
        return ""
    words: list[tuple[int, str]] = [(pos, w) for w, positions in inv.items() for pos in positions]
    return " ".join(w for _, w in sorted(words))


def _similar(a: str, b: str) -> float:
    norm = lambda s: re.sub(r"[\W_]+", " ", s.casefold()).strip()  # noqa: E731
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def lookup(client: httpx.Client, doi: str = "", arxiv_id: str = "", title: str = "") -> dict | None:
    params = {"select": SELECT}
    if doi:
        w = _get(client, f"/works/doi:{doi}", params)
        if w:
            return w
    if arxiv_id:
        w = _get(client, f"/works/doi:10.48550/arXiv.{arxiv_id}", params)
        if w:
            return w
    if title:
        res = _get(client, "/works", {**params, "search": title, "per-page": 3})
        for w in (res or {}).get("results", []):
            if _similar(w.get("title") or "", title) >= 0.9:
                return w
    return None


def enrich_paper(conn: sqlite3.Connection, pid: int, client: httpx.Client | None = None) -> bool:
    row = conn.execute("SELECT * FROM paper WHERE id = ?", (pid,)).fetchone()
    if row is None:
        return False
    own = client is None
    client = client or httpx.Client(headers={"User-Agent": "PaperMind/0.1 (local research tool)"})
    try:
        w = lookup(client, row["doi"] or "", row["arxiv_id"] or "", row["title"])
    finally:
        if own:
            client.close()
    conn.execute("UPDATE paper SET enriched_at = CURRENT_TIMESTAMP WHERE id = ?", (pid,))
    if not w:
        conn.commit()
        return False
    locked = set(json.loads(row["user_edited"]))
    src = (w.get("primary_location") or {}).get("source") or {}
    new = {
        "year": w.get("publication_year"),
        "venue": src.get("display_name"),
        "abstract": abstract_from_index(w.get("abstract_inverted_index")),
        "citation_count": w.get("cited_by_count"),
        "openalex_id": w.get("id"),
        "doi": re.sub(r"^https?://doi.org/", "", w["doi"]).lower() if w.get("doi") else None,
    }
    for col, val in new.items():
        if val in (None, "") or col in locked:
            continue
        if row[col] in (None, "") or col in ("citation_count", "openalex_id"):
            conn.execute(f"UPDATE paper SET {col} = ? WHERE id = ?", (val, pid))
    conn.execute("UPDATE paper SET refs = ? WHERE id = ?", (json.dumps(w.get("referenced_works") or []), pid))
    if not conn.execute("SELECT 1 FROM paper_author WHERE paper_id = ?", (pid,)).fetchone():
        for i, a in enumerate(w.get("authorships") or []):
            name = (a.get("author") or {}).get("display_name")
            if not name:
                continue
            oid = (a.get("author") or {}).get("id")
            inst = ((a.get("institutions") or [{}])[0] or {}).get("display_name")
            existing = conn.execute("SELECT id FROM author WHERE openalex_id = ?", (oid,)).fetchone() if oid else None
            aid = (
                existing["id"]
                if existing
                else conn.execute(
                    "INSERT INTO author(name, openalex_id, affiliation) VALUES (?,?,?)", (name, oid, inst)
                ).lastrowid
            )
            conn.execute(
                "INSERT OR IGNORE INTO paper_author(paper_id, author_id, position) VALUES (?,?,?)", (pid, aid, i)
            )
    reindex_fts(conn, pid)
    conn.commit()
    return True
