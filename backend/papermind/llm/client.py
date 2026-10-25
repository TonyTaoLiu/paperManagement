"""Unified OpenAI-compatible client for generation and embeddings.

Works against the local llama-server children, an external endpoint (Ollama / LM Studio)
or a cloud API: only the base URL and model name differ.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import httpx
from pydantic import BaseModel, ValidationError


@dataclass
class ChatResult:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    parsed: BaseModel | None = None
    raw: dict = field(default_factory=dict)

    @property
    def tokens_per_second(self) -> float:
        return self.completion_tokens / self.seconds if self.seconds else 0.0


class LLMClient:
    def __init__(self, base_url: str, model: str = "local", api_key: str = "none", timeout: float = 900):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.timeout = timeout

    def chat(
        self,
        messages: list[dict],
        *,
        schema: type[BaseModel] | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.1,
        retries: int = 1,
    ) -> ChatResult:
        body: dict = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            # Disable "thinking" for models that support the switch; others ignore it.
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "strict": True,
                                "schema": schema.model_json_schema()},
            }  # fmt: skip
        last_err: Exception | None = None
        for _ in range(retries + 1):
            t0 = time.time()
            r = httpx.post(
                f"{self.base_url}/chat/completions", json=body, headers=self.headers,
                timeout=self.timeout,
            )  # fmt: skip
            r.raise_for_status()
            data = r.json()
            text = data["choices"][0]["message"].get("content") or ""
            usage = data.get("usage", {})
            result = ChatResult(
                text=text,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                seconds=time.time() - t0,
                raw=data,
            )
            if schema is None:
                return result
            try:
                result.parsed = schema.model_validate(json.loads(text))
                return result
            except (json.JSONDecodeError, ValidationError) as e:
                last_err = e
                body["temperature"] = min(0.5, body["temperature"] + 0.2)
        raise ValueError(f"model output failed schema validation: {last_err}")

    def embed(self, texts: list[str]) -> list[list[float]]:
        r = httpx.post(
            f"{self.base_url}/embeddings", json={"model": self.model, "input": texts},
            headers=self.headers, timeout=self.timeout,
        )  # fmt: skip
        r.raise_for_status()
        rows = sorted(r.json()["data"], key=lambda d: d["index"])
        return [row["embedding"] for row in rows]
