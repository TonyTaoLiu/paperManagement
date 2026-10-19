"""FastAPI entry point: API routes plus the pre-built static frontend."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from papermind import __version__
from papermind.api import categories, graph, imports, models, papers, system
from papermind.db.core import init_db

STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    init_db()
    app = FastAPI(title="PaperMind", version=__version__)
    app.include_router(system.router)
    app.include_router(models.router)
    app.include_router(imports.router)
    app.include_router(papers.router)
    app.include_router(categories.router)
    app.include_router(graph.router)

    if (STATIC_DIR / "index.html").exists():
        assets = STATIC_DIR / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            if full_path.startswith("api/"):
                return FileResponse(STATIC_DIR / "index.html", status_code=404)
            candidate = (STATIC_DIR / full_path).resolve()
            if full_path and candidate.is_file() and STATIC_DIR.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(STATIC_DIR / "index.html")

    return app
