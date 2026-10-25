"""App-wide access to generation / embedding models (local llama-server, external or cloud)."""

from __future__ import annotations

import threading

from papermind.config import data_dir, load_settings
from papermind.llm.client import LLMClient
from papermind.runtime.catalog import DEFAULT_TIERS, ModelSpec, get_model
from papermind.runtime.downloader import ensure_model, models_dir
from papermind.runtime.llama_bin import ensure_llama_server, find_existing
from papermind.runtime.manager import LlamaProcess
from papermind.services.tasks import Task


class ModelService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._procs: dict[str, LlamaProcess] = {}

    # ---- configuration -------------------------------------------------
    def selected(self, kind: str) -> ModelSpec:
        s = load_settings()
        override = s.get(f"{kind}_model", "")
        return get_model(override or DEFAULT_TIERS[s["memory_tier"]][kind])

    def local_ready(self, kind: str) -> bool:
        return (models_dir() / self.selected(kind).path_name).exists()

    def status(self) -> dict:
        s = load_settings()
        return {
            "llama_server": str(find_existing() or ""),
            "data_dir": str(data_dir()),
            "tier": s["memory_tier"],
            "llm": self._model_status("llm"),
            "embed": self._model_status("embed"),
            "cloud_enabled": bool(s["cloud_llm"]["enabled"]),
            "external_endpoint": s["external_endpoint"],
            "running": {k: p.proc is not None and p.proc.poll() is None for k, p in self._procs.items()},
        }

    def _model_status(self, kind: str) -> dict:
        spec = self.selected(kind)
        return {"id": spec.id, "file": spec.filename, "size_gb": spec.size_gb, "downloaded": self.local_ready(kind)}

    # ---- setup (download binary + models) -----------------------------
    def setup(self, task: Task, kinds: tuple[str, ...] = ("embed", "llm")) -> dict:
        task.update(0.02, "获取 llama-server ...")
        binary = ensure_llama_server(lambda m: task.update(message=m))
        done = 0.1
        for i, kind in enumerate(kinds):
            spec = self.selected(kind)
            task.update(done, f"下载模型 {spec.id} ({spec.size_gb} GB) ...")
            lo, span = done, 0.9 / len(kinds)

            def cb(d: int, total: int, lo=lo, span=span) -> None:
                task.update(lo + span * (d / total if total else 0))

            ensure_model(spec, cb)
            done = 0.1 + 0.9 * (i + 1) / len(kinds)
        return {"llama_server": str(binary)}

    # ---- clients -------------------------------------------------------
    def _local(self, kind: str) -> LlamaProcess:
        with self._lock:
            proc = self._procs.get(kind)
            if proc is None or proc.proc is None or proc.proc.poll() is not None:
                spec = self.selected(kind)
                path = models_dir() / spec.path_name
                if not path.exists():
                    raise RuntimeError(f"model {spec.id} is not downloaded; run setup first")
                binary = find_existing()
                if binary is None:
                    raise RuntimeError("llama-server not available; run setup first")
                extra = ["-b", "2048", "-ub", "2048"] if kind == "embed" else []
                proc = LlamaProcess(binary, path, embedding=(kind == "embed"), ctx=spec.ctx, extra_args=extra)
                proc.start()
                self._procs[kind] = proc
            return proc

    def llm(self) -> LLMClient:
        s = load_settings()
        cloud = s["cloud_llm"]
        if cloud["enabled"] and cloud["base_url"]:
            return LLMClient(cloud["base_url"], cloud["model"], cloud["api_key"] or "none")
        if s["external_endpoint"]:
            return LLMClient(s["external_endpoint"], self.selected("llm").id)
        proc = self._local("llm")
        return LLMClient(proc.base_url, self.selected("llm").id)

    def embedder(self) -> tuple[LLMClient, ModelSpec]:
        spec = self.selected("embed")
        proc = self._local("embed")
        return LLMClient(proc.base_url, spec.id), spec

    def llm_available(self) -> bool:
        s = load_settings()
        return bool(
            (s["cloud_llm"]["enabled"] and s["cloud_llm"]["base_url"])
            or s["external_endpoint"]
            or (self.local_ready("llm") and find_existing())
        )

    def embed_available(self) -> bool:
        return bool(self.local_ready("embed") and find_existing())

    def shutdown(self) -> None:
        for p in self._procs.values():
            p.stop()
        self._procs.clear()


models = ModelService()
