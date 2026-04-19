"""Shared helpers for task lifecycle integration hooks."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from reins.cli import utils
from reins.export.task_exporter import TaskExporter
from reins.task.manager import TaskManager


def load_task(task_json_path: str | Path) -> dict[str, Any]:
    """Load a task export from disk."""
    return json.loads(Path(task_json_path).read_text(encoding="utf-8"))


def task_markdown(task_json_path: str | Path, task: dict[str, Any]) -> str:
    """Return the richest available task description for external systems."""
    task_path = Path(task_json_path)
    prd_path = task_path.with_name("prd.md")
    if prd_path.exists():
        return prd_path.read_text(encoding="utf-8")
    if isinstance(task.get("description"), str) and task["description"].strip():
        return str(task["description"])
    return str(task.get("title", "")).strip()


def task_developer(task: dict[str, Any]) -> str:
    """Return the most relevant human-facing developer field for notifications."""
    for key in ("assignee", "created_by"):
        value = task.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return "Unknown"


def metadata_value(task: dict[str, Any], key: str) -> Any | None:
    """Read a metadata value from an exported task."""
    metadata = task.get("metadata")
    if not isinstance(metadata, dict):
        return None
    return metadata.get(key)


def persist_task_metadata(
    task_json_path: str | Path,
    *,
    updates: dict[str, Any],
    updated_by: str,
) -> None:
    """Persist integration metadata through the task journal and export layer."""
    task_path = Path(task_json_path).resolve()
    task = load_task(task_path)
    task_id = task.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise RuntimeError(f"Task file at {task_path} is missing a valid task_id")

    repo_root = task_path.parents[3]
    projection = utils.rebuild_task_projection(repo_root)
    manager = TaskManager(utils.get_journal(repo_root), projection, run_id=utils.make_run_id("hook"))
    asyncio.run(
        manager.update_task(
            task_id,
            {"metadata": dict(updates)},
            updated_by=updated_by,
        )
    )
    TaskExporter(projection, repo_root / ".reins" / "tasks").export_task(task_id)
