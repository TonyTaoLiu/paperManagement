"""Candidate scoring (docs 6.5): time-decayed similarity + feedback prototype + citation + author signals."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import numpy as np

W_SIM, W_CLS, W_CIT, W_AUTH = 0.45, 0.20, 0.20, 0.15


@dataclass
class Signals:
    sim: float = 0.0
    cls: float = 0.0
    cit: float = 0.0
    auth: float = 0.0
    near: list[tuple[int, float]] = field(default_factory=list)  # nearest library papers (id, cos)
    cited_by_lib: int = 0
    coupled: int = 0
    authors: list[str] = field(default_factory=list)


def recency_weights(n: int) -> np.ndarray:
    """Weight of the i-th most recent library paper: 1 / (1 + log10(i + 1)); newer papers count more."""
    return np.array([1.0 / (1.0 + math.log10(i + 1)) for i in range(n)])


def _minmax(x: np.ndarray) -> np.ndarray:
    if x.size == 0:
        return x
    lo, hi = float(x.min()), float(x.max())
    return np.zeros_like(x) if hi - lo < 1e-9 else (x - lo) / (hi - lo)


def norm_name(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.casefold())


def compute_signals(
    cand_vecs: np.ndarray,
    lib_vecs: np.ndarray,  # rows ordered most-recent first
    lib_ids: list[int],
    liked: np.ndarray,
    disliked: np.ndarray,
    cand_refs: list[list[str]],
    cand_ext: list[str],
    lib_refs: dict[int, set[str]],
    cand_authors: list[list[str]],
    followed: set[str],
) -> list[Signals]:
    n = len(cand_vecs)
    sigs = [Signals() for _ in range(n)]
    if n == 0:
        return sigs
    raw_sim = np.zeros(n)
    if len(lib_vecs):
        S = cand_vecs @ lib_vecs.T
        w = recency_weights(len(lib_vecs))
        raw_sim = (S * w).sum(1) / w.sum()
        for i in range(n):
            top = np.argsort(-S[i])[:2]
            sigs[i].near = [(lib_ids[j], float(S[i, j])) for j in top]
    raw_cls = np.zeros(n)
    if len(liked) or len(disliked):
        pos = liked.mean(0) if len(liked) else 0.0
        neg = disliked.mean(0) if len(disliked) else 0.0
        raw_cls = cand_vecs @ (pos if len(liked) else np.zeros(cand_vecs.shape[1])) - cand_vecs @ (
            neg if len(disliked) else np.zeros(cand_vecs.shape[1])
        )
    raw_cit = np.zeros(n)
    all_refs: set[str] = set().union(*lib_refs.values()) if lib_refs else set()
    for i in range(n):
        cited_by = sum(1 for refs in lib_refs.values() if cand_ext[i] in refs)
        coupled = len(set(cand_refs[i]) & all_refs)
        sigs[i].cited_by_lib, sigs[i].coupled = cited_by, coupled
        raw_cit[i] = cited_by + 0.3 * coupled
    raw_auth = np.zeros(n)
    for i in range(n):
        hit = [a for a in cand_authors[i] if norm_name(a) in followed]
        sigs[i].authors = hit
        raw_auth[i] = 1.0 if hit else 0.0
    for arr, key in ((raw_sim, "sim"), (raw_cls, "cls"), (raw_cit, "cit"), (raw_auth, "auth")):
        for s, v in zip(sigs, _minmax(arr), strict=True):
            setattr(s, key, float(v))
    return sigs


def final_score(s: Signals) -> float:
    return W_SIM * s.sim + W_CLS * s.cls + W_CIT * s.cit + W_AUTH * s.auth
