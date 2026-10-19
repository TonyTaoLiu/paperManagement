"""Neuroscience entity lexicon: canonical names, aliases, and rule-based entity spotting."""

from __future__ import annotations

import re

# canonical name -> aliases (matched case-insensitively as whole tokens for ASCII, substring for CJK)
LEXICON: dict[str, dict[str, list[str]]] = {
    "modality": {
        "STN-LFP": ["STN-LFP", "STN LFP", "subthalamic LFP", "STN local field", "LFP", "local field potential"],
        "ECoG": ["ECoG", "electrocorticography", "皮层电图"],
        "EEG": ["EEG", "scalp EEG", "头皮 EEG", "脑电"],
        "MEG": ["MEG", "脑磁图", "magnetoencephalography"],
        "PSG": ["PSG", "polysomnography", "多导睡眠"],
        "MRI": ["MRI", "T1 MRI", "T1 结构 MRI", "结构 MRI"],
        "FDG-PET": ["FDG-PET", "FDG PET", "PET"],
        "fMRI": ["fMRI"],
        "仿真": ["仿真", "simulation", "synthetic", "模型研究", "纯模型"],
        "tACS": ["tACS"],
        "术中电生理": ["术中", "intraoperative", "perioperative"],
    },
    "method": {
        "aperiodic 分解": ["specparam", "FOOOF", "IRASA", "periodic/aperiodic", "aperiodic exponent"],
        "CCA": ["CCA", "canonical correlation"],
        "DDPM": ["DDPM", "denoising diffusion", "扩散模型"],
        "MAML": ["MAML", "meta-learning", "元学习"],
        "CNN": ["CNN", "卷积"],
        "Wilson–Cowan": ["Wilson–Cowan", "Wilson-Cowan", "Wilson Cowan"],
        "Jansen–Rit": ["Jansen–Rit", "Jansen-Rit", "Jansen Rit"],
        "RSA/CKA": ["RSA", "CKA", "Gromov"],
        "beta burst 分析": ["beta burst", "burst dynamics", "burst"],
        "自适应 DBS": ["aDBS", "adaptive DBS", "adaptive deep brain stimulation", "closed-loop"],
        "双阈值 aDBS": ["dual-threshold", "双阈值", "DT-aDBS"],
        "LLM Agent": ["LLM Agent", "Agent", "agent"],
        "LIF": ["LIF", "spiking"],
        "混合效应模型": ["mixed-effects", "混合效应"],
        "归一化连接组": ["connectome", "connectomics", "连接组"],
        "摊销推断": ["amortized", "摊销"],
    },
    "dataset": {
        "UCSF RC+S": ["UCSF", "RC+S"],
        "NatMEG": ["NatMEG"],
        "ADAPT-PD": ["ADAPT-PD"],
        "NeuroBench": ["NeuroBench"],
        "ADNI": ["ADNI"],
        "HCP": ["HCP"],
        "UK Biobank": ["UK Biobank", "UKB"],
    },
    "device": {
        "Medtronic Percept": ["Percept", "SenSight"],
        "Medtronic Summit RC+S": ["Summit RC+S", "RC+S"],
        "Kinarm": ["Kinarm"],
    },
    "disease": {
        "帕金森病": ["Parkinson", "帕金森", " PD ", "PD 患者", "PD STN", "PD DBS"],
        "肌张力障碍": ["dystonia", "肌张力障碍"],
        "抽动症": ["Tourette", "抽动"],
    },
    "species": {
        "人": ["患者", "patients", "human", "健康被试", "受试者"],
        "大鼠": ["rat ", "大鼠", "rodent"],
        "猴": ["monkey", "猴", "非人灵长类"],
    },
}

ALIAS_INDEX: dict[str, dict[str, str]] = {
    etype: {alias.lower(): canon for canon, aliases in table.items() for alias in aliases + [canon]}
    for etype, table in LEXICON.items()
}

PRINCIPLE_RE = re.compile(r"`([^`]*(?:≠|⇏|≢)[^`]*)`")


def normalize_entity(etype: str, name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip(" ,;.，；。")
    return ALIAS_INDEX.get(etype, {}).get(name.lower(), name)


def _present(alias: str, text: str, low: str) -> bool:
    a = alias.lower()
    if re.search(r"[一-鿿]", alias) or a.startswith(" ") or a.endswith(" "):
        return a in low
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(a)}(?![A-Za-z0-9])", low) is not None


def spot_entities(text: str) -> dict[str, list[str]]:
    """Find canonical entities of each type mentioned in `text`."""
    low = text.lower() + " "
    out: dict[str, list[str]] = {}
    for etype, table in LEXICON.items():
        found = [c for c, aliases in table.items() if any(_present(a, text, low) for a in aliases + [c])]
        if found:
            out[etype] = found
    return out


def spot_principles(text: str) -> list[str]:
    seen: list[str] = []
    for m in PRINCIPLE_RE.finditer(text):
        p = m.group(1).strip()
        if p not in seen:
            seen.append(p)
    return seen


# Methodological principles the user repeatedly applies (docs 1.2). A principle fires on a paper when
# every regex group matches somewhere in the paper's summary or follow-ups. Free-form principles written
# as `X ≠ Y` in the text are picked up by `spot_principles` and by the LLM in addition.
PRINCIPLE_TRIGGERS: dict[str, list[str]] = {
    "temporal precedence ≠ causality": [r"时间先后|先后顺序|时序|先行|领先|temporal|precedence", r"因果|causal"],
    "association ≠ mediation": [r"中介|mediat", r"相关|关联|associat"],
    "necessary node ≠ generator": [r"generator|发生器", r"不等于|不能|不一定|并非|必要|necessary"],
    "same beta frequency ≠ same mechanism": [r"相同.{0,12}(频|PSD|peak)|same beta", r"同一|机制|generator"],
}


def detect_principles(text: str) -> list[str]:
    return [name for name, pats in PRINCIPLE_TRIGGERS.items() if all(re.search(p, text, re.I) for p in pats)]


_NAME_RE = re.compile(r"[A-Z][a-zA-Z'’-]+(?: [A-Z]\.)?(?: [A-Z][a-zA-Z'’-]+)+")
_NOT_NAME = (
    "Hospital", "Institute", "University", "Berlin", "Beijing", "Trial", "Parkinson", "Deep", "Brain",
    "Medtronic", "Percept", "Digital", "Medicine", "Nature", "Cohort", "Technical", "Report", "Charité",
    "Tiantan", "Generative", "Network", "Wilson", "Stimulation",
)  # fmt: skip


def spot_people(text: str) -> list[str]:
    """Author/team names from lines that talk about authors (conservative, rule based)."""
    out: list[str] = []
    for line in text.splitlines():
        if not re.search(r"作者|团队|通讯|第一作者|以.{0,12}为核心", line):
            continue
        for m in _NAME_RE.finditer(line):
            name = m.group(0)
            if any(w in name for w in _NOT_NAME) or name in out:
                continue
            out.append(name)
    return out
