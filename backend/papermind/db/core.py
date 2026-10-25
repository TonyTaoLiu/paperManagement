"""SQLite connection helper and schema bootstrap."""

from __future__ import annotations

import sqlite3

from papermind.config import db_path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS setting (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS source (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, filename TEXT, sha256 TEXT UNIQUE NOT NULL,
  imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, raw_path TEXT, report TEXT
);

CREATE TABLE IF NOT EXISTS paper (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL, title_norm TEXT NOT NULL,
  doi TEXT, arxiv_id TEXT, url TEXT, code_url TEXT,
  year INTEGER, venue TEXT, abstract TEXT, paper_type TEXT, one_liner TEXT,
  verification TEXT NOT NULL DEFAULT '未核实',
  citation_count INTEGER, openalex_id TEXT, refs TEXT NOT NULL DEFAULT '[]', enriched_at TEXT, read_at TEXT, status TEXT NOT NULL DEFAULT 'active',
  user_edited TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_paper_doi ON paper(doi);
CREATE INDEX IF NOT EXISTS idx_paper_title_norm ON paper(title_norm);

CREATE TABLE IF NOT EXISTS paper_source (
  paper_id INTEGER NOT NULL REFERENCES paper(id) ON DELETE CASCADE,
  source_id INTEGER NOT NULL REFERENCES source(id) ON DELETE CASCADE,
  turn_indexes TEXT NOT NULL DEFAULT '[]',
  PRIMARY KEY (paper_id, source_id)
);

CREATE TABLE IF NOT EXISTS paper_section (
  id INTEGER PRIMARY KEY,
  paper_id INTEGER NOT NULL REFERENCES paper(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, content_md TEXT NOT NULL DEFAULT '',
  origin TEXT NOT NULL DEFAULT 'ai', evidence TEXT,
  UNIQUE (paper_id, kind)
);

CREATE TABLE IF NOT EXISTS followup (
  id INTEGER PRIMARY KEY,
  paper_id INTEGER NOT NULL REFERENCES paper(id) ON DELETE CASCADE,
  question TEXT NOT NULL, answer_md TEXT NOT NULL DEFAULT '', is_correction INTEGER NOT NULL DEFAULT 0,
  source_id INTEGER REFERENCES source(id) ON DELETE CASCADE, turn_index INTEGER,
  content_hash TEXT NOT NULL DEFAULT '',
  UNIQUE (paper_id, content_hash)
);

CREATE TABLE IF NOT EXISTS author (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, openalex_id TEXT, affiliation TEXT, followed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS paper_author (
  paper_id INTEGER NOT NULL REFERENCES paper(id) ON DELETE CASCADE,
  author_id INTEGER NOT NULL REFERENCES author(id) ON DELETE CASCADE,
  position INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (paper_id, author_id)
);

CREATE TABLE IF NOT EXISTS category (
  id INTEGER PRIMARY KEY, facet TEXT NOT NULL DEFAULT 'topic', name TEXT NOT NULL,
  parent_id INTEGER REFERENCES category(id) ON DELETE SET NULL,
  description TEXT NOT NULL DEFAULT '', created_by TEXT NOT NULL DEFAULT 'user', position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS paper_category (
  paper_id INTEGER NOT NULL REFERENCES paper(id) ON DELETE CASCADE,
  category_id INTEGER NOT NULL REFERENCES category(id) ON DELETE CASCADE,
  confidence REAL, origin TEXT NOT NULL DEFAULT 'auto', rationale TEXT,
  is_primary INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (paper_id, category_id)
);
CREATE TABLE IF NOT EXISTS category_rejection (
  paper_id INTEGER NOT NULL REFERENCES paper(id) ON DELETE CASCADE,
  category_id INTEGER NOT NULL REFERENCES category(id) ON DELETE CASCADE,
  PRIMARY KEY (paper_id, category_id)
);
CREATE TABLE IF NOT EXISTS inbox (
  paper_id INTEGER PRIMARY KEY REFERENCES paper(id) ON DELETE CASCADE,
  suggestions TEXT NOT NULL DEFAULT '[]', reason TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS entity (
  id INTEGER PRIMARY KEY, type TEXT NOT NULL, name TEXT NOT NULL, aliases TEXT NOT NULL DEFAULT '[]',
  description TEXT NOT NULL DEFAULT '', UNIQUE (type, name)
);
CREATE TABLE IF NOT EXISTS paper_entity (
  paper_id INTEGER NOT NULL REFERENCES paper(id) ON DELETE CASCADE,
  entity_id INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  relation TEXT NOT NULL DEFAULT 'uses', evidence TEXT, origin TEXT NOT NULL DEFAULT 'ai',
  PRIMARY KEY (paper_id, entity_id, relation)
);
CREATE TABLE IF NOT EXISTS paper_relation (
  id INTEGER PRIMARY KEY,
  src_id INTEGER NOT NULL REFERENCES paper(id) ON DELETE CASCADE,
  dst_id INTEGER NOT NULL REFERENCES paper(id) ON DELETE CASCADE,
  type TEXT NOT NULL, score REAL, evidence TEXT, origin TEXT NOT NULL DEFAULT 'auto',
  UNIQUE (src_id, dst_id, type)
);

CREATE TABLE IF NOT EXISTS embedding (
  owner_type TEXT NOT NULL, owner_id INTEGER NOT NULL, model TEXT NOT NULL,
  text_hash TEXT NOT NULL, dim INTEGER NOT NULL, vector BLOB NOT NULL,
  PRIMARY KEY (owner_type, owner_id, model)
);

CREATE TABLE IF NOT EXISTS digest (
  category_id INTEGER PRIMARY KEY REFERENCES category(id) ON DELETE CASCADE,
  content_md TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, source_paper_ids TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS candidate (
  id INTEGER PRIMARY KEY, ext_id TEXT UNIQUE NOT NULL, title TEXT NOT NULL, abstract TEXT, authors TEXT,
  year INTEGER, url TEXT, doi TEXT, venue TEXT, source TEXT, score REAL, reason TEXT, group_name TEXT,
  payload TEXT, status TEXT NOT NULL DEFAULT 'new', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY, candidate_id INTEGER NOT NULL REFERENCES candidate(id) ON DELETE CASCADE,
  value INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS review_card (
  paper_id INTEGER PRIMARY KEY REFERENCES paper(id) ON DELETE CASCADE,
  due_at TEXT, stability REAL NOT NULL DEFAULT 0, difficulty REAL NOT NULL DEFAULT 0,
  reps INTEGER NOT NULL DEFAULT 0
);

CREATE VIRTUAL TABLE IF NOT EXISTS paper_fts USING fts5(title, body, tokenize='trigram');
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
    finally:
        conn.close()


def fts5_available() -> bool:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()
