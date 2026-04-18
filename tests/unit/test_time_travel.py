from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.event.journal import EventJournal, normalize_timestamp
from reins.kernel.event.projections import EventProjections
from reins.kernel.event.task_events import TASK_COMPLETED, TASK_CREATED, TASK_STARTED
from reins.kernel.event.time_travel import RunTimeTravel
from reins.kernel.types import Actor, RunStatus
from reins.task.metadata import TaskStatus


def _ts(seconds: int) -> datetime:
    return datetime(2026, 4, 18, 10, 0, tzinfo=UTC) + timedelta(seconds=seconds)


def _event(
    run_id: str,
    event_type: str,
    payload: dict,
    *,
    ts: datetime,
    actor: Actor = Actor.runtime,
) -> EventEnvelope:
    return EventEnvelope(
        run_id=run_id,
        actor=actor,
        type=event_type,
        payload=payload,
        ts=ts,
    )


@pytest.mark.asyncio
async def test_run_time_travel_reconstructs_state_at_timestamp(tmp_path) -> None:
    journal = EventJournal(tmp_path / "events.jsonl")
    run_id = "run-1"

    await journal.append(_event(run_id, "run.started", {"objective": "ship"}, ts=_ts(0)))
    await journal.append(_event(run_id, "path.routed", {"path": "fast"}, ts=_ts(1)))
    await journal.append(
        _event(
            run_id,
            "approval.requested",
            {"approval_id": "ap-1", "summary": "deploy"},
            ts=_ts(2),
            actor=Actor.policy,
        )
    )
    await journal.append(
        _event(
            run_id,
            "approval.resolved",
            {"approval_id": "ap-1", "decision": "approved"},
            ts=_ts(3),
            actor=Actor.human,
        )
    )
    await journal.append(_event(run_id, "run.completed", {}, ts=_ts(4)))

    traveler = RunTimeTravel(journal)

    waiting = await traveler.reconstruct_at(
        run_id,
        timestamp="2026-04-18T10:00:02Z",
    )
    assert waiting.status is RunStatus.waiting_approval
    assert waiting.pending_approvals == ["ap-1"]

    resumed = await traveler.reconstruct_run_state(run_id, timestamp=_ts(3))
    assert resumed.status is RunStatus.resumable
    assert resumed.pending_approvals == []

    final = await traveler.reconstruct_run_state(run_id)
    assert final.status is RunStatus.completed


@pytest.mark.asyncio
async def test_run_time_travel_queries_historical_task_state(tmp_path) -> None:
    journal = EventJournal(tmp_path / "events.jsonl")
    run_id = "run-2"
    task_id = "04-18-historical-task"

    await journal.append(
        _event(
            run_id,
            TASK_CREATED,
            {
                "task_id": task_id,
                "title": "Historical task",
                "slug": "historical-task",
                "task_type": "backend",
                "prd_content": "Build historical replay",
                "acceptance_criteria": ["Replay task state"],
                "priority": "P1",
                "assignee": "peppa",
                "branch": "feat/historical-task",
                "base_branch": "main",
                "created_by": "test",
                "created_at": _ts(0).isoformat(),
                "parent_task_id": None,
                "metadata": {"component": "event-sourcing"},
            },
            ts=_ts(0),
        )
    )
    await journal.append(
        _event(
            run_id,
            TASK_STARTED,
            {"task_id": task_id, "assignee": "peppa", "started_at": _ts(1).isoformat()},
            ts=_ts(1),
        )
    )
    await journal.append(
        _event(
            run_id,
            TASK_COMPLETED,
            {
                "task_id": task_id,
                "completed_at": _ts(2).isoformat(),
                "outcome": {"summary": "done"},
                "completed_by": "system",
            },
            ts=_ts(2),
        )
    )

    traveler = RunTimeTravel(journal)

    mid_context = await traveler.task_state_at(run_id, task_id, timestamp=_ts(1))
    assert mid_context is not None
    assert mid_context.metadata.status is TaskStatus.IN_PROGRESS
    assert len(mid_context.events) == 2

    mid_tasks = await traveler.query_tasks(run_id, timestamp=_ts(1))
    assert len(mid_tasks) == 1
    assert mid_tasks[0].status is TaskStatus.IN_PROGRESS

    final_events = await traveler.task_events_at(run_id, task_id)
    assert [event.type for event in final_events] == [
        TASK_CREATED,
        TASK_STARTED,
        TASK_COMPLETED,
    ]


@pytest.mark.asyncio
async def test_derived_projections_build_agent_summary_and_task_timeline(tmp_path) -> None:
    journal = EventJournal(tmp_path / "events.jsonl")
    run_id = "run-3"
    task_id = "04-18-timeline-task"

    await journal.append(
        _event(
            run_id,
            TASK_CREATED,
            {
                "task_id": task_id,
                "title": "Timeline task",
                "slug": "timeline-task",
                "task_type": "backend",
                "prd_content": "Track timeline",
                "acceptance_criteria": [],
                "priority": "P1",
                "assignee": "peppa",
                "branch": "feat/timeline-task",
                "base_branch": "main",
                "created_by": "test",
                "created_at": _ts(0).isoformat(),
                "parent_task_id": None,
                "metadata": {},
            },
            ts=_ts(0),
        )
    )
    await journal.append(
        _event(
            run_id,
            TASK_STARTED,
            {"task_id": task_id, "assignee": "peppa", "started_at": _ts(1).isoformat()},
            ts=_ts(1),
        )
    )
    await journal.append(
        _event(
            run_id,
            "agent.registered",
            {
                "agent_id": "agent-1",
                "worktree_id": "wt-1",
                "task_id": task_id,
                "status": "running",
                "started_at": _ts(1).isoformat(),
                "last_heartbeat": _ts(1).isoformat(),
            },
            ts=_ts(1),
        )
    )
    await journal.append(
        _event(
            run_id,
            "agent.heartbeat_updated",
            {
                "agent_id": "agent-1",
                "worktree_id": "wt-1",
                "task_id": task_id,
                "status": "running",
                "last_heartbeat": _ts(2).isoformat(),
            },
            ts=_ts(2),
        )
    )
    await journal.append(
        _event(
            run_id,
            "agent.unregistered",
            {
                "agent_id": "agent-1",
                "worktree_id": "wt-1",
                "task_id": task_id,
                "final_status": "completed",
                "unregistered_at": _ts(3).isoformat(),
            },
            ts=_ts(3),
        )
    )
    await journal.append(
        _event(
            run_id,
            TASK_COMPLETED,
            {
                "task_id": task_id,
                "completed_at": _ts(4).isoformat(),
                "outcome": {"summary": "done"},
                "completed_by": "system",
            },
            ts=_ts(4),
        )
    )

    projections = EventProjections(journal)

    timeline = await projections.task_timeline(run_id, task_id)
    assert [entry.event_type for entry in timeline.entries] == [
        TASK_CREATED,
        TASK_STARTED,
        TASK_COMPLETED,
    ]
    assert [entry.status for entry in timeline.entries] == [
        TaskStatus.PENDING.value,
        TaskStatus.IN_PROGRESS.value,
        TaskStatus.COMPLETED.value,
    ]
    assert timeline.current_status == TaskStatus.COMPLETED.value

    summary = await projections.agent_activity_summary(
        run_id,
        from_time=_ts(1),
        to_time="2026-04-18T10:00:03Z",
    )
    assert len(summary) == 1
    assert summary[0] == summary[0]  # dataclass equality smoke check
    assert summary[0].agent_id == "agent-1"
    assert summary[0].event_count == 3
    assert summary[0].registration_count == 1
    assert summary[0].heartbeat_count == 1
    assert summary[0].unregistration_count == 1
    assert summary[0].active is False
    assert summary[0].last_status == "completed"
    assert summary[0].task_ids == (task_id,)
    assert summary[0].worktree_ids == ("wt-1",)

    assert normalize_timestamp("2026-04-18T10:00:03Z") == _ts(3)
