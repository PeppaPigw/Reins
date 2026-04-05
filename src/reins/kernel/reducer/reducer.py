from __future__ import annotations

from dataclasses import replace

from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.reducer.state import RunState
from reins.kernel.types import FailureClass, GrantRef, PathKind, RunStatus

REDUCER_VERSION = "0.1.0"


def _grant_from_payload(payload: dict) -> GrantRef:
    return GrantRef(
        grant_id=payload["grant_id"],
        capability=payload["capability"],
        scope=payload["scope"],
        issued_to=payload["issued_to"],
        ttl_seconds=payload["ttl_seconds"],
        approval_hash=payload.get("approval_hash"),
        inherited=payload.get("inherited", False),
    )


def reduce(state: RunState, event: EventEnvelope) -> RunState:
    """Pure reducer. Returns new state from current state + event. No I/O."""
    active_grants = list(state.active_grants)
    pending = list(state.pending_approvals)

    if event.type == "run.started":
        return replace(state, status=RunStatus.routing)
    if event.type == "path.routed":
        path = PathKind(event.payload["path"])
        return replace(
            state,
            status=RunStatus.executing if path is PathKind.fast else RunStatus.planning,
        )
    if event.type == "policy.grant_issued":
        active_grants.append(_grant_from_payload(event.payload))
        return replace(state, active_grants=active_grants)
    if event.type == "policy.grant_revoked":
        grant_id = event.payload["grant_id"]
        active_grants = [grant for grant in active_grants if grant.grant_id != grant_id]
        return replace(state, active_grants=active_grants)
    if event.type == "approval.requested":
        pending.append(event.payload["approval_id"])
        return replace(state, pending_approvals=pending, status=RunStatus.waiting_approval)
    if event.type == "approval.resolved":
        approval_id = event.payload["approval_id"]
        pending = [item for item in pending if item != approval_id]
        status = RunStatus.resumable if not pending else state.status
        return replace(state, pending_approvals=pending, status=status)
    if event.type == "run.dehydrated":
        return replace(
            state,
            status=RunStatus.dehydrated,
            last_checkpoint_id=event.payload.get("checkpoint_id"),
        )
    if event.type == "run.hydrated":
        return replace(state, status=RunStatus.resumable)
    if event.type == "run.completed":
        return replace(state, status=RunStatus.completed)
    if event.type == "run.aborted":
        return replace(state, status=RunStatus.aborted)
    if event.type == "run.failed":
        failure = FailureClass(event.payload["failure_class"])
        return replace(state, status=RunStatus.failed, last_failure_class=failure)
    return replace(state)
