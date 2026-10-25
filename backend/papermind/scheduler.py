"""In-process scheduler: daily recommendation refresh."""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from papermind.config import load_settings
from papermind.db.core import connect
from papermind.services import recommend
from papermind.services.models import models

log = logging.getLogger("papermind.scheduler")
_sched: BackgroundScheduler | None = None


def run_daily() -> dict:
    if not models.embed_available():
        log.info("daily recommendations skipped: embedding model not ready")
        return {"skipped": True}
    conn = connect()
    try:
        client, spec = models.embedder()
        llm = models.llm() if models.llm_available() else None
        return recommend.refresh(conn, client, spec, llm)
    finally:
        conn.close()


def start() -> BackgroundScheduler | None:
    global _sched
    s = load_settings()
    if not s.get("rec_daily", True) or _sched is not None:
        return _sched
    _sched = BackgroundScheduler(daemon=True)
    _sched.add_job(
        run_daily,
        "cron",
        hour=int(s.get("rec_hour", 8)),
        minute=0,
        id="daily-recs",
        misfire_grace_time=3600,
        coalesce=True,
    )
    _sched.start()
    return _sched


def stop() -> None:
    global _sched
    if _sched is not None:
        _sched.shutdown(wait=False)
        _sched = None
