"""Resumable file downloader with progress callbacks and Hugging Face mirror support."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import httpx

from papermind.config import data_dir, load_settings
from papermind.runtime.catalog import ModelSpec

ProgressCb = Callable[[int, int], None]  # (downloaded_bytes, total_bytes)


def models_dir() -> Path:
    p = data_dir() / "models"
    p.mkdir(parents=True, exist_ok=True)
    return p


def hf_url(spec: ModelSpec, mirror: str = "") -> str:
    base = (mirror or os.environ.get("HF_ENDPOINT") or "https://huggingface.co").rstrip("/")
    return f"{base}/{spec.repo}/resolve/main/{spec.filename}"


def download_file(url: str, dest: Path, progress: ProgressCb | None = None, expected_size: int = 0) -> Path:
    """Download `url` to `dest`, resuming from `dest.part` when possible."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    done = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={done}-"} if done else {}
    with httpx.stream("GET", url, headers=headers, follow_redirects=True, timeout=60) as r:
        if r.status_code == 416:  # already complete
            part.rename(dest)
            return dest
        r.raise_for_status()
        if r.status_code == 200:  # server ignored Range: restart
            done = 0
        total = int(r.headers.get("content-length", 0)) + done or expected_size
        with open(part, "ab" if done else "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    part.rename(dest)
    return dest


def ensure_model(spec: ModelSpec, progress: ProgressCb | None = None) -> Path:
    dest = models_dir() / spec.path_name
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    mirror = load_settings().get("hf_mirror", "")
    urls = [hf_url(spec, mirror)]
    if mirror:
        urls.append(hf_url(spec, ""))  # fall back to the official host
    last: Exception | None = None
    for url in urls:
        try:
            return download_file(url, dest, progress, int(spec.size_gb * 1e9))
        except httpx.HTTPError as e:
            last = e
    raise RuntimeError(f"failed to download {spec.id}: {last}")


def delete_model(spec: ModelSpec) -> None:
    for suffix in ("", ".part"):
        (models_dir() / (spec.path_name + suffix)).unlink(missing_ok=True)
