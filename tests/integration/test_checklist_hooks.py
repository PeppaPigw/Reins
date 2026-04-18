from __future__ import annotations

import json
from pathlib import Path

import pytest

from reins.context.compiler import ContextCompiler
from reins.export import TaskExporter
from reins.kernel.event.journal import EventJournal
from reins.orchestration.hooks import ContextInjectionHook
from reins.task.manager import TaskManager
from reins.task.projection import TaskContextProjection


@pytest.mark.asyncio
async def test_checklist_hook_persists_status_and_emits_warning(tmp_path: Path) -> None:
    repo_root = tmp_path
    reins_dir = repo_root / ".reins"
    (reins_dir / "tasks").mkdir(parents=True, exist_ok=True)
    (reins_dir / "spec" / "backend").mkdir(parents=True, exist_ok=True)
    (reins_dir / "spec" / "backend" / "index.md").write_text(
        "# Backend Specifications\n\n"
        "## Pre-Development Checklist\n\n"
        "- [ ] [Missing Guide](missing.md) - This file does not exist\n",
        encoding="utf-8",
    )

    journal = EventJournal(reins_dir / "journal.jsonl")
    projection = TaskContextProjection()
    manager = TaskManager(journal, projection, run_id="checklist-hook-run")
    task_id = await manager.create_task(
        title="Checklist hook task",
        task_type="backend",
        prd_content="Persist checklist status.",
        acceptance_criteria=["Checklist tracked"],
        created_by="tester",
        assignee="peppa",
    )
    exporter = TaskExporter(projection, reins_dir / "tasks")
    task_dir = exporter.export_task(task_id)
    assert task_dir is not None
    exporter.set_current_task(task_id)

    hook = ContextInjectionHook(
        repo_root=repo_root,
        journal=journal,
        context_compiler=ContextCompiler(token_budget=1_500),
    )
    context = await hook.before_subagent_spawn("implement", run_id="checklist-hook-run")

    assert context["checklist"] is not None
    assert context["checklist"]["complete"] is False
    assert context["checklist"]["missing_files"] == ["missing.md"]

    task_json = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    assert task_json["metadata"]["checklist"]["missing_files"] == ["missing.md"]

    event_types = [event.type async for event in journal.read_from("checklist-hook-run")]
    assert "checklist.incomplete" in event_types
