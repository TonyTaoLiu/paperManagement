from __future__ import annotations

from fastapi import APIRouter, HTTPException

from papermind.services.models import models
from papermind.services.tasks import get_task, list_tasks, start_task

router = APIRouter(prefix="/api")


@router.get("/models/status")
def models_status() -> dict:
    return models.status()


@router.post("/models/setup")
def models_setup() -> dict:
    task = start_task("setup-models", lambda t: models.setup(t))
    return task.as_dict()


@router.get("/tasks")
def tasks() -> list[dict]:
    return list_tasks()


@router.get("/tasks/{task_id}")
def task(task_id: str) -> dict:
    t = get_task(task_id)
    if t is None:
        raise HTTPException(404, "task not found")
    return t.as_dict()
