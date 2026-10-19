"""Runtime configuration: data directory and persisted user settings."""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_PORT = 8765

DEFAULT_SETTINGS: dict = {
    "ui_language": "zh",
    "memory_tier": "8gb",  # "8gb" | "16gb"
    "hf_mirror": "",  # e.g. https://hf-mirror.com
    "cloud_llm": {"enabled": False, "base_url": "", "api_key": "", "model": ""},
    "enrich_metadata": True,  # query OpenAlex for authors/year/abstract after import
    "contact_email": "",  # sent to OpenAlex/PubMed as the polite-pool contact (optional)
    "openalex_api_key": "",
    "s2_api_key": "",
    "rec_keywords": [],  # extra search keywords for recommendations (empty: derived from the library)
    "rec_daily": True,
    "rec_hour": 8,
    "llama_server_path": "",
    "external_endpoint": "",
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    path = Path(os.environ.get("PAPERMIND_DATA_DIR") or project_root() / "data")
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "papermind.db"


def settings_path() -> Path:
    return data_dir() / "settings.json"


def load_settings() -> dict:
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))
    p = settings_path()
    if p.exists():
        try:
            stored = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            stored = {}
        for key, value in stored.items():
            if isinstance(value, dict) and isinstance(settings.get(key), dict):
                settings[key].update(value)
            else:
                settings[key] = value
    return settings


def save_settings(update: dict) -> dict:
    settings = load_settings()
    for key, value in update.items():
        if key not in DEFAULT_SETTINGS:
            continue
        if isinstance(value, dict) and isinstance(settings.get(key), dict):
            settings[key].update(value)
        else:
            settings[key] = value
    settings_path().write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    return settings


def public_settings() -> dict:
    """Settings with secrets masked, safe to return to the browser."""
    s = load_settings()
    key = s["cloud_llm"].get("api_key", "")
    s["cloud_llm"]["api_key"] = "***" if key else ""
    return s
