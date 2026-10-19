"""Model catalog: GGUF files the app knows how to download."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    id: str
    kind: str  # "llm" | "embed"
    repo: str
    filename: str
    size_gb: float
    ctx: int = 8192
    note: str = ""
    query_prefix: str = ""
    doc_prefix: str = ""

    @property
    def path_name(self) -> str:
        return f"{self.repo.replace('/', '__')}__{self.filename}"


LLM_MODELS: dict[str, ModelSpec] = {
    m.id: m
    for m in [
        ModelSpec("minicpm5-1b", "llm", "openbmb/MiniCPM5-1B-GGUF", "MiniCPM5-1B-Q4_K_M.gguf", 0.69),
        ModelSpec("minicpm5-2b", "llm", "openbmb/MiniCPM5-2B-GGUF", "MiniCPM5-2B-Q4_K_M.gguf", 1.56),
        ModelSpec("qwen3.5-2b", "llm", "unsloth/Qwen3.5-2B-GGUF", "Qwen3.5-2B-Q4_K_M.gguf", 1.28),
        ModelSpec("qwen3.5-4b", "llm", "unsloth/Qwen3.5-4B-GGUF", "Qwen3.5-4B-Q4_K_M.gguf", 2.74),
        ModelSpec("gemma4-e4b", "llm", "unsloth/gemma-4-E4B-it-GGUF", "gemma-4-E4B-it-Q4_K_M.gguf", 4.98),
        ModelSpec("lfm2.5-8b-a1b", "llm", "LiquidAI/LFM2.5-8B-A1B-GGUF", "LFM2.5-8B-A1B-Q4_K_M.gguf", 5.16),
        ModelSpec("qwen3.5-9b", "llm", "unsloth/Qwen3.5-9B-GGUF", "Qwen3.5-9B-Q4_K_M.gguf", 5.68),
    ]
}

EMBED_MODELS: dict[str, ModelSpec] = {
    m.id: m
    for m in [
        ModelSpec(
            "qwen3-embedding-0.6b",
            "embed",
            "Qwen/Qwen3-Embedding-0.6B-GGUF",
            "Qwen3-Embedding-0.6B-Q8_0.gguf",
            0.64,
            8192,
        ),
        ModelSpec(
            "embeddinggemma-2",
            "embed",
            "ggml-org/embeddinggemma-2-GGUF",
            "embeddinggemma-2-Q8_0.gguf",
            0.31,
            2048,
        ),
        ModelSpec("bge-m3", "embed", "ggml-org/bge-m3-Q8_0-GGUF", "bge-m3-q8_0.gguf", 0.63, 8192),
    ]
}

# Defaults per memory tier; finalised from the measurements in docs/模型评测.md.
DEFAULT_TIERS = {
    "8gb": {"llm": "minicpm5-2b", "embed": "qwen3-embedding-0.6b"},
    "16gb": {"llm": "qwen3.5-9b", "embed": "qwen3-embedding-0.6b"},
}


def get_model(model_id: str) -> ModelSpec:
    for table in (LLM_MODELS, EMBED_MODELS):
        if model_id in table:
            return table[model_id]
    raise KeyError(f"unknown model id: {model_id}")
