from __future__ import annotations

import asyncio
import subprocess

import pytest

from reins.cli import utils
from reins.export.task_exporter import TaskExporter
from reins.isolation.agent_registry import AgentRegistry
from reins.isolation.worktree_manager import WorktreeManager
from reins.task.context_jsonl import ContextJSONL, ContextMessage
from reins.task.manager import TaskManager
from reins.task.projection import TaskContextProjection
from tests.integration.helpers import (
    assert_event_types_in_order,
    load_run_events,
    simulate_agent_work,
    write_worktree_config,
)


@pytest.mark.asyncio
async def test_multi_agent_coordination_integration(integration_harness) -> None:
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

    run_id = "multi-agent"
    journal = utils.get_journal(repo_root)
    projection = TaskContextProjection()
    manager = TaskManager(journal, projection, run_id=run_id)
    exporter = TaskExporter(projection, repo_root / ".reins" / "tasks")
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

    parent_task_id = await manager.create_task(
        title="Parent integration task",
        task_type="backend",
        prd_content="Coordinate multiple agents.",
        acceptance_criteria=["Agents stay isolated"],
        created_by="test",
        assignee="peppa",
    )
    exporter.export_task(parent_task_id)

    subtask_ids: list[str] = []
    for idx in range(3):
        task_id = await manager.create_task(
            title=f"Subtask {idx + 1}",
            task_type="backend",
            prd_content=f"Work item {idx + 1}",
            acceptance_criteria=["done"],
            created_by="test",
            assignee=f"agent-{idx + 1}",
            parent_task_id=parent_task_id,
        )
        exporter.export_task(task_id)
        ContextJSONL.write_message(
            repo_root / ".reins" / "tasks" / task_id / "implement.jsonl",
            ContextMessage(
                role="system",
                content=f"Context for {task_id}",
                metadata={"task_id": task_id},
            ),
        )
        subtask_ids.append(task_id)

    states = await asyncio.gather(
        *[
            worktree_manager.create_worktree_for_agent(
                agent_id=f"agent-{idx + 1}",
                task_id=task_id,
                branch_name=f"feat/{task_id}",
                base_branch=base_branch,
            )
            for idx, task_id in enumerate(subtask_ids)
        ]
    )

    for idx, state in enumerate(states):
        context_path = state.worktree_path / ".reins" / "tasks" / subtask_ids[idx] / "implement.jsonl"
        messages = ContextJSONL.read_messages(context_path)
        assert messages[0].metadata["task_id"] == subtask_ids[idx]

    outputs = await asyncio.gather(
        *[
            simulate_agent_work(
                state.worktree_path,
                file_name=f"agent-{idx + 1}/result.txt",
                content=f"agent-{idx + 1}",
            )
            for idx, state in enumerate(states)
        ],
        *[
            registry.heartbeat(f"agent-{idx + 1}", status="running")
            for idx in range(3)
        ],
    )
    assert len(outputs) == 6
    assert len(await registry.list_by_status("running")) == 3

    failed_state = states[0]
    await registry.heartbeat("agent-1", status="failed")
    await worktree_manager.cleanup_agent_worktree(
        failed_state.worktree_id,
        force=True,
        removed_by="test",
        reason="simulated failure",
    )

    await asyncio.gather(
        simulate_agent_work(states[1].worktree_path, file_name="agent-2/continued.txt", content="ok"),
        simulate_agent_work(states[2].worktree_path, file_name="agent-3/continued.txt", content="ok"),
        registry.heartbeat("agent-2", status="running"),
        registry.heartbeat("agent-3", status="running"),
    )

    assert await registry.get("agent-1") is None
    assert await registry.get("agent-2") is not None
    assert await registry.get("agent-3") is not None
    assert not failed_state.worktree_path.exists()
    assert (states[1].worktree_path / "agent-2" / "continued.txt").exists()
    assert (states[2].worktree_path / "agent-3" / "continued.txt").exists()
    assert not (states[1].worktree_path / "agent-1" / "result.txt").exists()
    assert not (states[2].worktree_path / "agent-1" / "result.txt").exists()

    await asyncio.gather(
        worktree_manager.cleanup_agent_worktree(states[1].worktree_id, force=True, removed_by="test"),
        worktree_manager.cleanup_agent_worktree(states[2].worktree_id, force=True, removed_by="test"),
    )

    assert await registry.list_all() == []
    assert worktree_manager.list_worktrees() == []

    events = await load_run_events(journal, run_id)
    assert_event_types_in_order(
        events,
        [
            "task.created",
            "worktree.created",
            "agent.registered",
            "agent.heartbeat_updated",
            "worktree.removed",
            "agent.unregistered",
        ],
    )
    assert sum(1 for event in events if event.type == "agent.heartbeat_updated") >= 5
