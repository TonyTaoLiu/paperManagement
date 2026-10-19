"""Pydantic schemas for structured LLM output (enforced via JSON-Schema-constrained decoding)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

PAPER_TYPES = ["原始研究", "综述", "数据资源", "计算模型", "方法与工具", "临床试验", "技术报告"]
VERIFICATIONS = ["全文已读", "部分章节", "仅摘要", "无法访问", "未核实"]

PaperType = Literal["原始研究", "综述", "数据资源", "计算模型", "方法与工具", "临床试验", "技术报告"]
Verification = Literal["全文已读", "部分章节", "仅摘要", "无法访问", "未核实"]


Short = Annotated[str, StringConstraints(max_length=48)]


class PaperExtraction(BaseModel):
    """Short structured fields extracted from one paper summary. Empty when absent from the text."""

    paper_type: PaperType
    one_liner: str = Field(max_length=120, description="一句话核心结论（中文，不超过60字）")
    species: list[Short] = Field(default_factory=list, max_length=4)
    diseases: list[Short] = Field(default_factory=list, max_length=4)
    modalities: list[Short] = Field(
        max_length=8, description="数据模态，如 STN-LFP、ECoG、EEG、MEG、PSG、MRI、FDG-PET、仿真"
    )
    methods: list[Short] = Field(max_length=8, description="关键方法/模型/算法名称")
    datasets: list[Short] = Field(default_factory=list, max_length=6)
    devices: list[Short] = Field(default_factory=list, max_length=4)
    principles: list[Annotated[str, StringConstraints(max_length=80)]] = Field(
        default_factory=list, max_length=4, description="方法学原则，形如 'X ≠ Y'"
    )
    sample_size: str = Field("", max_length=48)
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
        "verification（文本表明全文已读/部分章节/仅摘要/无法访问；无法判断填“未核实”）。\n"
        "命名参考：数据模态如 STN-LFP、ECoG、EEG、MEG、PSG、MRI、FDG-PET、仿真；"
        "文献类型只能从给定枚举中选择。"
    )


def category_schema(ids: list[str]) -> type[BaseModel]:
    """Schema for top-3 category ranking; category ids are constrained to the given enum."""
    from pydantic import create_model

    enum = Literal[tuple(ids)]  # type: ignore[valid-type]
    return create_model(
        "CategoryRanking",
        ranking=(list[enum], Field(min_length=1, max_length=3, description="按可能性从高到低最多3个类别编号")),  # type: ignore[valid-type]
        confidence=(float, Field(description="对第一个类别的把握，0到1")),
    )


CLASSIFY_SYSTEM = (
    "你是论文分类助手。根据论文总结，从给定的主题类别中选出最合适的主类别，并按可能性从高到低列出最多3个类别编号。"
)


def classify_user_prompt(categories: list[tuple[str, str, str]], title: str, text: str) -> str:
    cats = "\n".join(f"{cid}. {name}：{desc}" for cid, name, desc in categories)
    return f"可选类别：\n{cats}\n\n论文标题：{title}\n\n总结文本：\n{text}\n\n请输出该论文的类别排名。"


class SubCategory(BaseModel):
    name: str
    description: str


class TopCategory(BaseModel):
    name: str
    description: str = Field(description="一句话描述该主题涵盖的内容，用于后续自动归类")
    children: list[SubCategory] = Field(default_factory=list)


class TaxonomyProposal(BaseModel):
    categories: list[TopCategory]


TAXONOMY_SYSTEM = "你是科研文献管理助手。根据一批论文的标题与一句话结论，提出一套主题分类体系。"


def taxonomy_user_prompt(papers: list[tuple[str, str]]) -> str:
    lines = "\n".join(f"- {t}：{o}" for t, o in papers)
    return (
        f"论文列表：\n{lines}\n\n请提出 6 到 10 个一级主题，每个一级主题下设 0 到 4 个二级主题。"
        "每个类别写一句描述说明它包含哪类论文。类别名用中文，必要时保留英文术语。"
    )


RelationLabel = Literal["互补", "矛盾/挑战", "扩展", "同一问题的不同回答", "方法借鉴", "无明显关系"]


class RelationJudgement(BaseModel):
    relation: RelationLabel
    explanation: str = Field(max_length=100, description="一句话说明两篇论文为何有此关系")
    confidence: float = Field(description="0到1")


RELATION_SYSTEM = (
    "你是计算神经科学文献分析助手。判断两篇论文之间的关系：互补、矛盾/挑战、扩展、同一问题的不同回答、"
    "方法借鉴，或无明显关系。只根据给出的摘要性文字判断；没有明确依据就选“无明显关系”。"
)


def relation_user_prompt(a: dict, b: dict) -> str:
    def block(tag: str, p: dict) -> str:
        return f"论文{tag}：{p['title']}\n一句话结论：{p['one_liner']}\n主要结果：{p['results'][:500]}\n批判：{p['critique'][:300]}"

    return block("A", a) + "\n\n" + block("B", b) + "\n\n请给出关系类型、一句话说明和置信度。"


class Statement(BaseModel):
    text: str = Field(max_length=200)
    sources: list[int] = Field(min_length=1, max_length=4, description="支持该句的论文编号（P 后面的数字）")


class DigestDraft(BaseModel):
    core_question: list[Statement] = Field(max_length=3)
    relations: list[Statement] = Field(max_length=5)
    consensus: list[Statement] = Field(max_length=4)
    disputes: list[Statement] = Field(max_length=4)
    method_notes: list[Statement] = Field(max_length=4)
    open_questions: list[Statement] = Field(max_length=4)


DIGEST_SYSTEM = (
    "你是计算神经科学领域的综述写作助手。根据给定主题下的论文笔记写一页综述。"
    "每一句话都必须在 sources 里列出支持它的论文编号；没有依据的内容不要写；没有分歧或共识时对应列表留空。"
)
