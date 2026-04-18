from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from reins.cli import utils
from reins.isolation.agent_registry import AgentRegistry
from reins.isolation.worktree_manager import WorktreeManager
from reins.kernel.event.builder import EventBuilder
from reins.kernel.event.projections import EventProjections
from reins.kernel.event.time_travel import RunTimeTravel
from reins.kernel.types import RunStatus
from reins.task.manager import TaskManager
from reins.task.metadata import TaskStatus
from reins.task.projection import TaskContextProjection
from tests.integration.helpers import create_test_task, load_run_events, write_worktree_config


@pytest.mark.asyncio
async def test_time_travel_replays_real_task_and_agent_history(
    integration_harness,
    tmp_path: Path,
) -> None:
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

    run_id = "time-travel"
    journal = utils.get_journal(repo_root)
    builder = EventBuilder(journal)
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

    await builder.emit_run_started(run_id, "replay a real event stream")
    await builder.emit_path_routed(run_id, "fast")
    task_id = await create_test_task(
        repo_root,
        "Historical replay task",
        journal=journal,
        projection=projection,
        run_id=run_id,
    )
    await task_manager.start_task(task_id, assignee="peppa")
    worktree_state = await worktree_manager.create_worktree_for_agent(
        agent_id="agent-1",
        task_id=task_id,
        branch_name=f"feat/{task_id}",
        base_branch=base_branch,
    )
    await task_manager.complete_task(task_id, outcome={"summary": "done"})
    await builder.emit_run_completed(run_id)

    events = await load_run_events(journal, run_id)
    task_started_event = next(event for event in events if event.type == "task.started")

    traveler = RunTimeTravel(journal)
    projections = EventProjections(journal)

    live_state = await traveler.reconstruct_run_state(run_id)
    assert live_state.status is RunStatus.completed

    mid_state = await traveler.reconstruct_run_state(run_id, timestamp=task_started_event.ts)
    assert mid_state.status is RunStatus.executing

    historical_task = await traveler.task_state_at(
        run_id,
        task_id,
        timestamp=task_started_event.ts,
    )
    assert historical_task is not None
    assert historical_task.metadata.status is TaskStatus.IN_PROGRESS

    historical_tasks = await traveler.query_tasks(run_id, timestamp=task_started_event.ts)
    assert [task.task_id for task in historical_tasks] == [task_id]
    assert historical_tasks[0].status is TaskStatus.IN_PROGRESS

    timeline = await projections.task_timeline(run_id, task_id)
    assert [entry.event_type for entry in timeline.entries] == [
        "task.created",
        "task.started",
        "task.completed",
    ]
    assert timeline.current_status == TaskStatus.COMPLETED.value

    agent_activity = await projections.agent_activity_summary(run_id)
    assert len(agent_activity) == 1
    assert agent_activity[0].agent_id == "agent-1"
    assert agent_activity[0].registration_count == 1
    assert agent_activity[0].active is True
    assert agent_activity[0].task_ids == (task_id,)
    assert agent_activity[0].worktree_ids == (worktree_state.worktree_id,)
