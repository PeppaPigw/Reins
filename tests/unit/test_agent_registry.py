from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from reins.isolation.agent_registry import AgentRegistry, AgentRegistryRecord
from reins.kernel.event.journal import EventJournal


@pytest.mark.asyncio
async def test_register_persists_and_queries(tmp_path: Path) -> None:
    journal = EventJournal(tmp_path / "journal.jsonl")
    registry_path = tmp_path / ".reins" / "registry.json"
    registry = AgentRegistry(
        path=registry_path,
        journal=journal,
        run_id="run-1",
    )

    record = await registry.register(
        agent_id="agent-1",
        worktree_id="worktree-1",
        task_id="task-1",
        status="running",
    )

    assert record.agent_id == "agent-1"
    assert registry_path.exists()

    reopened = AgentRegistry(
        path=registry_path,
        journal=journal,
        run_id="run-1",
    )
    loaded = await reopened.get("agent-1")
    assert loaded is not None
    assert loaded.worktree_id == "worktree-1"
    assert [item.agent_id for item in await reopened.list_by_status("running")] == [
        "agent-1"
    ]
    assert [item.agent_id for item in await reopened.list_by_task("task-1")] == [
        "agent-1"
    ]


@pytest.mark.asyncio
async def test_heartbeat_updates_timestamp_and_status(tmp_path: Path) -> None:
    journal = EventJournal(tmp_path / "journal.jsonl")
    registry = AgentRegistry(
        path=tmp_path / ".reins" / "registry.json",
        journal=journal,
        run_id="run-1",
    )

    await registry.register(
        agent_id="agent-1",
        worktree_id="worktree-1",
        task_id="task-1",
        status="running",
    )
    before = await registry.get("agent-1")
    assert before is not None

    updated = await registry.heartbeat("agent-1", status="verifying")
    assert updated is not None
    assert updated.status == "verifying"
    assert updated.last_heartbeat >= before.last_heartbeat


@pytest.mark.asyncio
async def test_unregister_removes_record(tmp_path: Path) -> None:
    journal = EventJournal(tmp_path / "journal.jsonl")
    registry = AgentRegistry(
        path=tmp_path / ".reins" / "registry.json",
        journal=journal,
        run_id="run-1",
    )

    await registry.register(
        agent_id="agent-1",
        worktree_id="worktree-1",
        task_id="task-1",
        status="running",
    )

    removed = await registry.unregister("agent-1", final_status="completed")

    assert removed is not None
    assert await registry.get("agent-1") is None
    assert await registry.list_by_status("running") == []


def test_agent_registry_record_round_trip() -> None:
    timestamp = datetime.now(UTC)
    record = AgentRegistryRecord(
        agent_id="agent-1",
        worktree_id="worktree-1",
        task_id="task-1",
        status="running",
        started_at=timestamp,
        last_heartbeat=timestamp,
    )

    loaded = AgentRegistryRecord.from_dict(record.to_dict())

    assert loaded == record
