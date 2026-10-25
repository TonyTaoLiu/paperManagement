"""In-process background tasks with progress, polled or streamed (SSE) by the UI."""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class Task:
    id: str
    name: str
    status: str = "running"  # running | done | error
    progress: float = 0.0
    message: str = ""
    result: object = None
    error: str = ""
    started: float = field(default_factory=time.time)
    log: list[str] = field(default_factory=list)

    def update(self, progress: float | None = None, message: str | None = None) -> None:
        if progress is not None:
            self.progress = max(0.0, min(1.0, progress))
        if message is not None:
            self.message = message
            self.log.append(message)
            del self.log[:-200]

    def as_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "status": self.status, "progress": self.progress,
            "message": self.message, "result": self.result, "error": self.error,
            "elapsed": time.time() - self.started,
        }  # fmt: skip


_tasks: dict[str, Task] = {}
_lock = threading.Lock()


def start_task(name: str, fn: Callable[[Task], object], *, background: bool = True) -> Task:
    task = Task(id=uuid.uuid4().hex[:12], name=name)
    with _lock:
        _tasks[task.id] = task

    def runner() -> None:
        try:
            task.result = fn(task)
            task.status, task.progress = "done", 1.0
        except Exception as e:  # noqa: BLE001 - surfaced to the UI
            task.status, task.error = "error", f"{type(e).__name__}: {e}"
            task.log.append(traceback.format_exc()[-1500:])

    if background:
        threading.Thread(target=runner, daemon=True, name=f"task-{name}").start()
    else:
        runner()
    return task


def get_task(task_id: str) -> Task | None:
    return _tasks.get(task_id)


def list_tasks() -> list[dict]:
    return [t.as_dict() for t in sorted(_tasks.values(), key=lambda t: -t.started)][:20]
