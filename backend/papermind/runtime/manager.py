"""Manage llama-server child processes (one for generation, one for embeddings)."""

from __future__ import annotations

import atexit
import os
import socket
import subprocess
import time
from pathlib import Path

import httpx

from papermind.config import data_dir


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LlamaProcess:
    def __init__(
        self,
        binary: Path,
        model: Path,
        *,
        embedding: bool = False,
        ctx: int = 8192,
        threads: int | None = None,
        extra_args: list[str] | None = None,
    ):
        self.binary, self.model, self.embedding = binary, model, embedding
        self.ctx, self.threads = ctx, threads or max(1, (os.cpu_count() or 4))
        self.extra_args = extra_args or []
        self.port = 0
        self.proc: subprocess.Popen | None = None
        self.log_path = data_dir() / "logs" / f"llama-{'embed' if embedding else 'llm'}.log"

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def start(self, timeout: float = 300) -> None:
        if self.proc and self.proc.poll() is None:
            return
        self.port = free_port()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            str(self.binary), "-m", str(self.model), "--host", "127.0.0.1",
            "--port", str(self.port), "-c", str(self.ctx), "-t", str(self.threads),
            "--no-webui",
        ]  # fmt: skip
        if self.embedding:
            cmd += [
                "--embeddings",
                "--pooling",
                "last" if "Qwen3-Embedding" in self.model.name else "mean",
            ]
        cmd += self.extra_args
        log = open(self.log_path, "ab")  # noqa: SIM115 - owned by the child for its lifetime
        self.proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
        atexit.register(self.stop)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"llama-server exited early; see {self.log_path}")
            try:
                if httpx.get(f"http://127.0.0.1:{self.port}/health", timeout=2).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        self.stop()
        raise TimeoutError(f"llama-server did not become ready; see {self.log_path}")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def peak_rss_mb(self) -> float:
        """Resident memory of the child in MB (Linux /proc), 0 when unavailable."""
        if not self.proc:
            return 0.0
        try:
            for line in Path(f"/proc/{self.proc.pid}/status").read_text().splitlines():
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) / 1024
        except OSError:
            pass
        return 0.0
