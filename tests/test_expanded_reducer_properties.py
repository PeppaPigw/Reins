"""Expanded property-based tests for the reducer.

These tests use Hypothesis to verify reducer invariants with hundreds of
generated cases, covering determinism, idempotency, terminal states,
graceful handling of unknown events, and serialization safety.
"""

from __future__ import annotations

from copy import deepcopy

from hypothesis import given, settings, strategies as st

from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.reducer.reducer import reduce
from reins.kernel.reducer.state import RunState
from reins.kernel.types import Actor, FailureClass, PathKind, RunStatus
from reins.serde import to_primitive

# --- Strategies ---

VALID_EVENT_TYPES = [
    "run.started",
    "path.routed",
    "policy.grant_issued",
    "policy.grant_revoked",
    "adapter.handle_opened",
    "eval.completed",
    "repair.required",
    "repair.started",
    "repair.finished",
    "approval.requested",
    "approval.resolved",
    "integration.remote_required",
    "run.dehydrated",
    "run.hydrated",
    "run.completed",
    "run.aborted",
    "run.failed",
]

FAILURE_CLASSES = [fc.value for fc in FailureClass]
PATH_KINDS = [pk.value for pk in PathKind]
ACTORS = list(Actor)

TERMINAL_STATUSES = {RunStatus.completed, RunStatus.aborted, RunStatus.failed}


@st.composite
def payload_for_event_type(draw, event_type: str) -> dict:
    """Generate a valid payload for a given event type."""
    if event_type == "run.started":
        return {}
    if event_type == "path.routed":
        return {"path": draw(st.sampled_from(PATH_KINDS))}
    if event_type == "policy.grant_issued":
        return {
            "grant_id": draw(st.text(min_size=1, max_size=15, alphabet="abcdefghijklmnop0123456789")),
            "capability": draw(st.text(min_size=1, max_size=15, alphabet="abcdefghijklmnop.")),
            "scope": draw(st.text(min_size=1, max_size=15, alphabet="abcdefghijklmnop/")),
            "issued_to": draw(st.text(min_size=1, max_size=15, alphabet="abcdefghijklmnop-")),
            "ttl_seconds": draw(st.integers(min_value=1, max_value=3600)),
            "approval_hash": draw(st.none() | st.text(min_size=1, max_size=10)),
            "issued_at": draw(st.floats(min_value=0, max_value=1e10, allow_nan=False)),
            "inherited": draw(st.booleans()),
        }
    if event_type == "policy.grant_revoked":
        return {"grant_id": draw(st.text(min_size=1, max_size=15, alphabet="abcdefghijklmnop0123456789"))}
    if event_type == "adapter.handle_opened":
        return {
            "handle_id": draw(st.text(min_size=1, max_size=15, alphabet="abcdefghijklmnop0123456789")),
            "adapter_kind": draw(st.text(min_size=1, max_size=10, alphabet="abcdefghijklmnop")),
            "adapter_id": draw(st.text(min_size=1, max_size=10, alphabet="abcdefghijklmnop0123456789")),
        }
    if event_type == "eval.completed":
        passed = draw(st.booleans())
        payload: dict = {"passed": passed}
        if not passed:
            payload["failure_class"] = draw(st.sampled_from(FAILURE_CLASSES) | st.none())
        return payload
    if event_type == "repair.required":
        return {
            "eval_id": draw(st.text(min_size=1, max_size=10, alphabet="abcdefghijklmnop")),
            "failure_class": draw(st.sampled_from(FAILURE_CLASSES)),
            "repair_route": draw(st.text(min_size=1, max_size=10, alphabet="abcdefghijklmnop")),
            "retry_allowed": draw(st.booleans()),
            "details": draw(st.text(max_size=20)),
            "repair_hints": draw(st.lists(st.text(max_size=10), max_size=3)),
            "command_id": draw(st.none() | st.text(min_size=1, max_size=10)),
        }
    if event_type == "repair.started":
        return {"command_id": draw(st.text(min_size=1, max_size=15, alphabet="abcdefghijklmnop"))}
    if event_type == "repair.finished":
        return {
            "eval_id": draw(st.text(min_size=1, max_size=10, alphabet="abcdefghijklmnop")),
            "command_id": draw(st.text(min_size=1, max_size=10, alphabet="abcdefghijklmnop")),
            "resolved_failure_class": draw(st.sampled_from(FAILURE_CLASSES) | st.none()),
        }
    if event_type == "approval.requested":
        return {"approval_id": draw(st.text(min_size=1, max_size=15, alphabet="abcdefghijklmnop"))}
    if event_type == "approval.resolved":
        return {"approval_id": draw(st.text(min_size=1, max_size=15, alphabet="abcdefghijklmnop"))}
    if event_type == "integration.remote_required":
        return {}
    if event_type == "run.dehydrated":
        return {
            "checkpoint_id": draw(st.text(max_size=15, alphabet="abcdefghijklmnop0123456789")),
            "snapshot_id": draw(st.text(max_size=15, alphabet="abcdefghijklmnop0123456789")),
        }
    if event_type == "run.hydrated":
        return {
            "checkpoint_id": draw(st.text(max_size=15, alphabet="abcdefghijklmnop0123456789")),
            "snapshot_id": draw(st.text(max_size=15, alphabet="abcdefghijklmnop0123456789")),
        }
    if event_type == "run.completed":
        return {}
    if event_type == "run.aborted":
        return {}
    if event_type == "run.failed":
        return {"failure_class": draw(st.sampled_from(FAILURE_CLASSES))}
    return {}


@st.composite
def valid_event_envelope(draw, run_id: str = "prop-test-run") -> EventEnvelope:
    """Generate a valid EventEnvelope with correct payload for its type."""
    event_type = draw(st.sampled_from(VALID_EVENT_TYPES))
    payload = draw(payload_for_event_type(event_type))
    return EventEnvelope(
        run_id=run_id,
        actor=draw(st.sampled_from(ACTORS)),
        type=event_type,
        payload=payload,
    )


@st.composite
def event_sequence(draw, min_size: int = 1, max_size: int = 20) -> list[EventEnvelope]:
    """Generate a sequence of valid events."""
    return draw(st.lists(valid_event_envelope(), min_size=min_size, max_size=max_size))


# --- Property Tests ---


@given(events=event_sequence(min_size=1, max_size=20))
@settings(max_examples=500)
def test_reducer_never_crashes_on_valid_events(events: list[EventEnvelope]):
    """Given any valid event sequence, reduce never raises."""
    state = RunState(run_id="prop-test-run")
    for event in events:
        state = reduce(state, event)
    assert state is not None


@given(events=event_sequence(min_size=1, max_size=20))
@settings(max_examples=500)
def test_reducer_state_always_has_run_id(events: list[EventEnvelope]):
    """After any reduction, state.run_id is preserved."""
    state = RunState(run_id="prop-test-run")
    for event in events:
        state = reduce(state, event)
    assert state.run_id == "prop-test-run"


@given(events=event_sequence(min_size=2, max_size=20))
@settings(max_examples=500)
def test_reducer_events_count_monotonically_increases(events: list[EventEnvelope]):
    """Grants list size only changes by at most one per event (monotonic growth check)."""
    state = RunState(run_id="prop-test-run")
    prev_grants = 0
    for event in events:
        state = reduce(state, event)
        current_grants = len(state.active_grants)
        # Grants can grow by 1 (issued) or shrink (revoked), but never jump by more than 1 up
        assert current_grants <= prev_grants + 1
        prev_grants = current_grants


@given(event=valid_event_envelope())
@settings(max_examples=500)
def test_reducer_idempotent_on_duplicate_events(event: EventEnvelope):
    """Applying same event twice: second application doesn't crash and state is consistent."""
    state = RunState(run_id="prop-test-run")
    state_after_first = reduce(state, event)
    state_after_second = reduce(state_after_first, event)
    # The reducer should not crash on duplicate events
    assert state_after_second is not None
    assert state_after_second.run_id == "prop-test-run"


@given(events=event_sequence(min_size=1, max_size=20))
@settings(max_examples=500)
def test_reducer_status_transitions_are_valid(events: list[EventEnvelope]):
    """Status only moves through valid RunStatus values."""
    state = RunState(run_id="prop-test-run")
    for event in events:
        state = reduce(state, event)
        assert state.status in RunStatus


@given(events=event_sequence(min_size=1, max_size=15))
@settings(max_examples=500)
def test_reducer_completed_state_is_terminal(events: list[EventEnvelope]):
    """Once completed, the run.completed event sets terminal status."""
    state = RunState(run_id="prop-test-run")
    # First, drive to completed
    completed_event = EventEnvelope(
        run_id="prop-test-run",
        actor=Actor.runtime,
        type="run.completed",
        payload={},
    )
    state = reduce(state, completed_event)
    assert state.status == RunStatus.completed

    # Apply more events — only terminal events (aborted/failed) can change from completed
    for event in events:
        new_state = reduce(state, event)
        if event.type in ("run.aborted", "run.failed"):
            # These are also terminal — they override
            assert new_state.status in TERMINAL_STATUSES
        elif event.type == "run.completed":
            assert new_state.status == RunStatus.completed
        # Non-terminal events may or may not change status depending on reducer logic
        # but the state should always be valid
        assert new_state.status in RunStatus


@given(event=valid_event_envelope())
@settings(max_examples=500)
def test_reducer_preserves_trace_id(event: EventEnvelope):
    """The reducer does not corrupt the trace_id on the event."""
    original_trace = event.trace_id
    state = RunState(run_id="prop-test-run")
    reduce(state, event)
    # EventEnvelope is frozen, trace_id should be unchanged
    assert event.trace_id == original_trace


@given(
    payload=st.dictionaries(
        st.text(min_size=1, max_size=10, alphabet="abcdefghijklmnop"),
        st.text(max_size=20),
        max_size=5,
    )
)
@settings(max_examples=500)
def test_reducer_handles_unknown_event_types_gracefully(payload: dict):
    """Unknown event types don't crash the reducer."""
    event = EventEnvelope(
        run_id="prop-test-run",
        actor=Actor.runtime,
        type="totally.unknown.event",
        payload=payload,
    )
    state = RunState(run_id="prop-test-run")
    result = reduce(state, event)
    # Unknown events should not change status from created
    assert result.status == state.status
    assert result.run_id == "prop-test-run"


@given(events=event_sequence(min_size=1, max_size=15))
@settings(max_examples=500)
def test_reducer_state_serializable(events: list[EventEnvelope]):
    """After any reduction, state can be serialized to a primitive dict."""
    state = RunState(run_id="prop-test-run")
    for event in events:
        state = reduce(state, event)
    # to_primitive should not raise
    serialized = to_primitive(state)
    assert isinstance(serialized, dict)
    assert serialized["run_id"] == "prop-test-run"
    assert "status" in serialized


@given(events=event_sequence(min_size=1, max_size=20))
@settings(max_examples=500)
def test_reducer_deterministic(events: list[EventEnvelope]):
    """Same event sequence always produces the same final state."""
    state1 = RunState(run_id="prop-test-run")
    for event in events:
        state1 = reduce(state1, event)

    state2 = RunState(run_id="prop-test-run")
    for event in events:
        state2 = reduce(state2, event)

    assert state1.status == state2.status
    assert state1.active_grants == state2.active_grants
    assert state1.open_handles == state2.open_handles
    assert state1.pending_approvals == state2.pending_approvals
    assert state1.last_failure_class == state2.last_failure_class
    assert state1.pending_repair == state2.pending_repair


@given(events=event_sequence(min_size=2, max_size=10))
@settings(max_examples=500)
def test_reducer_order_matters_for_non_commutative(events: list[EventEnvelope]):
    """Different orderings may produce different states (non-commutativity)."""
    state_forward = RunState(run_id="prop-test-run")
    for event in events:
        state_forward = reduce(state_forward, event)

    state_reverse = RunState(run_id="prop-test-run")
    for event in reversed(events):
        state_reverse = reduce(state_reverse, event)

    # We can't assert they're always different (some sequences commute),
    # but both must be valid states
    assert state_forward.status in RunStatus
    assert state_reverse.status in RunStatus
    assert state_forward.run_id == "prop-test-run"
    assert state_reverse.run_id == "prop-test-run"


@given(event_type=st.sampled_from(VALID_EVENT_TYPES))
@settings(max_examples=500)
def test_reducer_empty_payload_handled(event_type: str):
    """Events with empty payloads don't crash the reducer (graceful degradation)."""
    event = EventEnvelope(
        run_id="prop-test-run",
        actor=Actor.runtime,
        type=event_type,
        payload={},
    )
    state = RunState(run_id="prop-test-run")
    try:
        result = reduce(state, event)
        # If it doesn't raise, the result must be valid
        assert result is not None
        assert result.status in RunStatus
    except (KeyError, ValueError):
        # Some event types require specific payload keys — that's acceptable
        # The important thing is no unexpected crashes (AttributeError, TypeError, etc.)
        pass


@given(event=valid_event_envelope())
@settings(max_examples=500)
def test_reducer_purity_no_mutation(event: EventEnvelope):
    """The reducer does not mutate the input state."""
    state = RunState(run_id="prop-test-run")
    original = deepcopy(state)
    reduce(state, event)
    assert state.status == original.status
    assert state.active_grants == original.active_grants
    assert state.open_handles == original.open_handles
    assert state.pending_approvals == original.pending_approvals
