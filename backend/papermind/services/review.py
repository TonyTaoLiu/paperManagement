"""Recall mode: spaced repetition with an FSRS-4.5 style scheduler (stability / difficulty / power forgetting)."""

from __future__ import annotations

import math
import sqlite3
from datetime import UTC, datetime, timedelta

W = [
    0.5701,
    1.4436,
    4.1386,
    10.9355,
    5.1443,
    1.2006,
    0.8627,
    0.0362,
    1.629,
    0.1342,
    1.0166,
    2.1174,
    0.0839,
    0.3204,
    1.4676,
    0.219,
    2.8237,
]
DECAY, FACTOR = -0.5, 19 / 81
RETENTION = 0.9


def retrievability(elapsed_days: float, stability: float) -> float:
    return (1 + FACTOR * elapsed_days / stability) ** DECAY


def interval_days(stability: float, retention: float = RETENTION) -> float:
    return max(1.0, stability / FACTOR * (retention ** (1 / DECAY) - 1))


def next_state(stability: float, difficulty: float, elapsed_days: float, rating: int, reps: int) -> tuple[float, float]:
    """rating: 1 again, 2 hard, 3 good, 4 easy."""
    if reps == 0:
        s = W[rating - 1]
        d = min(10.0, max(1.0, W[4] - W[5] * (rating - 3)))
        return s, d
    r = retrievability(elapsed_days, max(stability, 0.01))
    d = difficulty - W[6] * (rating - 3)
    d = min(10.0, max(1.0, W[7] * W[4] + (1 - W[7]) * d))
    if rating == 1:
        s = W[11] * d ** (-W[12]) * ((stability + 1) ** W[13] - 1) * math.exp((1 - r) * W[14])
    else:
        hard = W[15] if rating == 2 else 1.0
        easy = W[16] if rating == 4 else 1.0
        s = stability * (
            1 + math.exp(W[8]) * (11 - d) * stability ** (-W[9]) * (math.exp((1 - r) * W[10]) - 1) * hard * easy
        )
    return max(0.1, s), d


def _now() -> datetime:
    return datetime.now(UTC)


def ensure_cards(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "INSERT OR IGNORE INTO review_card(paper_id, due_at) SELECT id, ? FROM paper WHERE status = 'active'",
        (_now().isoformat(),),
    )
    conn.commit()
    return cur.rowcount


def due_cards(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    ensure_cards(conn)
    rows = conn.execute(
        "SELECT rc.*, p.title, p.one_liner FROM review_card rc JOIN paper p ON p.id = rc.paper_id WHERE rc.due_at <= ? ORDER BY rc.due_at LIMIT ?",
        (_now().isoformat(), limit),
    ).fetchall()
    out = []
    for r in rows:
        crit = conn.execute(
            "SELECT content_md FROM paper_section WHERE paper_id = ? AND kind = 'critique'", (r["paper_id"],)
        ).fetchone()
        lines = [ln.lstrip("-* ").strip() for ln in (crit["content_md"] if crit else "").splitlines() if ln.strip()]
        out.append(
            {
                "paper_id": r["paper_id"],
                "title": r["title"],
                "one_liner": r["one_liner"],
                "critique": lines[:2],
                "reps": r["reps"],
            }
        )
    return out


def answer_card(conn: sqlite3.Connection, paper_id: int, rating: int) -> dict:
    if rating not in (1, 2, 3, 4):
        raise ValueError("rating must be 1-4")
    ensure_cards(conn)
    c = conn.execute("SELECT * FROM review_card WHERE paper_id = ?", (paper_id,)).fetchone()
    if c is None:
        raise KeyError(paper_id)
    last = datetime.fromisoformat(c["due_at"]) - timedelta(days=interval_days(c["stability"])) if c["reps"] else _now()
    elapsed = max(0.0, (_now() - last).total_seconds() / 86400)
    s, d = next_state(c["stability"], c["difficulty"], elapsed, rating, c["reps"])
    days = 0.007 if rating == 1 else interval_days(s)  # "again" comes back in ~10 minutes
    due = _now() + timedelta(days=days)
    conn.execute(
        "UPDATE review_card SET stability = ?, difficulty = ?, reps = reps + 1, due_at = ? WHERE paper_id = ?",
        (s, d, due.isoformat(), paper_id),
    )
    conn.commit()
    return {"paper_id": paper_id, "stability": s, "difficulty": d, "due_at": due.isoformat(), "interval_days": days}


def due_count(conn: sqlite3.Connection) -> int:
    ensure_cards(conn)
    return conn.execute("SELECT COUNT(*) FROM review_card WHERE due_at <= ?", (_now().isoformat(),)).fetchone()[0]
