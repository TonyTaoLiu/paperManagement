from __future__ import annotations

import platform

from fastapi import APIRouter
from pydantic import BaseModel

from papermind import __version__
from papermind.config import data_dir, public_settings, save_settings
from papermind.db.core import fts5_available

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "fts5": fts5_available(),
        "platform": platform.system(),
        "data_dir": str(data_dir()),
    }


class SettingsUpdate(BaseModel):
    values: dict


@router.get("/settings")
def get_settings() -> dict:
    return public_settings()


@router.put("/settings")
def put_settings(body: SettingsUpdate) -> dict:
    values = dict(body.values)
    cloud = values.get("cloud_llm")
    if isinstance(cloud, dict) and cloud.get("api_key") == "***":
        cloud.pop("api_key")  # masked placeholder: keep the stored key
    save_settings(values)
    return public_settings()
