"""Structured field extraction: rules first, optional LLM refinement."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from papermind.importers.archive_md import PaperSession, Turn, split_sections
from papermind.llm.schemas import (
    EXTRACT_SYSTEM,
    PaperExtraction,
    extract_user_prompt,
)
from papermind.pipeline.lexicon import (
    detect_principles,
    normalize_entity,
    spot_entities,
    spot_people,
    spot_principles,
)

TYPE_RULES = [
    ("综述", ("综述", "review")),
    ("数据资源", ("数据资源", "数据集论文", "dataset")),
    ("技术报告", ("技术报告", "technical report")),
    ("临床试验", ("临床试验", "trial")),
    ("计算模型", ("纯模型", "计算模型", "仿真", "firing-rate", "Wilson")),
    ("方法与工具", ("方法", "解码", "预测模型", "深度学习", "预训练", "生成模型", "inverse model")),
]
NUM_RE = re.compile(r"[A-Za-z_²]{0,12}\s?[=≈<>≥≤]\s?-?\d[\d.,]*\s?%?|\b\d[\d.,]*\s?(?:%|名|篇|h|Hz|ms|s|例|个中心)")
CORRECTION_CUES = ("不要猜", "更正", "纠正", "不对", "错了", "纠错")


@dataclass
class Extracted:
    title: str
    paper_type: str = "原始研究"
    one_liner: str = ""
    entities: dict[str, list[str]] = field(default_factory=dict)  # type -> names
    principles: list[str] = field(default_factory=list)
    sample_size: str = ""
    verification: str = "未核实"
    sections: dict[str, str] = field(default_factory=dict)
    key_numbers: list[str] = field(default_factory=list)
    used_llm: bool = False


def main_turn(session: PaperSession) -> Turn:
    """The turn carrying the actual summary (turns merged by DOI may include a failed attempt)."""
    return max(session.turns, key=lambda t: len(t.assistant) - (500 if "403" in t.assistant else 0))


def guess_verification(session: PaperSession) -> str:
    main = main_turn(session)
    text = main.assistant
    if main.has_attachment or "PDF 并追加" in text or "40 页 PDF" in text:
        return "部分章节"
    if "仅能辨认" in text or "返回 HTTP 403" in text:
        return "无法访问"
    if "根据摘要" in text or "仅摘要" in text:
        return "仅摘要"
    return "未核实"


def is_correction(turn: Turn) -> bool:
    return any(c in turn.user for c in CORRECTION_CUES)


def guess_paper_type(text: str) -> str:
    head = text[:400]
    for ptype, cues in TYPE_RULES:
        if any(c.lower() in head.lower() for c in cues):
            return ptype
    return "原始研究"


def guess_one_liner(text: str) -> str:
    m = re.search(r"\*\*核心一句话\*\*[:：]\s*(.+)", text)
    if m:
        return re.sub(r"[`*]", "", m.group(1)).strip()
    m = re.search(r"\*\*(?:论文定位|论文|核心问题|研究问题|核心主张|问题|话题)\*\*[:：]\s*(.+)", text)
    if m:
        return re.sub(r"[`*]", "", m.group(1)).strip()[:120]
    for line in text.splitlines():
        if line.strip() and not line.startswith("**助手"):
            return re.sub(r"[`*]", "", line).strip()[:120]
    return ""


def key_numbers(text: str, limit: int = 12) -> list[str]:
    out: list[str] = []
    for m in NUM_RE.finditer(text):
        s = m.group(0).strip()
        if len(s) >= 3 and s not in out:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def rule_extract(session: PaperSession) -> Extracted:
    main = main_turn(session)
    text = main.assistant
    thread = "\n".join(t.assistant for t in [*session.turns, *session.followups])  # follow-ups mention devices etc.
    ent = {k: [normalize_entity(k, n) for n in v] for k, v in spot_entities(thread + "\n" + session.title).items()}
    sample = re.search(r"(\d+)\s*名[^，。；,;]{0,12}(?:患者|被试|受试者|人)", text)
    people = spot_people(text)
    if people:
        ent["author"] = people
    ex = Extracted(
        title=session.title,
        paper_type=guess_paper_type(text),
        one_liner=guess_one_liner(text),
        entities=ent,
        principles=spot_principles(text)
        + [
            p
            for p in detect_principles("\n".join(t.assistant for t in [*session.turns, *session.followups]))
            if p not in spot_principles(text)
        ],
        sample_size=sample.group(0) if sample else "",
        verification=guess_verification(session),
        sections=split_sections(text),
        key_numbers=key_numbers(text),
    )
    return ex


def llm_extract(session: PaperSession, client, base: Extracted, max_chars: int = 3500) -> Extracted:
    """Refine rule output with the LLM; any LLM failure keeps the rule result."""
    text = main_turn(session).assistant[:max_chars]
    try:
        r = client.chat(
            [{"role": "system", "content": EXTRACT_SYSTEM}, {"role": "user", "content": extract_user_prompt(session.title, text)}],
            schema=PaperExtraction,
            max_tokens=900,
            retries=1,
        )  # fmt: skip
    except Exception:  # noqa: BLE001 - LLM is an enhancement, never a hard dependency
        return base
    p: PaperExtraction = r.parsed  # type: ignore[assignment]
    src = re.sub(r"\W+", "", text.lower())
    merged = dict(base.entities)

    def grounded(name: str) -> bool:  # drop LLM items that never appear in the source text
        return re.sub(r"\W+", "", name.lower()) in src

    for etype, items in (
        ("modality", p.modalities), ("method", p.methods), ("dataset", p.datasets),
        ("device", p.devices), ("disease", p.diseases), ("species", p.species),
    ):  # fmt: skip
        names = [normalize_entity(etype, n) for n in items if n and grounded(n)]
        cur = merged.setdefault(etype, [])
        cur.extend(n for n in names if n not in cur)
    base.entities = {k: v for k, v in merged.items() if v}
    base.paper_type = p.paper_type or base.paper_type
    base.one_liner = p.one_liner.strip() or base.one_liner
    for pr in p.principles:
        if "≠" in pr and pr not in base.principles:
            base.principles.append(pr)
    base.sample_size = base.sample_size or p.sample_size
    # the LLM may only upgrade verification when the rules found nothing definite
    if base.verification == "未核实" and p.verification != "未核实":
        base.verification = p.verification
    base.used_llm = True
    return base
