"""Parser for the official ChatGPT data export (conversations.json)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from papermind.importers.archive_md import URL_RE, Turn, _clean_urls


def _text_of(message: dict) -> str:
    parts = (message.get("content") or {}).get("parts") or []
    return "\n".join(p for p in parts if isinstance(p, str)).strip()


def _main_path(conv: dict) -> list[dict]:
    mapping = conv.get("mapping") or {}
    node_id = conv.get("current_node")
    path: list[dict] = []
    seen: set[str] = set()
    while node_id and node_id in mapping and node_id not in seen:
        seen.add(node_id)
        node = mapping[node_id]
        if node.get("message"):
            path.append(node["message"])
        node_id = node.get("parent")
    return list(reversed(path))


def parse_conversations(raw: str) -> list[tuple[dict, list[Turn]]]:
    """Return (conversation metadata, turns) per conversation."""
    data = json.loads(raw)
    if isinstance(data, dict):
        data = [data]
    out: list[tuple[dict, list[Turn]]] = []
    for conv in data:
        turns: list[Turn] = []
        user: str | None = None
        attach = False
        answers: list[str] = []
        first_time: float | None = None

        def flush() -> None:
            nonlocal user, attach, answers
            if user is not None:
                assistant = ("**助手回复（内容归档）**\n\n" + "\n\n".join(answers)) if answers else ""
                urls = _clean_urls(URL_RE.findall(user + "\n" + assistant))
                turns.append(Turn(len(turns) + 1, conv.get("title") or "", user, assistant, urls, attach))  # noqa: B023
            user, attach, answers = None, False, []

        for msg in _main_path(conv):
            role = (msg.get("author") or {}).get("role")
            text = _text_of(msg)
            if role == "user":
                flush()
                user = text
                attach = bool((msg.get("metadata") or {}).get("attachments"))
                first_time = first_time or msg.get("create_time")
            elif role == "assistant" and user is not None and text:
                answers.append(text)
        flush()
        meta = {"title": conv.get("title") or "", "create_time": _iso(first_time or conv.get("create_time"))}
        out.append((meta, turns))
    return out


def _iso(ts: float | None) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d") if ts else ""


def looks_like_chatgpt_export(raw: str) -> bool:
    head = raw.lstrip()[:2000]
    return head.startswith(("[", "{")) and '"mapping"' in raw[:200000]
