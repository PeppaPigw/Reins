from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from reins.cli import utils
from reins.isolation.agent_registry import AgentRegistry
from reins.isolation.worktree_manager import WorktreeManager
from reins.kernel.intent.envelope import IntentEnvelope
from reins.kernel.reducer.reducer import reduce
from reins.kernel.reducer.state import RunState
from reins.kernel.types import RunStatus
from reins.migration.engine import MigrationEngine
from reins.task.manager import TaskManager
from reins.task.projection import TaskContextProjection
from tests.integration.helpers import (
    assert_event_types_in_order,
    build_orchestrator_bundle,
    create_test_task,
    load_run_events,
    write_worktree_config,
)


def _write_schema(manifest_dir: Path) -> None:
    schema = {
        "type": "object",
        "required": ["version", "migrations"],
        "properties": {
            "version": {"type": "string"},
            "migrations": {"type": "array"},
        },
    }
    (manifest_dir / "schema.json").write_text(json.dumps(schema), encoding="utf-8")


@pytest.mark.asyncio
async def test_event_sourcing_replays_cross_module_state(integration_harness, tmp_path: Path) -> None:
    repo_root = integration_harness.repo_root
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
    (repo_root / ".reins" / ".developer").write_text("peppa\n", encoding="utf-8")
    write_worktree_config(repo_root)

    run_id = "event-sourcing"
    journal = utils.get_journal(repo_root)
    projection = TaskContextProjection()
    task_manager = TaskManager(journal, projection, run_id=run_id)
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
        "Replay task lifecycle",
        journal=journal,
        projection=projection,
        run_id=run_id,
    )
    await task_manager.start_task(task_id, assignee="peppa")

    state = await worktree_manager.create_worktree_for_agent(
        agent_id="agent-1",
        task_id=task_id,
        branch_name=f"feat/{task_id}",
        base_branch=base_branch,
    )

    manifest_dir = tmp_path / "migrations" / "manifests"
    manifest_dir.mkdir(parents=True)
    _write_schema(manifest_dir)
    (repo_root / "legacy.txt").write_text("legacy\n", encoding="utf-8")
    (manifest_dir / "0.1.0.json").write_text(
        json.dumps(
            {
                "version": "0.1.0",
                "migrations": [
                    {
                        "type": "rename",
                        "from_path": "legacy.txt",
                        "to_path": "modern.txt",
                        "description": "Rename legacy file",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    engine = MigrationEngine(
        repo_root=repo_root,
        journal=journal,
        run_id=run_id,
        manifest_dir=manifest_dir,
    )
    await engine.migrate(from_version="0.0.0", to_version="0.1.0")
    await task_manager.complete_task(task_id, outcome={"summary": "finished"})

    replay_projection = TaskContextProjection()
    events = await load_run_events(journal, run_id)
    for event in events:
        replay_projection.apply_event(event)

    live_task = projection.get_task(task_id)
    replayed_task = replay_projection.get_task(task_id)
    assert live_task is not None
    assert replayed_task is not None
    assert replayed_task.status == live_task.status
    assert replayed_task.assignee == live_task.assignee
    assert replayed_task.completed_at == live_task.completed_at

    replayed_worktree_manager = utils.hydrate_worktree_manager(repo_root, run_id)
    replayed_worktree = replayed_worktree_manager.get_worktree(state.worktree_id)
    assert replayed_worktree is not None
    assert replayed_worktree.task_id == task_id
    assert (repo_root / "modern.txt").exists()

    assert_event_types_in_order(
        events,
        [
            "task.created",
            "task.started",
            "worktree.created",
            "agent.registered",
            "migration.started",
            "migration.operation",
            "migration.completed",
            "task.completed",
        ],
    )


@pytest.mark.asyncio
async def test_run_reducer_is_pure_and_replayable(tmp_path: Path) -> None:
    bundle = build_orchestrator_bundle(tmp_path, run_id="reducer-run")
    orchestrator = bundle.orchestrator

    await orchestrator.intake(
        intent=IntentEnvelope(run_id="reducer-run", objective="Verify reducer purity")
    )
    await orchestrator.route()
    await orchestrator.complete()

    events = await load_run_events(bundle.journal, "reducer-run")
    original = RunState(run_id="reducer-run")

    reduced_once = original
    for event in events:
        reduced_once = reduce(reduced_once, event)

    reduced_twice = original
    for event in events:
        reduced_twice = reduce(reduced_twice, event)

    assert original.status == RunStatus.created
    assert reduced_once == reduced_twice
    assert reduced_once.status == RunStatus.completed
