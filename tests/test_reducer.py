from __future__ import annotations

from copy import deepcopy

from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.reducer.reducer import reduce
from reins.kernel.reducer.state import RunState
from reins.kernel.routing.router import route
from reins.kernel.types import Actor, GrantRef, PathKind, RunStatus


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
