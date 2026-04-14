from __future__ import annotations

from dataclasses import replace

from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.reducer.state import CompletedRepair, PendingRepair, RunState
from reins.kernel.types import FailureClass, GrantRef, HandleRef, PathKind, RunStatus

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


def _handle_from_payload(payload: dict) -> HandleRef:
    return HandleRef(
        handle_id=payload["handle_id"],
        adapter_kind=payload["adapter_kind"],
        adapter_id=payload["adapter_id"],
    )


def reduce(state: RunState, event: EventEnvelope) -> RunState:
    """Pure reducer. Returns new state from current state + event. No I/O."""
    active_grants = list(state.active_grants)
    open_handles = list(state.open_handles)
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
    if event.type == "adapter.handle_opened":
        handle = _handle_from_payload(event.payload)
        if all(existing.handle_id != handle.handle_id for existing in open_handles):
            open_handles.append(handle)
        return replace(state, open_handles=open_handles)
    if event.type == "eval.completed":
        if not event.payload.get("passed", False) and event.payload.get("failure_class"):
            failure = FailureClass(event.payload["failure_class"])
            return replace(state, last_failure_class=failure, repairing_command_id=None)
        return replace(state)
    if event.type == "repair.required":
        failure = FailureClass(event.payload["failure_class"])
        pending_repair = PendingRepair(
            eval_id=event.payload["eval_id"],
            failure_class=failure,
            repair_route=event.payload["repair_route"],
            retry_allowed=bool(event.payload["retry_allowed"]),
            details=event.payload.get("details", ""),
            repair_hints=list(event.payload.get("repair_hints", [])),
            command_id=event.payload.get("command_id"),
        )
        return replace(
            state,
            status=RunStatus.resumable,
            last_failure_class=failure,
            pending_repair=pending_repair,
            repairing_command_id=None,
        )
    if event.type == "repair.started":
        return replace(
            state,
            status=RunStatus.executing,
            pending_repair=None,
            repairing_command_id=event.payload["command_id"],
        )
    if event.type == "repair.finished":
        failure_class = (
            FailureClass(event.payload["resolved_failure_class"])
            if event.payload.get("resolved_failure_class") is not None
            else None
        )
        return replace(
            state,
            last_failure_class=None,
            pending_repair=None,
            repairing_command_id=None,
            last_completed_repair=CompletedRepair(
                eval_id=event.payload["eval_id"],
                command_id=event.payload["command_id"],
                failure_class=failure_class,
            ),
        )
    if event.type == "approval.requested":
        pending.append(event.payload["approval_id"])
        return replace(state, pending_approvals=pending, status=RunStatus.waiting_approval)
    if event.type == "approval.resolved":
        approval_id = event.payload["approval_id"]
        pending = [item for item in pending if item != approval_id]
        status = RunStatus.resumable if not pending else state.status
        return replace(state, pending_approvals=pending, status=status)
    if event.type == "integration.remote_required":
        return replace(state, status=RunStatus.waiting_external)
    if event.type == "run.dehydrated":
        return replace(
            state,
            status=RunStatus.dehydrated,
            last_checkpoint_id=event.payload.get("checkpoint_id"),
            snapshot_id=event.payload.get("snapshot_id", state.snapshot_id),
        )
    if event.type == "run.hydrated":
        return replace(
            state,
            status=RunStatus.resumable,
            last_checkpoint_id=event.payload.get("checkpoint_id", state.last_checkpoint_id),
            snapshot_id=event.payload.get("snapshot_id", state.snapshot_id),
        )
    if event.type == "run.completed":
        return replace(
            state,
            status=RunStatus.completed,
            pending_repair=None,
            repairing_command_id=None,
        )
    if event.type == "run.aborted":
        return replace(state, status=RunStatus.aborted)
    if event.type == "run.failed":
        failure = FailureClass(event.payload["failure_class"])
        return replace(
            state,
            status=RunStatus.failed,
            last_failure_class=failure,
            pending_repair=None,
            repairing_command_id=None,
        )
    return replace(state)
