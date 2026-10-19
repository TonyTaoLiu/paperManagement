"""SQLite backups (online backup API) with simple retention."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from papermind.config import data_dir, db_path

KEEP = 7


def backup_dir():
    p = data_dir() / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def create_backup(keep: int = KEEP) -> str | None:
    if not db_path().exists():
        return None
    name = f"papermind-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.db"
    dest = backup_dir() / name
    src = sqlite3.connect(db_path())
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    for old in sorted(backup_dir().glob("papermind-*.db"))[:-keep]:
        old.unlink(missing_ok=True)
    return name


def list_backups() -> list[dict]:
    return [
        {"name": p.name, "size": p.stat().st_size} for p in sorted(backup_dir().glob("papermind-*.db"), reverse=True)
    ]


def startup_backup() -> None:
    """Back up once per start, but only when the library has content."""
    if not db_path().exists():
        return
    conn = sqlite3.connect(db_path())
    try:
        has = (
            conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'paper'").fetchone()[0]
            and conn.execute("SELECT COUNT(*) FROM paper").fetchone()[0]
        )
    finally:
        conn.close()
    if has:
        create_backup()
