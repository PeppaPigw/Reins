from __future__ import annotations

from copy import deepcopy

import pytest
from hypothesis import given, settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.reducer.reducer import reduce
from reins.kernel.reducer.state import RunState
from reins.kernel.types import Actor, FailureClass, PathKind, RunStatus

FAILURE_CLASSES = [fc.value for fc in FailureClass]
PATH_KINDS = [pk.value for pk in PathKind]
ACTORS = list(Actor)


@st.composite
def path_routed_payload(draw):
    return {"path": draw(st.sampled_from(PATH_KINDS))}


@st.composite
def grant_issued_payload(draw):
    return {
        "grant_id": draw(st.text(min_size=1, max_size=20)),
        "capability": draw(st.text(min_size=1, max_size=20)),
        "scope": draw(st.text(min_size=1, max_size=20)),
        "issued_to": draw(st.text(min_size=1, max_size=20)),
        "ttl_seconds": draw(st.integers(min_value=1, max_value=3600)),
        "approval_hash": draw(st.none() | st.text(min_size=1, max_size=20)),
        "issued_at": draw(st.floats(min_value=0, max_value=1e10, allow_nan=False)),
        "inherited": draw(st.booleans()),
    }


@st.composite
def grant_revoked_payload(draw):
    return {"grant_id": draw(st.text(min_size=1, max_size=20))}


@st.composite
def handle_opened_payload(draw):
    return {
        "handle_id": draw(st.text(min_size=1, max_size=20)),
        "adapter_kind": draw(st.text(min_size=1, max_size=20)),
        "adapter_id": draw(st.text(min_size=1, max_size=20)),
    }


@st.composite
def eval_completed_payload(draw):
    passed = draw(st.booleans())
    payload = {"passed": passed}
    if not passed:
        payload["failure_class"] = draw(st.sampled_from(FAILURE_CLASSES) | st.none())
    return payload


@st.composite
def repair_required_payload(draw):
    return {
        "eval_id": draw(st.text(min_size=1, max_size=20)),
        "failure_class": draw(st.sampled_from(FAILURE_CLASSES)),
        "repair_route": draw(st.text(min_size=1, max_size=20)),
        "retry_allowed": draw(st.booleans()),
        "details": draw(st.text(max_size=50)),
        "repair_hints": draw(st.lists(st.text(max_size=20), max_size=3)),
        "command_id": draw(st.none() | st.text(min_size=1, max_size=20)),
    }


@st.composite
def repair_started_payload(draw):
    return {"command_id": draw(st.text(min_size=1, max_size=20))}


@st.composite
def repair_finished_payload(draw):
    return {
        "eval_id": draw(st.text(min_size=1, max_size=20)),
        "command_id": draw(st.text(min_size=1, max_size=20)),
        "resolved_failure_class": draw(st.sampled_from(FAILURE_CLASSES) | st.none()),
    }


@st.composite
def approval_requested_payload(draw):
    return {"approval_id": draw(st.text(min_size=1, max_size=20))}


@st.composite
def approval_resolved_payload(draw):
    return {"approval_id": draw(st.text(min_size=1, max_size=20))}


@st.composite
def dehydrated_payload(draw):
    return {
        "checkpoint_id": draw(st.text(max_size=20)),
        "snapshot_id": draw(st.text(max_size=20)),
    }


@st.composite
def hydrated_payload(draw):
    return {
        "checkpoint_id": draw(st.text(max_size=20)),
        "snapshot_id": draw(st.text(max_size=20)),
    }


@st.composite
def run_failed_payload(draw):
    return {"failure_class": draw(st.sampled_from(FAILURE_CLASSES))}


EVENT_TYPE_STRATEGIES = {
    "run.started": st.just({}),
    "path.routed": path_routed_payload(),
    "policy.grant_issued": grant_issued_payload(),
    "policy.grant_revoked": grant_revoked_payload(),
    "adapter.handle_opened": handle_opened_payload(),
    "eval.completed": eval_completed_payload(),
    "repair.required": repair_required_payload(),
    "repair.started": repair_started_payload(),
    "repair.finished": repair_finished_payload(),
    "approval.requested": approval_requested_payload(),
    "approval.resolved": approval_resolved_payload(),
    "integration.remote_required": st.just({}),
    "run.dehydrated": dehydrated_payload(),
    "run.hydrated": hydrated_payload(),
    "run.completed": st.just({}),
    "run.aborted": st.just({}),
    "run.failed": run_failed_payload(),
}

EVENT_TYPES = list(EVENT_TYPE_STRATEGIES.keys())


@st.composite
def valid_event(draw, run_id="test-run"):
    event_type = draw(st.sampled_from(EVENT_TYPES))
    payload = draw(EVENT_TYPE_STRATEGIES[event_type])
    return EventEnvelope(
        run_id=run_id, actor=draw(st.sampled_from(ACTORS)), type=event_type, payload=payload
    )


@st.composite
def unknown_event(draw, run_id="test-run"):
    return EventEnvelope(
        run_id=run_id,
        actor=draw(st.sampled_from(ACTORS)),
        type="unknown.generated",
        payload=draw(st.dictionaries(st.text(max_size=10), st.text(max_size=10), max_size=3)),
    )


# --- Property Tests ---


@given(events=st.lists(valid_event(), min_size=1, max_size=30))
@settings(max_examples=200)
def test_replay_invariant(events):
    state = RunState(run_id="test-run")
    for event in events:
        state = reduce(state, event)

    replayed = RunState(run_id="test-run")
    for event in events:
        replayed = reduce(replayed, event)

    assert state.status == replayed.status
    assert state.active_grants == replayed.active_grants
    assert state.open_handles == replayed.open_handles
    assert state.pending_approvals == replayed.pending_approvals
    assert state.last_failure_class == replayed.last_failure_class
    assert state.pending_repair == replayed.pending_repair


@given(event=valid_event())
@settings(max_examples=200)
def test_purity(event):
    state = RunState(run_id="test-run")
    original = deepcopy(state)
    reduce(state, event)
    assert state.status == original.status
    assert state.active_grants == original.active_grants
    assert state.open_handles == original.open_handles
    assert state.pending_approvals == original.pending_approvals


@given(event=unknown_event())
@settings(max_examples=200)
def test_unknown_event_graceful(event):
    state = RunState(run_id="test-run")
    result = reduce(state, event)
    assert result.status == state.status
    assert result.active_grants == state.active_grants
    assert result.open_handles == state.open_handles
    assert result.pending_approvals == state.pending_approvals


@given(event=valid_event())
@settings(max_examples=200)
def test_no_exceptions(event):
    state = RunState(run_id="test-run")
    result = reduce(state, event)
    assert result is not None


@given(events=st.lists(valid_event(), min_size=1, max_size=30))
@settings(max_examples=200)
def test_status_always_valid(events):
    state = RunState(run_id="test-run")
    for event in events:
        state = reduce(state, event)
        assert state.status in RunStatus


# --- Stateful Test ---


class TestReducerStateMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.state = RunState(run_id="prop-test")
        self.events: list[EventEnvelope] = []

    def _apply(self, event_type: str, payload: dict):
        event = EventEnvelope(
            run_id="prop-test", actor=Actor.runtime, type=event_type, payload=payload
        )
        self.state = reduce(self.state, event)
        self.events.append(event)

    @rule()
    def start_run(self):
        self._apply("run.started", {})

    @rule(data=st.data())
    def route_path(self, data):
        self._apply("path.routed", {"path": data.draw(st.sampled_from(PATH_KINDS))})

    @rule(data=st.data())
    def issue_grant(self, data):
        self._apply("policy.grant_issued", data.draw(grant_issued_payload()))

    @rule(data=st.data())
    def revoke_grant(self, data):
        self._apply("policy.grant_revoked", data.draw(grant_revoked_payload()))

    @rule(data=st.data())
    def open_handle(self, data):
        self._apply("adapter.handle_opened", data.draw(handle_opened_payload()))

    @rule(data=st.data())
    def complete_eval(self, data):
        self._apply("eval.completed", data.draw(eval_completed_payload()))

    @rule(data=st.data())
    def require_repair(self, data):
        self._apply("repair.required", data.draw(repair_required_payload()))

    @rule(data=st.data())
    def start_repair(self, data):
        self._apply("repair.started", data.draw(repair_started_payload()))

    @rule(data=st.data())
    def finish_repair(self, data):
        self._apply("repair.finished", data.draw(repair_finished_payload()))

    @rule(data=st.data())
    def request_approval(self, data):
        self._apply("approval.requested", data.draw(approval_requested_payload()))

    @rule(data=st.data())
    def resolve_approval(self, data):
        self._apply("approval.resolved", data.draw(approval_resolved_payload()))

    @rule()
    def require_remote(self):
        self._apply("integration.remote_required", {})

    @rule(data=st.data())
    def dehydrate(self, data):
        self._apply("run.dehydrated", data.draw(dehydrated_payload()))

    @rule(data=st.data())
    def hydrate(self, data):
        self._apply("run.hydrated", data.draw(hydrated_payload()))

    @rule()
    def complete_run(self):
        self._apply("run.completed", {})

    @rule()
    def abort_run(self):
        self._apply("run.aborted", {})

    @rule(data=st.data())
    def fail_run(self, data):
        self._apply("run.failed", data.draw(run_failed_payload()))

    @invariant()
    def status_is_valid(self):
        assert self.state.status in RunStatus

    @invariant()
    def grants_is_list(self):
        assert isinstance(self.state.active_grants, list)

    @invariant()
    def replay_matches(self):
        replayed = RunState(run_id="prop-test")
        for event in self.events:
            replayed = reduce(replayed, event)
        assert self.state.status == replayed.status
        assert self.state.active_grants == replayed.active_grants
        assert self.state.pending_approvals == replayed.pending_approvals


TestReducerStateful = TestReducerStateMachine.TestCase
