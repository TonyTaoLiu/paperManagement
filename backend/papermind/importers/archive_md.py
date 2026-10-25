"""Rule-based parser for the ChatGPT-summary archive Markdown (see 论文总结记录.md).

Stage 1 turns the file into `Turn`s; stage 2 (`segment`) groups turns into paper sessions:
new paper / follow-up / non-paper, merging turns that share a DOI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TURN_RE = re.compile(r"^## (\d{2})\. (.+)$", re.M)
URL_RE = re.compile(r"https?://[^\s<>）)\]】,，;；]+(?:\([^\s)]*\))?[^\s<>）)\]】,，;；]*")
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s?#<>）)\]]+")
ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|html|pdf)/(\d{4}\.\d{4,5})", re.I)
MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((?:[^()\s]|\([^)]*\))+\)")
CJK_RE = re.compile(r"[一-鿿]")

FOLLOWUP_CUES = ("？", "?", "吗", "是否", "为什么", "他们", "他的", "不要猜", "基于论文", "怎么", "能否", "这意思")
NONPAPER_CUES = ("你是一名", "保存", "下载到本地", "导出", "归档", "模板")

SECTION_KEYWORDS = {
    "background": ("背景", "核心问题", "研究问题", "问题", "论文定位", "定位", "话题", "核心动机", "核心主张", "研究定位"),
    "methods": ("方法", "数据", "设计", "模型", "模式", "规模", "关键分析", "架构", "受试者", "处理", "候选", "inverse", "两类"),
    "results": ("结果", "发现", "主旨", "报告", "主要观点", "解释", "意义", "泛化", "临床关联", "实用实验", "合成恢复", "下游", "安全性"),
    "team": ("团队", "作者", "关系", "参考", "原文", "代码", "论文及代码"),
    "critique": ("批判", "局限", "质疑", "疑问", "评价", "边界", "限制", "核心疑问", "疑点", "核实标记", "审读警示", "历史精度"),
}  # fmt: skip


@dataclass
class Turn:
    index: int
    heading: str
    user: str
    assistant: str
    urls: list[str] = field(default_factory=list)
    has_attachment: bool = False


@dataclass
class PaperSession:
    turns: list[Turn]  # the turns that describe the paper itself (usually 1; 2 when merged by DOI)
    followups: list[Turn] = field(default_factory=list)
    title: str = ""
    doi: str = ""
    arxiv_id: str = ""
    url: str = ""
    code_url: str = ""

    @property
    def turn_indexes(self) -> list[int]:
        return [t.index for t in self.turns] + [t.index for t in self.followups]


@dataclass
class ArchiveParse:
    papers: list[PaperSession]
    non_paper_turns: list[Turn]
    turns: list[Turn]


def parse_turns(text: str) -> list[Turn]:
    start = text.find("# 一、逐轮讨论记录")
    end = text.find("\n# 二、", start if start >= 0 else 0)
    body = text[start : end if end > 0 else None] if start >= 0 else text
    matches = list(TURN_RE.finditer(body))
    turns: list[Turn] = []
    for i, m in enumerate(matches):
        chunk = body[m.end() : matches[i + 1].start() if i + 1 < len(matches) else len(body)]
        chunk = re.sub(r"\n---\s*$", "", chunk.strip())
        user_part, _, assistant = chunk.partition("**助手")
        user_part = user_part.replace("**用户（原文）**", "").strip()
        user = "\n".join(re.sub(r"^>\s?", "", ln) for ln in user_part.splitlines() if ln.startswith(">")).strip()
        assistant = ("**助手" + assistant).strip() if assistant else ""
        urls = _clean_urls(URL_RE.findall(chunk))
        turns.append(Turn(int(m.group(1)), m.group(2).strip(), user, assistant, urls, "[附件]" in user))
    return turns


def _clean_urls(urls: list[str]) -> list[str]:
    out: list[str] = []
    for u in urls:
        u = u.rstrip(".。,，;；\\")
        u = u.replace("\\(", "(").replace("\\)", ")")
        if u not in out:
            out.append(u)
    return out


def normalize_doi(doi: str) -> str:
    d = doi.lower().rstrip(".")
    d = re.sub(r"(\.full(\.pdf)?|\.abstract|\.pdf)$", "", d)
    d = re.sub(r"v\d+$", "", d)
    return d


def extract_doi(urls: list[str]) -> str:
    for u in urls:
        m = DOI_RE.search(u)
        if m:
            return normalize_doi(m.group(0))
    return ""


def extract_arxiv(urls: list[str]) -> str:
    for u in urls:
        m = ARXIV_RE.search(u)
        if m:
            return m.group(1)
    return ""


def clean_user_title(user: str) -> str:
    """Turn a user message such as '@Web search Title: X' or '### [X](url)' into a bare title."""
    t = re.sub(r"\[附件\].*", "", user)
    t = re.sub(r"@(Web search|网页搜索)\s*", "", t)
    t = MD_LINK_RE.sub(lambda m: m.group(1), t)
    t = URL_RE.sub("", t)
    t = t.replace("&#x20;", " ")
    t = re.sub(r"^[\s#>*]+", "", t)
    t = re.sub(r"^(总结这篇论文|总结这篇|总结这篇文章)\s*[:：]?\s*", "", t)
    t = re.sub(r"^title\s*[:：]\s*", "", t, flags=re.I)
    t = re.sub(r"[（(]\s*[）)]", "", t)
    return t.strip(" \t\n*[]（）()。").strip()


def title_from_assistant(assistant: str) -> str:
    m = re.search(r"\*\*论文\*\*[:：]\s*\*([^*]+)\*", assistant)
    return m.group(1).strip(" ，,.。") if m else ""


def _is_title_like(text: str) -> bool:
    if not text or CJK_RE.search(text):
        return False
    return len(text.split()) >= 3


def classify_turn(turn: Turn, have_paper: bool) -> str:
    """Return 'paper' | 'followup' | 'non_paper' using rules only."""
    if turn.has_attachment:
        return "paper"
    if any(c in turn.user for c in NONPAPER_CUES) and not turn.urls:
        return "non_paper"
    if DOI_RE.search(turn.user) or ARXIV_RE.search(turn.user) or URL_RE.search(turn.user):
        return "paper"
    cleaned = clean_user_title(turn.user)
    if _is_title_like(cleaned):
        return "paper"
    if have_paper:
        return "followup"
    return "non_paper"


def segment(turns: list[Turn], force_first: bool = False) -> ArchiveParse:
    papers: list[PaperSession] = []
    non_paper: list[Turn] = []
    by_doi: dict[str, PaperSession] = {}
    current: PaperSession | None = None
    for t in turns:
        kind = classify_turn(t, current is not None)
        if force_first and kind == "non_paper" and current is None and not papers:
            kind = "paper"
        if kind == "non_paper":
            non_paper.append(t)
        elif kind == "followup" and current is not None:
            current.followups.append(t)
        else:
            doi = extract_doi(t.urls)
            # the paper link is usually in the user message; fall back to the assistant's link
            if not doi:
                user_urls = _clean_urls(URL_RE.findall(t.user))
                doi = extract_doi(user_urls)
            existing = by_doi.get(doi) if doi else None
            if existing is not None:
                existing.turns.append(t)
                current = existing
            else:
                current = PaperSession(turns=[t])
                papers.append(current)
                if doi:
                    by_doi[doi] = current
    for p in papers:
        _fill_identity(p)
    return ArchiveParse(papers, non_paper, turns)


def _fill_identity(p: PaperSession) -> None:
    title = ""
    for t in p.turns:
        title = clean_user_title(t.user) or title
        if _is_title_like(title) or title:
            if len(title.split()) >= 3 and not CJK_RE.search(title):
                break
        title = ""
    if not title:
        for t in p.turns:
            title = title_from_assistant(t.assistant)
            if title:
                break
    p.title = title
    all_urls = [u for t in p.turns for u in t.urls]
    p.doi = extract_doi(all_urls)
    p.arxiv_id = extract_arxiv(all_urls)
    code = [u for u in all_urls if "github.com" in u]
    p.code_url = code[0] if code else ""
    main = [u for u in all_urls if "github.com" not in u]
    # prefer a landing-page URL over a bare PDF link
    main.sort(key=lambda u: u.endswith(".pdf"))
    p.url = main[0] if main else ""


def parse_archive(text: str) -> ArchiveParse:
    return segment(parse_turns(text))


def split_sections(assistant: str) -> dict[str, str]:
    """Group the archived bullet points of one assistant reply into the five summary sections."""
    out: dict[str, list[str]] = {k: [] for k in SECTION_KEYWORDS}
    for line in assistant.splitlines():
        line = line.strip()
        if not line or line.startswith("**助手回复"):
            continue
        label = re.match(r"^[-*]?\s*\*\*([^*]+)\*\*", line)
        head = label.group(1) if label else line[:12]
        key = "results"
        for k, words in SECTION_KEYWORDS.items():
            if any(w in head for w in words):
                key = k
                break
        out[key].append(line)
    return {k: "\n".join(v) for k, v in out.items() if v}
