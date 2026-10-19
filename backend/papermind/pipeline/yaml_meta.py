"""Parse the machine-readable YAML block produced by the improved summary prompt (Appendix B)."""

from __future__ import annotations

import re

import yaml

BLOCK_RE = re.compile(r"```ya?ml\s*\n(paper:.*?)```", re.S)


def parse_yaml_block(text: str) -> dict | None:
    m = BLOCK_RE.search(text)
    if not m:
        return None
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None
    paper = data.get("paper") if isinstance(data, dict) else None
    return paper if isinstance(paper, dict) else None


def _list(v) -> list[str]:
    if not v:
        return []
    return [str(x).strip() for x in (v if isinstance(v, list) else [v]) if str(x).strip()]


def meta_to_fields(meta: dict) -> dict:
    """Normalise a YAML metadata dict into the fields the ingest step understands."""
    return {
        "title": str(meta.get("title") or "").strip(),
        "doi": str(meta.get("doi") or "").strip(),
        "url": str(meta.get("url") or "").strip(),
        "code_url": str(meta.get("code_url") or "").strip(),
        "year": int(meta["year"]) if str(meta.get("year") or "").isdigit() else None,
        "venue": str(meta.get("venue") or "").strip(),
        "paper_type": str(meta.get("paper_type") or "").strip(),
        "one_liner": str(meta.get("one_liner") or "").strip(),
        "verification": str(meta.get("verification") or "").strip(),
        "sample_size": str(meta.get("sample_size") or "").strip(),
        "entities": {
            "species": _list(meta.get("species")),
            "disease": _list(meta.get("diseases")),
            "modality": _list(meta.get("modalities")),
            "method": _list(meta.get("methods")),
            "dataset": _list(meta.get("datasets")),
            "device": _list(meta.get("devices")),
        },
        "principles": _list(meta.get("principles")),
        "authors": ([str(meta["first_author"])] if meta.get("first_author") else []) + _list(meta.get("corresponding_authors")),
    }  # fmt: skip
