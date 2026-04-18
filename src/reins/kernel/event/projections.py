"""Derived read models built directly from journal replay."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.event.journal import EventJournal, TimestampLike, normalize_timestamp
from reins.kernel.event.task_events import (
    TASK_ARCHIVED,
    TASK_COMPLETED,
    TASK_CREATED,
    TASK_STARTED,
    TASK_UPDATED,
)
from reins.task.projection import TaskContextProjection

TASK_EVENT_TYPES = {
    TASK_CREATED,
    TASK_STARTED,
    TASK_COMPLETED,
    TASK_ARCHIVED,
    TASK_UPDATED,
}
AGENT_EVENT_TYPES = {
    "agent.registered",
    "agent.heartbeat_updated",
    "agent.unregistered",
}


@dataclass(frozen=True)
class AgentActivitySummary:
    """Aggregated agent activity for a run/time window."""

    agent_id: str
    event_count: int
    registration_count: int
    heartbeat_count: int
    unregistration_count: int
    first_seen: datetime | None
    last_seen: datetime | None
    active: bool
    last_status: str | None
    task_ids: tuple[str, ...] = ()
    worktree_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskTimelineEntry:
    """One task lifecycle event with the post-event task status."""

    seq: int
    event_type: str
    ts: datetime
    actor: str
    summary: str
    status: str | None
    payload: dict


@dataclass
class TaskTimeline:
    """Ordered task lifecycle history for a single task."""

    run_id: str
    task_id: str
    entries: list[TaskTimelineEntry] = field(default_factory=list)
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    current_status: str | None = None


class EventProjections:
    """Builds derived projections from journal events without mutating state."""

    def __init__(self, journal: EventJournal) -> None:
        self._journal = journal

    async def agent_activity_summary(
        self,
        run_id: str,
        *,
        from_time: TimestampLike | None = None,
        to_time: TimestampLike | None = None,
    ) -> list[AgentActivitySummary]:
        """Aggregate agent registry activity within an optional time window."""
        start = normalize_timestamp(from_time) if from_time is not None else None
        end = normalize_timestamp(to_time) if to_time is not None else None
        summaries: dict[str, dict] = {}

        async for event in self._journal.read_from(run_id):
            if event.type not in AGENT_EVENT_TYPES:
                continue
            if start is not None and event.ts < start:
                continue
            if end is not None and event.ts > end:
                continue

            agent_id = event.payload["agent_id"]
            current = summaries.setdefault(
                agent_id,
                {
                    "event_count": 0,
                    "registration_count": 0,
                    "heartbeat_count": 0,
                    "unregistration_count": 0,
                    "first_seen": None,
                    "last_seen": None,
                    "active": False,
                    "last_status": None,
                    "task_ids": set(),
                    "worktree_ids": set(),
                },
            )

            current["event_count"] += 1
            current["first_seen"] = (
                event.ts
                if current["first_seen"] is None or event.ts < current["first_seen"]
                else current["first_seen"]
            )
            current["last_seen"] = (
                event.ts
                if current["last_seen"] is None or event.ts > current["last_seen"]
                else current["last_seen"]
            )
            if event.payload.get("task_id") is not None:
                current["task_ids"].add(event.payload["task_id"])
            current["worktree_ids"].add(event.payload["worktree_id"])

            if event.type == "agent.registered":
                current["registration_count"] += 1
                current["active"] = True
                current["last_status"] = event.payload.get("status")
            elif event.type == "agent.heartbeat_updated":
                current["heartbeat_count"] += 1
                current["last_status"] = event.payload.get("status")
            elif event.type == "agent.unregistered":
                current["unregistration_count"] += 1
                current["active"] = False
                current["last_status"] = event.payload.get("final_status")

        return [
            AgentActivitySummary(
                agent_id=agent_id,
                event_count=data["event_count"],
                registration_count=data["registration_count"],
                heartbeat_count=data["heartbeat_count"],
                unregistration_count=data["unregistration_count"],
                first_seen=data["first_seen"],
                last_seen=data["last_seen"],
                active=data["active"],
                last_status=data["last_status"],
                task_ids=tuple(sorted(data["task_ids"])),
                worktree_ids=tuple(sorted(data["worktree_ids"])),
            )
            for agent_id, data in sorted(summaries.items())
        ]

    async def task_timeline(
        self,
        run_id: str,
        task_id: str,
        *,
        timestamp: TimestampLike | None = None,
    ) -> TaskTimeline:
        """Project a single task's lifecycle history up to an optional cutoff."""
        projection = TaskContextProjection()
        timeline = TaskTimeline(run_id=run_id, task_id=task_id)

        async for event in self._iter_task_events(run_id, task_id, timestamp=timestamp):
            projection.apply_event(event)
            metadata = projection.get_task(task_id)
            timeline.entries.append(
                TaskTimelineEntry(
                    seq=event.seq,
                    event_type=event.type,
                    ts=event.ts,
                    actor=event.actor.value,
                    summary=_summarize_task_event(event),
                    status=metadata.status.value if metadata is not None else None,
                    payload=event.payload,
                )
            )

        if timeline.entries:
            timeline.first_ts = timeline.entries[0].ts
            timeline.last_ts = timeline.entries[-1].ts
            timeline.current_status = timeline.entries[-1].status

        return timeline

    async def _iter_task_events(
        self,
        run_id: str,
        task_id: str,
        timestamp: TimestampLike | None = None,
    ):
        iterator = (
            self._journal.read_from(run_id)
            if timestamp is None
            else self._journal.read_until(run_id, timestamp=timestamp)
        )
        async for event in iterator:
            if event.type in TASK_EVENT_TYPES and event.payload.get("task_id") == task_id:
                yield event


def _summarize_task_event(event: EventEnvelope) -> str:
    payload = event.payload
    if event.type == TASK_CREATED:
        return f"Created task: {payload.get('title', payload['task_id'])}"
    if event.type == TASK_STARTED:
        return f"Started by {payload.get('assignee', '?')}"
    if event.type == TASK_COMPLETED:
        return f"Completed by {payload.get('completed_by', '?')}"
    if event.type == TASK_ARCHIVED:
        return f"Archived by {payload.get('archived_by', '?')}"
    if event.type == TASK_UPDATED:
        changed = ", ".join(sorted(payload.get("changes", {}).keys()))
        return f"Updated fields: {changed or 'none'}"
    return event.type
