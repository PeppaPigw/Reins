from __future__ import annotations

import json
from pathlib import Path

import pytest

from reins.context.compiler import ContextCompiler
from reins.export import TaskExporter
from reins.kernel.event.journal import EventJournal
from reins.orchestration.hooks import ContextInjectionHook
from reins.task.context_jsonl import ContextJSONL, add_context
from reins.task.manager import TaskManager
from reins.task.projection import TaskContextProjection


async def _create_hooked_task(
    tmp_path: Path,
    *,
    task_type: str = "backend",
) -> tuple[ContextInjectionHook, EventJournal, Path, str]:
    repo_root = tmp_path
    reins_dir = repo_root / ".reins"
    (reins_dir / "tasks").mkdir(parents=True, exist_ok=True)
    (reins_dir / "spec" / "backend").mkdir(parents=True, exist_ok=True)
    (reins_dir / "spec" / "guides").mkdir(parents=True, exist_ok=True)

    journal = EventJournal(reins_dir / "journal.jsonl")
    projection = TaskContextProjection()
    manager = TaskManager(journal, projection, run_id="integration-run")

    task_id = await manager.create_task(
        title="Inject Context",
        task_type=task_type,
        prd_content="Exercise hook integration end to end.",
        acceptance_criteria=["Hooks inject and persist context"],
        created_by="tester",
        priority="P1",
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
    return hook, journal, task_dir, task_id


async def _journal_events(journal: EventJournal, run_id: str) -> list[str]:
    return [event.type async for event in journal.read_from(run_id)]


@pytest.mark.asyncio
async def test_session_start_hook_injects_context(tmp_path: Path) -> None:
    hook, journal, _task_dir, task_id = await _create_hooked_task(tmp_path)
    (tmp_path / ".reins" / "spec" / "backend" / "index.md").write_text(
        "# Backend Rules\n\nRead this first.\n",
        encoding="utf-8",
    )
    (tmp_path / ".reins" / "spec" / "guides" / "index.md").write_text(
        "# Guides\n\nShared guidance.\n",
        encoding="utf-8",
    )

    context = await hook.before_subagent_spawn("implement", run_id="session-start-run")

    assert context["task_metadata"] is not None
    assert context["task_metadata"]["task_id"] == task_id
    assert len(context["specs"]) == 2

    event_types = await _journal_events(journal, "session-start-run")
    assert "context.injected" in event_types


@pytest.mark.asyncio
async def test_before_subagent_hook_full_flow(tmp_path: Path) -> None:
    hook, journal, task_dir, _task_id = await _create_hooked_task(tmp_path)
    add_context(task_dir, "implement", "user", "Use the injected task context.", {"source": "test"})
    (tmp_path / ".reins" / "spec" / "backend" / "index.md").write_text(
        "# Backend Rules\n",
        encoding="utf-8",
    )
    (tmp_path / ".reins" / "spec" / "guides" / "index.md").write_text(
        "# Guides\n",
        encoding="utf-8",
    )

    context = await hook.before_subagent_spawn("implement", run_id="before-subagent-run")

    assert [entry["content"] for entry in context["agent_context"]] == [
        "Use the injected task context."
    ]
    spec_identifiers = {spec["identifier"] for spec in context["specs"]}
    assert spec_identifiers == {"backend:index.md", "guides:index.md"}

    event_types = await _journal_events(journal, "before-subagent-run")
    assert event_types == ["context.injected"]


@pytest.mark.asyncio
async def test_after_subagent_hook_updates_context(tmp_path: Path) -> None:
    hook, journal, task_dir, _task_id = await _create_hooked_task(tmp_path)

    await hook.after_subagent_complete(
        "implement",
        {"status": "completed", "summary": "Done"},
        run_id="after-subagent-run",
    )

    messages = ContextJSONL.read_messages(task_dir / "implement.jsonl")
    assert len(messages) == 1
    assert json.loads(messages[0].content)["summary"] == "Done"

    task_json = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    assert task_json["status"] == "completed"
    assert task_json["completed_at"] is not None

    event_types = await _journal_events(journal, "after-subagent-run")
    assert event_types == ["context.injected"]
