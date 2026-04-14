from __future__ import annotations

from copy import deepcopy

from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.reducer.reducer import reduce
from reins.kernel.reducer.state import CompletedRepair, PendingRepair, RunState
from reins.kernel.routing.router import route
from reins.kernel.types import Actor, FailureClass, GrantRef, PathKind, RunStatus


def make_event(event_type: str, payload: dict) -> EventEnvelope:
    return EventEnvelope(run_id="run-1", actor=Actor.runtime, type=event_type, payload=payload)


def test_run_started() -> None:
    state = RunState(run_id="run-1")
    next_state = reduce(state, make_event("run.started", {}))
    assert next_state.status is RunStatus.routing


def test_grant_issued_and_revoked() -> None:
    state = RunState(run_id="run-1")
    grant = {
        "grant_id": "grant-1",
        "capability": "fs.read",
        "scope": "workspace",
        "issued_to": "model",
        "ttl_seconds": 60,
        "approval_hash": None,
        "inherited": False,
    }
    issued = reduce(state, make_event("policy.grant_issued", grant))
    assert issued.active_grants == [GrantRef(**grant)]
    revoked = reduce(issued, make_event("policy.grant_revoked", {"grant_id": "grant-1"}))
    assert revoked.active_grants == []


def test_reducer_is_pure() -> None:
    state = RunState(run_id="run-1")
    original = deepcopy(state)
    event = make_event("run.failed", {"failure_class": "logic_failure"})
    next_a = reduce(state, event)
    next_b = reduce(state, event)
    assert state == original
    assert next_a == next_b
    assert next_a is not state


def test_path_router_fast() -> None:
    assert route(["fs.read", "git.status"]) is PathKind.fast


def test_path_router_deliberative() -> None:
    assert route(["fs.write.workspace"]) is PathKind.deliberative


def test_path_router_ambiguity() -> None:
    assert route(["fs.read"], ambiguity_score=0.9) is PathKind.deliberative


def test_repair_required_records_pending_repair_and_marks_run_resumable() -> None:
    state = RunState(run_id="run-1", status=RunStatus.executing)
    repair = reduce(
        state,
        make_event(
            "repair.required",
            {
                "eval_id": "eval-1",
                "failure_class": "logic_failure",
                "repair_route": "change_hypothesis",
                "retry_allowed": False,
                "details": "assertion error",
                "repair_hints": ["fix assertion"],
                "command_id": "cmd-1",
            },
        ),
    )

    assert repair.status is RunStatus.resumable
    assert repair.last_failure_class is FailureClass.logic_failure
    assert repair.pending_repair == PendingRepair(
        eval_id="eval-1",
        failure_class=FailureClass.logic_failure,
        repair_route="change_hypothesis",
        retry_allowed=False,
        details="assertion error",
        repair_hints=["fix assertion"],
        command_id="cmd-1",
    )


def test_repair_started_clears_pending_repair_and_tracks_active_command() -> None:
    state = RunState(
        run_id="run-1",
        status=RunStatus.resumable,
        pending_repair=PendingRepair(
            eval_id="eval-1",
            failure_class=FailureClass.logic_failure,
            repair_route="change_hypothesis",
            retry_allowed=False,
            details="assertion error",
            repair_hints=["fix assertion"],
            command_id="cmd-old",
        ),
        last_failure_class=FailureClass.logic_failure,
    )
    next_state = reduce(
        state,
        make_event(
            "repair.started",
            {
                "command_id": "cmd-new",
                "previous_eval_id": "eval-1",
                "previous_failure_class": "logic_failure",
            },
        ),
    )
    assert next_state.status is RunStatus.executing
    assert next_state.pending_repair is None
    assert next_state.repairing_command_id == "cmd-new"
    assert next_state.last_failure_class is FailureClass.logic_failure


def test_repair_finished_clears_active_repair_state() -> None:
    state = RunState(
        run_id="run-1",
        status=RunStatus.executing,
        last_failure_class=FailureClass.logic_failure,
        repairing_command_id="cmd-new",
    )
    next_state = reduce(
        state,
        make_event(
            "repair.finished",
            {
                "command_id": "cmd-new",
                "eval_id": "eval-2",
                "resolved_failure_class": "logic_failure",
            },
        ),
    )
    assert next_state.last_failure_class is None
    assert next_state.pending_repair is None
    assert next_state.repairing_command_id is None
    assert next_state.last_completed_repair == CompletedRepair(
        eval_id="eval-2",
        command_id="cmd-new",
        failure_class=FailureClass.logic_failure,
    )
