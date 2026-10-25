"""Pasted text: archive Markdown, a role-marked chat, or a single paper summary."""

from __future__ import annotations

import re

from papermind.importers.archive_md import TURN_RE, URL_RE, Turn, _clean_urls

USER_RE = re.compile(r"^(?:用户|User|You|我)\s*[:：]\s*", re.M | re.I)
ASSIST_RE = re.compile(r"^(?:助手|ChatGPT|Assistant|GPT)\s*[:：]\s*", re.M | re.I)


def is_archive(text: str) -> bool:
    return bool(TURN_RE.search(text)) and "**用户（原文）**" in text


def parse_chat(text: str) -> list[Turn] | None:
    """Parse 'User: ... / Assistant: ...' transcripts. Returns None when no markers are found."""
    if not USER_RE.search(text):
        return None
    pieces = re.split(r"(?m)^(?=(?:用户|User|You|我|助手|ChatGPT|Assistant|GPT)\s*[:：])", text)
    turns: list[Turn] = []
    user = None
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        if USER_RE.match(piece):
            user = USER_RE.sub("", piece, count=1).strip()
            turns.append(Turn(len(turns) + 1, "", user, "", [], False))
        elif ASSIST_RE.match(piece) and turns:
            body = ASSIST_RE.sub("", piece, count=1).strip()
            t = turns[-1]
            t.assistant = (
                (t.assistant + "\n\n" + body).strip() if t.assistant else "**助手回复（内容归档）**\n\n" + body
            )
    for t in turns:
        t.urls = _clean_urls(URL_RE.findall(t.user + "\n" + t.assistant))
        t.has_attachment = "[附件]" in t.user
    return turns


def single_summary(text: str) -> list[Turn]:
    """A bare summary: first non-empty line is the title (or a URL), the rest is the answer."""
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    first = re.sub(r"^[#>*\s]+", "", lines[0]).strip() if lines else ""
    urls = _clean_urls(URL_RE.findall(text))
    turn = Turn(1, first, first, "**助手回复（内容归档）**\n\n" + text.strip(), urls, False)
    return [turn]
