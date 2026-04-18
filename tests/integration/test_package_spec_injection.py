from __future__ import annotations

from pathlib import Path

import pytest

from reins.context.compiler import ContextCompiler
from reins.export import TaskExporter
from reins.kernel.event.journal import EventJournal
from reins.orchestration.hooks import ContextInjectionHook
from reins.task.manager import TaskManager
from reins.task.projection import TaskContextProjection


@pytest.mark.asyncio
async def test_package_spec_injection_prefers_package_layer(tmp_path: Path) -> None:
    repo_root = tmp_path
    spec_root = repo_root / ".reins" / "spec"
    (spec_root / "auth" / "backend").mkdir(parents=True, exist_ok=True)
    (spec_root / "backend").mkdir(parents=True, exist_ok=True)
    (spec_root / "guides").mkdir(parents=True, exist_ok=True)
    (spec_root / "auth" / "backend" / "index.md").write_text("# Auth Backend\n", encoding="utf-8")
    (spec_root / "backend" / "index.md").write_text("# Global Backend\n", encoding="utf-8")
    (spec_root / "guides" / "index.md").write_text("# Shared Guides\n", encoding="utf-8")
    (repo_root / ".reins" / "tasks").mkdir(parents=True, exist_ok=True)

    journal = EventJournal(repo_root / ".reins" / "journal.jsonl")
    projection = TaskContextProjection()
    manager = TaskManager(journal, projection, run_id="package-spec-run")
    task_id = await manager.create_task(
        title="Package spec task",
        task_type="backend",
        prd_content="Prefer package specs.",
        acceptance_criteria=["Package specs injected first"],
        created_by="tester",
        assignee="peppa",
        metadata={"package": "auth"},
    )
    exporter = TaskExporter(projection, repo_root / ".reins" / "tasks")
    exporter.export_task(task_id)
    exporter.set_current_task(task_id)

    hook = ContextInjectionHook(
        repo_root=repo_root,
        journal=journal,
        context_compiler=ContextCompiler(token_budget=1_500),
    )
    context = await hook.before_subagent_spawn("implement", run_id="package-spec-run")

    identifiers = [spec["identifier"] for spec in context["specs"]]
    assert identifiers[:3] == [
        "package:auth:backend:index.md",
        "backend:index.md",
        "guides:index.md",
    ]
    assert context["specs"][0]["content"].startswith("# Auth Backend")
