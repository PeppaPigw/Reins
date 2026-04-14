"""Run timeline — reconstructs the observable history of a run from the journal.

The timeline is a read-only projection of the event journal, optimized
for human and tool consumption.  It answers questions like:

  - What happened in this run?
  - Where did it spend time?
  - What failed and why?
  - What approvals are pending?
  - What subagents were spawned?

This is the observability surface.  It never mutates state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.event.journal import EventJournal
from reins.kernel.reducer.reducer import reduce
from reins.kernel.reducer.state import RunState
from reins.kernel.types import RunStatus


@dataclass(frozen=True)
class TimelineEntry:
    """One observable moment in a run's history."""

    seq: int
    event_type: str
    actor: str
    ts: datetime
    summary: str
    payload: dict[str, Any]
    trace_id: str
    command_id: str | None = None
    correlation_id: str | None = None


@dataclass
class RunTimeline:
    """Full reconstructed timeline for a run."""

    run_id: str
    entries: list[TimelineEntry] = field(default_factory=list)
    final_status: RunStatus = RunStatus.created
    event_count: int = 0
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    duration_seconds: float = 0.0
    subagent_ids: list[str] = field(default_factory=list)
    failure_class: str | None = None
    pending_approvals: list[str] = field(default_factory=list)
    repair_state: dict[str, Any] | None = None
    repairing_command_id: str | None = None
    last_completed_repair: dict[str, Any] | None = None


def _summarize_event(event: EventEnvelope) -> str:
    """Generate a human-readable one-line summary of an event."""
    payload = event.payload
    match event.type:
        case "run.started":
            return f"Run started: {payload.get('objective', '?')}"
        case "path.routed":
            return f"Routed to {payload.get('path', '?')} path"
        case "policy.grant_issued":
            return f"Granted {payload.get('capability', '?')} to {payload.get('issued_to', '?')}"
        case "policy.grant_revoked":
            return f"Revoked grant {payload.get('grant_id', '?')}"
        case "adapter.handle_opened":
            return (
                f"Opened {payload.get('adapter_kind', '?')} handle "
                f"{payload.get('handle_id', '?')}"
            )
        case "approval.requested":
            return f"Approval requested: {payload.get('summary', '?')}"
        case "approval.resolved":
            return f"Approval {payload.get('decision', '?')}: {payload.get('approval_id', '?')}"
        case "command.executed":
            return f"Executed command {payload.get('command_id', '?')}"
        case "eval.completed":
            status = "PASS" if payload.get("passed") else "FAIL"
            return f"Eval {status}: {payload.get('details', '')[:80]}"
        case "repair.required":
            return (
                f"Repair required: {payload.get('failure_class', '?')} "
                f"via {payload.get('repair_route', '?')}"
            )
        case "repair.started":
            return f"Repair started by command {payload.get('command_id', '?')}"
        case "repair.finished":
            return f"Repair finished by command {payload.get('command_id', '?')}"
        case "subagent.spawned":
            return f"Spawned subagent for: {payload.get('objective', '?')[:60]}"
        case "subagent.completed":
            return f"Subagent completed ({payload.get('turns_used', '?')} turns)"
        case "subagent.failed":
            return f"Subagent failed: {payload.get('reason', '?')[:60]}"
        case "subagent.aborted":
            return f"Subagent aborted: {payload.get('reason', '?')[:60]}"
        case "run.completed":
            return "Run completed successfully"
        case "run.failed":
            return f"Run failed: {payload.get('failure_class', '?')} — {payload.get('reason', '')[:60]}"
        case "run.aborted":
            return f"Run aborted: {payload.get('reason', '?')[:60]}"
        case "run.dehydrated":
            return f"Run dehydrated → checkpoint {payload.get('checkpoint_id', '?')}"
        case "run.hydrated":
            return "Run hydrated from checkpoint"
        case _:
            return f"{event.type}: {str(payload)[:80]}"


class TimelineBuilder:
    """Reconstructs a RunTimeline from the event journal.

    This is a pure read-only projection — it replays events through the
    reducer to get the final state, and builds a human-readable timeline
    alongside.
    """

    def __init__(self, journal: EventJournal) -> None:
        self._journal = journal

    async def build(self, run_id: str) -> RunTimeline:
        """Reconstruct the full timeline for a run."""
        timeline = RunTimeline(run_id=run_id)
        state = RunState(run_id=run_id)

        async for event in self._journal.read_from(run_id):
            entry = TimelineEntry(
                seq=event.seq,
                event_type=event.type,
                actor=event.actor.value,
                ts=event.ts,
                summary=_summarize_event(event),
                payload=event.payload,
                trace_id=event.trace_id,
                command_id=event.command_id,
                correlation_id=event.correlation_id,
            )
            timeline.entries.append(entry)

            # Track subagent IDs
            if event.type == "subagent.spawned":
                child_id = event.payload.get("child_run_id")
                if child_id:
                    timeline.subagent_ids.append(child_id)

            # Reduce state
            state = reduce(state, event)

        timeline.event_count = len(timeline.entries)
        timeline.final_status = state.status
        timeline.failure_class = (
            state.last_failure_class.value if state.last_failure_class else None
        )
        timeline.pending_approvals = list(state.pending_approvals)
        if state.pending_repair is not None:
            timeline.repair_state = {
                "failure_class": state.pending_repair.failure_class.value,
                "repair_route": state.pending_repair.repair_route,
                "retry_allowed": state.pending_repair.retry_allowed,
                "details": state.pending_repair.details,
                "repair_hints": list(state.pending_repair.repair_hints),
                "command_id": state.pending_repair.command_id,
            }
        timeline.repairing_command_id = state.repairing_command_id
        if state.last_completed_repair is not None:
            timeline.last_completed_repair = {
                "eval_id": state.last_completed_repair.eval_id,
                "command_id": state.last_completed_repair.command_id,
                "failure_class": (
                    state.last_completed_repair.failure_class.value
                    if state.last_completed_repair.failure_class is not None
                    else None
                ),
            }

        if timeline.entries:
            timeline.first_ts = timeline.entries[0].ts
            timeline.last_ts = timeline.entries[-1].ts
            delta = timeline.last_ts - timeline.first_ts
            timeline.duration_seconds = delta.total_seconds()

        return timeline

    async def build_summary(self, run_id: str) -> dict[str, Any]:
        """Build a compact summary dict suitable for the context compiler."""
        tl = await self.build(run_id)
        return {
            "run_id": tl.run_id,
            "status": tl.final_status.value,
            "event_count": tl.event_count,
            "duration_seconds": tl.duration_seconds,
            "failure_class": tl.failure_class,
            "pending_approvals": tl.pending_approvals,
            "repair_state": tl.repair_state,
            "repairing_command_id": tl.repairing_command_id,
            "last_completed_repair": tl.last_completed_repair,
            "subagent_ids": tl.subagent_ids,
            "entries": [
                {"seq": e.seq, "type": e.event_type, "summary": e.summary}
                for e in tl.entries
            ],
        }
