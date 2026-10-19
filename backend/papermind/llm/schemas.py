"""Pydantic schemas for structured LLM output (enforced via JSON-Schema-constrained decoding)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PAPER_TYPES = ["原始研究", "综述", "数据资源", "计算模型", "方法与工具", "临床试验", "技术报告"]
VERIFICATIONS = ["全文已读", "部分章节", "仅摘要", "无法访问", "未核实"]

PaperType = Literal["原始研究", "综述", "数据资源", "计算模型", "方法与工具", "临床试验", "技术报告"]
Verification = Literal["全文已读", "部分章节", "仅摘要", "无法访问", "未核实"]


class PaperExtraction(BaseModel):
    """Short structured fields extracted from one paper summary. Empty when absent from the text."""

    paper_type: PaperType
    one_liner: str = Field(description="一句话核心结论（中文，不超过60字）")
    species: list[str] = Field(default_factory=list)
    diseases: list[str] = Field(default_factory=list)
    modalities: list[str] = Field(description="数据模态，如 STN-LFP、ECoG、EEG、MEG、PSG、MRI、FDG-PET、仿真")
    methods: list[str] = Field(description="关键方法/模型/算法名称")
    datasets: list[str] = Field(default_factory=list)
    devices: list[str] = Field(default_factory=list)
    principles: list[str] = Field(default_factory=list, description="方法学原则，形如 'X ≠ Y'")
    sample_size: str = ""
    verification: Verification


EXTRACT_SYSTEM = (
    "你是计算神经科学领域的文献整理助手。根据给定的论文总结文本抽取结构化字段。"
    "只使用文本中明确出现的信息；文本没有的内容留空，不要猜测或编造。"
    "实体名称保留原文（英文术语不要翻译）。输出必须是符合给定 JSON Schema 的 JSON。"
)


def extract_user_prompt(title: str, text: str) -> str:
    return (
        f"论文标题：{title}\n\n总结文本：\n{text}\n\n"
        "请抽取：paper_type（文献类型）、one_liner（一句话核心结论）、species、diseases、modalities、"
        "methods、datasets、devices、principles（形如“A ≠ B”的方法学原则）、sample_size、"
        "verification（文本表明全文已读/部分章节/仅摘要/无法访问；无法判断填“未核实”）。"
    )


def category_schema(ids: list[str]) -> type[BaseModel]:
    """Schema for top-3 category ranking; category ids are constrained to the given enum."""
    from pydantic import create_model

    enum = Literal[tuple(ids)]  # type: ignore[valid-type]
    return create_model(
        "CategoryRanking",
        ranking=(list[enum], Field(description="按可能性从高到低最多3个类别编号")),  # type: ignore[valid-type]
        confidence=(float, Field(description="对第一个类别的把握，0到1")),
    )


CLASSIFY_SYSTEM = (
    "你是论文分类助手。根据论文总结，从给定的主题类别中选出最合适的主类别，并按可能性从高到低列出最多3个类别编号。"
)


def classify_user_prompt(categories: list[tuple[str, str, str]], title: str, text: str) -> str:
    cats = "\n".join(f"{cid}. {name}：{desc}" for cid, name, desc in categories)
    return f"可选类别：\n{cats}\n\n论文标题：{title}\n\n总结文本：\n{text}\n\n请输出该论文的类别排名。"
