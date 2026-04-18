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


async def _build_hook_fixture(
    tmp_path: Path,
    *,
    task_type: str = "backend",
    package: str | None = None,
) -> tuple[ContextInjectionHook, EventJournal, Path, str]:
    repo_root = tmp_path
    reins_dir = repo_root / ".reins"
    (reins_dir / "tasks").mkdir(parents=True, exist_ok=True)
    (reins_dir / "spec").mkdir(parents=True, exist_ok=True)

    journal = EventJournal(reins_dir / "journal.jsonl")
    projection = TaskContextProjection()
    manager = TaskManager(journal, projection, run_id="test-run")
    task_id = await manager.create_task(
        title="Context Hook Task",
        task_type=task_type,
        prd_content="Load task metadata and specs into hook context.",
        acceptance_criteria=["Context is injected"],
        created_by="tester",
        priority="P0",
        assignee="peppa",
        metadata={"package": package} if package else None,
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


@pytest.mark.asyncio
async def test_before_subagent_reads_current_task(tmp_path: Path) -> None:
    hook, _journal, _task_dir, task_id = await _build_hook_fixture(tmp_path)

    context = await hook.before_subagent_spawn("implement", run_id="run-read-current")

    assert context["task_metadata"] is not None
    assert context["task_metadata"]["task_id"] == task_id


@pytest.mark.asyncio
async def test_before_subagent_loads_task_json(tmp_path: Path) -> None:
    hook, _journal, _task_dir, task_id = await _build_hook_fixture(tmp_path)

    context = await hook.before_subagent_spawn("implement", run_id="run-load-task")

    assert context["task_metadata"] == {
        "task_id": task_id,
        "title": "Context Hook Task",
        "slug": "context-hook-task",
        "task_type": "backend",
        "priority": "P0",
        "assignee": "peppa",
        "status": "pending",
        "branch": "feat/context-hook-task",
        "base_branch": "main",
        "created_by": "tester",
        "created_at": context["task_metadata"]["created_at"],
        "started_at": None,
        "completed_at": None,
        "parent_task_id": None,
        "metadata": {},
    }


@pytest.mark.asyncio
async def test_before_subagent_reads_agent_jsonl(tmp_path: Path) -> None:
    hook, _journal, task_dir, _task_id = await _build_hook_fixture(tmp_path)
    add_context(
        task_dir,
        "implement",
        "user",
        "Implement the context hook carefully.",
        {"source": "test"},
    )

    context = await hook.before_subagent_spawn("implement", run_id="run-read-agent")

    assert context["agent_context"] == [
        {
            "role": "user",
            "content": "Implement the context hook carefully.",
            "metadata": {"source": "test"},
        }
    ]


@pytest.mark.asyncio
async def test_before_subagent_compiles_specs(tmp_path: Path) -> None:
    hook, _journal, _task_dir, _task_id = await _build_hook_fixture(
        tmp_path,
        task_type="fullstack",
        package="auth",
    )
    spec_root = tmp_path / ".reins" / "spec"
    (spec_root / "backend").mkdir(parents=True, exist_ok=True)
    (spec_root / "frontend").mkdir(parents=True, exist_ok=True)
    (spec_root / "guides").mkdir(parents=True, exist_ok=True)
    (spec_root / "auth" / "commands").mkdir(parents=True, exist_ok=True)
    (spec_root / "backend" / "index.md").write_text("# Backend Rules\n", encoding="utf-8")
    (spec_root / "frontend" / "index.md").write_text("# Frontend Rules\n", encoding="utf-8")
    (spec_root / "guides" / "index.md").write_text("# Guides\n", encoding="utf-8")
    (spec_root / "auth" / "index.md").write_text("# Auth Specifications\n", encoding="utf-8")
    (spec_root / "auth" / "commands" / "index.md").write_text(
        "# Auth / Commands\n",
        encoding="utf-8",
    )

    context = await hook.before_subagent_spawn("implement", run_id="run-specs")

    spec_text = "\n".join(spec["content"] for spec in context["specs"])
    assert "Auth Specifications" in spec_text
    assert "Backend Rules" in spec_text
    assert "Frontend Rules" in spec_text
    assert "Guides" in spec_text


@pytest.mark.asyncio
async def test_after_subagent_appends_result(tmp_path: Path) -> None:
    hook, _journal, task_dir, _task_id = await _build_hook_fixture(tmp_path)

    await hook.after_subagent_complete(
        "implement",
        {"status": "completed", "summary": "Implemented context hooks"},
        run_id="run-after-complete",
    )

    messages = ContextJSONL.read_messages(task_dir / "implement.jsonl")
    assert len(messages) == 1
    assert messages[0].role == "assistant"
    assert json.loads(messages[0].content)["summary"] == "Implemented context hooks"
    assert messages[0].metadata["result"]["status"] == "completed"


@pytest.mark.asyncio
async def test_on_error_appends_to_debug_jsonl(tmp_path: Path) -> None:
    hook, _journal, task_dir, _task_id = await _build_hook_fixture(tmp_path)

    await hook.on_error("implement", ValueError("hook exploded"), run_id="run-on-error")

    messages = ContextJSONL.read_messages(task_dir / "debug.jsonl")
    assert len(messages) == 1
    assert messages[0].role == "system"
    assert messages[0].content == "ValueError: hook exploded"
    assert messages[0].metadata["agent_type"] == "implement"
    assert messages[0].metadata["error_type"] == "ValueError"
