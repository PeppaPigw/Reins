from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from reins.context.compiler import ContextCompiler
from reins.export.task_exporter import TaskExporter
from reins.isolation.worktree_manager import WorktreeManager
from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.event.journal import EventJournal
from reins.kernel.types import Actor
from reins.orchestration.agent_registry import AgentRegistry as OrchestrationAgentRegistry
from reins.orchestration.hooks import ContextInjectionHook
from reins.orchestration.subagent_manager import SubagentManager as OrchestrationSubagentManager
from reins.task.context_jsonl import ContextJSONL, add_context
from reins.task.manager import TaskManager
from reins.task.projection import TaskContextProjection
from tests.integration.helpers import (
    assert_event_types_in_order,
    ensure_base_specs,
    load_json,
    write_worktree_config,
)


async def _append_event(
    journal: EventJournal,
    *,
    run_id: str,
    event_type: str,
    payload: dict[str, object],
) -> None:
    await journal.append(
        EventEnvelope(
            run_id=run_id,
            actor=Actor.runtime,
            type=event_type,
            payload=payload,
        )
    )


async def _take_events(async_iter, limit: int):
    events = []
    async for event in async_iter:
        events.append(event)
        if len(events) >= limit:
            break
    return events


async def _build_orchestration_fixture(
    repo_root: Path,
    *,
    run_id: str,
    package: str = "auth",
    spec_token_budget: int = 8_000,
    add_large_specs: bool = False,
) -> tuple[
    EventJournal,
    OrchestrationSubagentManager,
    OrchestrationAgentRegistry,
    ContextInjectionHook,
    WorktreeManager,
    str,
    Path,
]:
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo_root, check=True)

    (repo_root / ".reins" / ".developer").write_text("peppa\n", encoding="utf-8")
    (repo_root / ".trellis" / ".developer").write_text("peppa\n", encoding="utf-8")
    write_worktree_config(
        repo_root,
        verify=["test -f .reins/.developer"],
    )
    ensure_base_specs(repo_root, package=package, layers=("commands",))

    if add_large_specs:
        large_content = "Always preserve task context.\n" * 250
        (repo_root / ".reins" / "spec" / package / "commands" / "long-guide.md").write_text(
            f"# Long Guide\n\n{large_content}",
            encoding="utf-8",
        )
        (repo_root / ".reins" / "spec" / "backend" / "deep-rules.md").write_text(
            f"# Deep Rules\n\n{large_content}",
            encoding="utf-8",
        )
        (repo_root / ".reins" / "spec" / "guides" / "long-shared.md").write_text(
            f"# Shared Guide\n\n{large_content}",
            encoding="utf-8",
        )

    journal = EventJournal(repo_root / ".reins" / "journal.jsonl")
    projection = TaskContextProjection()
    task_manager = TaskManager(journal, projection, run_id=run_id)

    task_id = await task_manager.create_task(
        title="Exercise Trellis orchestration path",
        task_type="backend",
        prd_content="Validate orchestration integration for hook, registry, and worktree flow.",
        acceptance_criteria=[
            "Subagent context is injected automatically",
            "Registry state is persisted",
            "Worktree lifecycle is tracked",
        ],
        created_by="tester",
        assignee="peppa",
        metadata={"package": package},
    )

    exporter = TaskExporter(projection, repo_root / ".reins" / "tasks")
    task_dir = exporter.export_task(task_id)
    assert task_dir is not None
    exporter.set_current_task(task_id)

    add_context(
        task_dir,
        "implement",
        "user",
        "Use the task PRD, package rules, and backend guidance.",
        {"source": "integration"},
    )

    worktree_manager = WorktreeManager(
        journal=journal,
        run_id=run_id,
        repo_root=repo_root,
    )
    context_hook = ContextInjectionHook(
        repo_root=repo_root,
        journal=journal,
        context_compiler=ContextCompiler(token_budget=50_000),
        spec_token_budget=spec_token_budget,
    )
    agent_registry = OrchestrationAgentRegistry(
        repo_root=repo_root,
        journal=journal,
    )
    manager = OrchestrationSubagentManager(
        repo_root=repo_root,
        journal=journal,
        worktree_manager=worktree_manager,
        context_hook=context_hook,
        agent_registry=agent_registry,
    )

    return (
        journal,
        manager,
        agent_registry,
        context_hook,
        worktree_manager,
        task_id,
        task_dir,
    )


@pytest.mark.asyncio
async def test_subagent_manager_persists_context_registry_and_worktree_state(
    integration_harness,
) -> None:
    repo_root = integration_harness.repo_root
    run_id = "trellis-subagent-success"
    (
        journal,
        manager,
        agent_registry,
        _context_hook,
        worktree_manager,
        task_id,
        task_dir,
    ) = await _build_orchestration_fixture(repo_root, run_id=run_id)

    handle = await manager.create_subagent(
        agent_type="implement",
        task_id=task_id,
        run_id=run_id,
        use_worktree=True,
    )

    assert handle.context["task_metadata"] is not None
    assert handle.context["task_metadata"]["task_id"] == task_id
    assert handle.context["agent_context"][0]["content"] == (
        "Use the task PRD, package rules, and backend guidance."
    )
    spec_identifiers = {spec["identifier"] for spec in handle.context["specs"]}
    assert "package:auth:index.md" in spec_identifiers
    assert "backend:index.md" in spec_identifiers
    assert "guides:index.md" in spec_identifiers

    assert handle.worktree_state is not None
    assert handle.worktree_state.worktree_path.exists()
    assert (
        handle.worktree_state.worktree_path / ".reins" / "tasks" / task_id / "task.json"
    ).exists()
    assert (
        handle.worktree_state.worktree_path / ".reins" / ".current-task"
    ).read_text(encoding="utf-8").strip() == f"tasks/{task_id}"
    assert (
        handle.worktree_state.worktree_path / ".trellis" / ".current-task"
    ).read_text(encoding="utf-8").strip() == f"tasks/{task_id}"
    assert worktree_manager.get_worktree(handle.worktree_state.worktree_id) is not None

    reopened_registry = OrchestrationAgentRegistry(repo_root=repo_root, journal=journal)
    assert [agent.agent_id for agent in reopened_registry.get_active_agents()] == [
        handle.agent_id
    ]
    assert [agent.agent_id for agent in reopened_registry.get_agents_by_task(task_id)] == [
        handle.agent_id
    ]
    assert [
        agent.agent_id for agent in reopened_registry.get_agents_by_type("implement")
    ] == [handle.agent_id]

    result_task = asyncio.create_task(manager.collect_results(handle, timeout_seconds=1.0))
    await asyncio.sleep(0.05)
    await _append_event(
        journal,
        run_id=run_id,
        event_type="orchestrator.subagent_completed",
        payload={
            "agent_id": handle.agent_id,
            "agent_type": handle.agent_type,
            "output": {
                "status": "completed",
                "summary": "Integrated auth changes and tests",
            },
            "exit_code": 0,
        },
    )
    result = await result_task

    assert result.status == "completed"
    assert result.exit_code == 0
    assert result.output["summary"] == "Integrated auth changes and tests"

    implement_messages = ContextJSONL.read_messages(task_dir / "implement.jsonl")
    assert len(implement_messages) == 2
    assert json.loads(implement_messages[-1].content)["summary"] == (
        "Integrated auth changes and tests"
    )

    task_json = load_json(task_dir / "task.json")
    assert task_json["status"] == "completed"
    assert task_json["completed_at"] is not None

    completed_registry = OrchestrationAgentRegistry(repo_root=repo_root, journal=journal)
    assert completed_registry.get_active_agents() == []
    completed_agents = completed_registry.get_agents_by_task(task_id)
    assert len(completed_agents) == 1
    assert completed_agents[0].status == "completed"
    assert completed_registry.get_registry_stats() == {
        "total_agents": 1,
        "by_status": {"completed": 1},
        "by_type": {"implement": 1},
        "active_count": 0,
    }

    reloaded_hook = ContextInjectionHook(
        repo_root=repo_root,
        journal=journal,
        context_compiler=ContextCompiler(token_budget=50_000),
    )
    reloaded_context = await reloaded_hook.before_subagent_spawn(
        "implement",
        run_id=f"{run_id}-reload",
    )
    assert reloaded_context["task_metadata"]["status"] == "completed"
    assert any(
        json.loads(message["content"]).get("summary") == "Integrated auth changes and tests"
        for message in reloaded_context["agent_context"]
        if message["role"] == "assistant"
    )

    await manager.cleanup(handle)

    assert OrchestrationAgentRegistry(repo_root=repo_root, journal=journal).get_agent(
        handle.agent_id
    ) is None
    assert worktree_manager.get_worktree(handle.worktree_state.worktree_id) is None
    assert not handle.worktree_state.worktree_path.exists()

    events = [event async for event in journal.read_from(run_id)]
    assert_event_types_in_order(
        events,
        [
            "context.injected",
            "worktree.created",
            "agent.registered",
            "agent.status_changed",
            "orchestrator.subagent_spawned",
            "agent.status_changed",
            "context.injected",
            "worktree.removed",
            "agent.cleanup_completed",
            "orchestrator.subagent_cleanup",
        ],
    )


@pytest.mark.asyncio
async def test_subagent_manager_monitor_progress_filters_agent_specific_events(
    integration_harness,
) -> None:
    repo_root = integration_harness.repo_root
    run_id = "trellis-monitor-progress"
    journal, manager, agent_registry, _context_hook, _worktree_manager, task_id, _task_dir = (
        await _build_orchestration_fixture(repo_root, run_id=run_id)
    )

    handle = await manager.create_subagent(
        agent_type="implement",
        task_id=task_id,
        run_id=run_id,
        use_worktree=False,
    )

    consumer = asyncio.create_task(
        asyncio.wait_for(
            _take_events(
                manager.monitor_progress(
                    handle,
                    event_types=["orchestrator.subagent_progress"],
                ),
                limit=1,
            ),
            timeout=1.0,
        )
    )

    await asyncio.sleep(0.05)
    await _append_event(
        journal,
        run_id=run_id,
        event_type="orchestrator.subagent_progress",
        payload={"agent_id": "other-agent", "step": "ignore-other-agent"},
    )
    await _append_event(
        journal,
        run_id=run_id,
        event_type="orchestrator.subagent_completed",
        payload={"agent_id": handle.agent_id, "step": "ignore-other-type"},
    )
    await _append_event(
        journal,
        run_id=run_id,
        event_type="orchestrator.subagent_progress",
        payload={"agent_id": handle.agent_id, "step": "use-this-progress-event"},
    )

    events = await consumer
    assert len(events) == 1
    assert events[0].payload["agent_id"] == handle.agent_id
    assert events[0].payload["step"] == "use-this-progress-event"

    await manager.cleanup(handle, remove_worktree=False)
    assert agent_registry.get_agent(handle.agent_id) is None


@pytest.mark.asyncio
async def test_subagent_manager_timeout_logs_debug_context_and_cleans_up(
    integration_harness,
) -> None:
    repo_root = integration_harness.repo_root
    run_id = "trellis-timeout-recovery"
    (
        journal,
        manager,
        agent_registry,
        _context_hook,
        worktree_manager,
        task_id,
        task_dir,
    ) = await _build_orchestration_fixture(repo_root, run_id=run_id)

    handle = await manager.create_subagent(
        agent_type="implement",
        task_id=task_id,
        run_id=run_id,
        use_worktree=True,
    )

    with pytest.raises(asyncio.TimeoutError):
        await manager.collect_results(handle, timeout_seconds=0.05)

    debug_messages = ContextJSONL.read_messages(task_dir / "debug.jsonl")
    assert len(debug_messages) == 1
    assert "Agent timeout after 0.05s" in debug_messages[0].content
    assert debug_messages[0].metadata["error_type"] == "TimeoutError"

    failed_agent = agent_registry.get_agent(handle.agent_id)
    assert failed_agent is not None
    assert failed_agent.status == "failed"
    assert failed_agent.error_message == "Timeout after 0.05s"
    assert failed_agent.completed_at is not None

    await manager.cleanup(handle)

    assert agent_registry.get_agent(handle.agent_id) is None
    assert worktree_manager.get_worktree(handle.worktree_state.worktree_id) is None
    assert not handle.worktree_state.worktree_path.exists()

    events = [event async for event in journal.read_from(run_id)]
    assert any(event.type == "context.error" for event in events)
    assert any(event.type == "orchestrator.subagent_cleanup" for event in events)


@pytest.mark.asyncio
async def test_context_hook_enforces_spec_token_budget_for_trellis_specs(
    integration_harness,
) -> None:
    repo_root = integration_harness.repo_root
    run_id = "trellis-spec-budget"
    (
        _journal,
        _manager,
        _agent_registry,
        context_hook,
        _worktree_manager,
        _task_id,
        _task_dir,
    ) = await _build_orchestration_fixture(
        repo_root,
        run_id=run_id,
        spec_token_budget=120,
        add_large_specs=True,
    )

    context = await context_hook.before_subagent_spawn(
        "implement",
        run_id=run_id,
    )

    assert context["specs"]
    total_spec_tokens = sum(spec["token_count"] for spec in context["specs"])
    identifiers = {spec["identifier"] for spec in context["specs"]}

    assert total_spec_tokens <= 120
    assert all(identifier.startswith("package:auth:") for identifier in identifiers)
    assert not any(
        identifier.startswith(("backend:", "guides:")) for identifier in identifiers
    )
    assert any("[truncated]" in spec["content"] for spec in context["specs"])
