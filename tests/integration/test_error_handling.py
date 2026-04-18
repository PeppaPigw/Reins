from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from reins.cli import utils
from reins.isolation.agent_registry import AgentRegistry
from reins.isolation.worktree_manager import WorktreeError, WorktreeManager
from reins.kernel.event.journal import EventJournal
from reins.migration.engine import MigrationEngine
from reins.task.context_jsonl import ContextJSONL
from reins.task.manager import TaskManager
from reins.task.projection import TaskContextProjection
from tests.integration.helpers import create_test_task, load_run_events, write_worktree_config


def _write_schema(manifest_dir: Path) -> None:
    (manifest_dir / "schema.json").write_text(
        json.dumps({"type": "object", "required": ["version", "migrations"]}),
        encoding="utf-8",
    )


def _write_manifest(manifest_dir: Path, version: str, migrations: list[dict[str, object]]) -> None:
    (manifest_dir / f"{version}.json").write_text(
        json.dumps({"version": version, "migrations": migrations}, indent=2),
        encoding="utf-8",
    )


def test_cli_errors_are_audited_and_do_not_corrupt_state(integration_harness) -> None:
    missing_start = integration_harness.invoke(["task", "start", "missing-task"])
    assert missing_start.exit_code == 1

    missing_context = integration_harness.invoke(["task", "init-context", "missing-task", "backend"])
    assert missing_context.exit_code == 1

    invalid_add = integration_harness.invoke(["task", "add-context", "missing-task", "implement", str(integration_harness.repo_root)])
    assert invalid_add.exit_code == 1

    error_events = integration_harness.load_events(event_type="cli.error")
    commands = {event.payload["command"] for event in error_events}
    assert commands == {"task.start", "task.init-context", "task.add-context"}
    assert integration_harness.current_task_id() is None


def test_context_validation_and_corrupted_journal_are_actionable(tmp_path: Path) -> None:
    context_path = tmp_path / "implement.jsonl"
    context_path.write_text('{"role":"system","content":"ok"}\nnot-json\n', encoding="utf-8")
    valid, errors = ContextJSONL.validate_jsonl(context_path)
    assert valid is False
    assert errors and "Line 2: invalid JSON" in errors[0]
    assert len(ContextJSONL.read_messages(context_path)) == 1

    journal_path = tmp_path / "journal.jsonl"
    journal_path.write_text('{"run_id":"broken","seq":1}\nnot-json\n', encoding="utf-8")
    journal = EventJournal(journal_path)
    with pytest.raises(Exception):
        asyncio.run(load_run_events(journal, "broken"))


@pytest.mark.asyncio
async def test_manager_failures_leave_consistent_state(integration_harness, tmp_path: Path) -> None:
    repo_root = integration_harness.repo_root
    (repo_root / ".reins" / ".developer").write_text("peppa\n", encoding="utf-8")
    write_worktree_config(
        repo_root,
        post_create=["python -c \"raise SystemExit(1)\""],
        verify=["test -f .reins/.developer"],
    )
    base_branch = (
        subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
    )

    run_id = "error-handling"
    journal = utils.get_journal(repo_root)
    projection = TaskContextProjection()
    TaskManager(journal, projection, run_id=run_id)
    registry = AgentRegistry(
        path=repo_root / ".reins" / "registry.json",
        journal=journal,
        run_id=run_id,
    )
    worktree_manager = WorktreeManager(
        journal=journal,
        run_id=run_id,
        repo_root=repo_root,
        agent_registry=registry,
    )
    task_id = await create_test_task(
        repo_root,
        "Broken worktree",
        journal=journal,
        projection=projection,
        run_id=run_id,
    )

    with pytest.raises(WorktreeError):
        await worktree_manager.create_worktree_for_agent(
            agent_id="agent-broken",
            task_id=task_id,
            branch_name=f"feat/{task_id}",
            base_branch=base_branch,
        )

    assert worktree_manager.list_worktrees() == []
    assert await registry.list_all() == []

    manifest_dir = tmp_path / "migrations" / "manifests"
    manifest_dir.mkdir(parents=True)
    _write_schema(manifest_dir)
    (repo_root / "alpha.txt").write_text("alpha\n", encoding="utf-8")
    (repo_root / "beta.txt").write_text("beta\n", encoding="utf-8")
    _write_manifest(
        manifest_dir,
        "0.1.0",
        [
            {
                "type": "rename",
                "from_path": "alpha.txt",
                "to_path": "gamma.txt",
                "description": "Rename alpha to gamma",
            },
            {
                "type": "rename",
                "from_path": "beta.txt",
                "to_path": "gamma.txt",
                "description": "Conflicting rename should fail",
            },
        ],
    )
    engine = MigrationEngine(
        repo_root=repo_root,
        journal=journal,
        run_id=run_id,
        manifest_dir=manifest_dir,
    )
    with pytest.raises(Exception):
        await engine.migrate(from_version="0.0.0", to_version="0.1.0")

    assert (repo_root / "alpha.txt").exists()
    assert (repo_root / "beta.txt").exists()
    assert not (repo_root / "gamma.txt").exists()

    first = await registry.register(
        agent_id="agent-1",
        worktree_id="wt-1",
        task_id="task-1",
        status="running",
    )
    second = await registry.register(
        agent_id="agent-1",
        worktree_id="wt-2",
        task_id="task-2",
        status="running",
    )
    record = await registry.get("agent-1")
    assert first.worktree_id == "wt-1"
    assert second.worktree_id == "wt-2"
    assert record is not None
    assert record.worktree_id == "wt-2"

    registry_json = json.loads((repo_root / ".reins" / "registry.json").read_text(encoding="utf-8"))
    assert len(registry_json["agents"]) == 1
    assert registry_json["agents"][0]["worktree_id"] == "wt-2"

    events = await load_run_events(journal, run_id)
    assert any(event.type == "migration.failed" for event in events)
    assert sum(1 for event in events if event.type == "agent.registered") >= 2
