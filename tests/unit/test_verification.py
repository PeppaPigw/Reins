"""Tests for the formal verification engine."""

from __future__ import annotations

import pytest

from reins.verification import (
    DeadlockReport,
    Invariant,
    InvariantKind,
    StateTransition,
    VerificationEngine,
    VerificationStatus,
)


@pytest.fixture
def engine() -> VerificationEngine:
    return VerificationEngine()


@pytest.mark.asyncio
async def test_state_invariant_verified_when_all_events_satisfy_predicate(engine):
    invariant = Invariant(
        name="status_not_empty",
        kind=InvariantKind.STATE_INVARIANT,
        description="Every event must have a non-empty status",
        predicate="event.status != ''",
    )

    async def predicate(event):
        return event.get("status", "") != ""

    engine.register_invariant(invariant, predicate)

    history = [
        {"status": "running", "seq": 1},
        {"status": "completed", "seq": 2},
    ]

    report = await engine.verify_all(history)
    assert report.all_verified
    assert report.violated_count == 0
    assert report.results[0].status == VerificationStatus.VERIFIED
    assert report.results[0].checked_states == 2


@pytest.mark.asyncio
async def test_state_invariant_violated_returns_counterexample(engine):
    invariant = Invariant(
        name="no_negative_seq",
        kind=InvariantKind.STATE_INVARIANT,
        description="Sequence numbers must be positive",
        predicate="event.seq > 0",
    )

    async def predicate(event):
        return event.get("seq", 0) > 0

    engine.register_invariant(invariant, predicate)

    history = [
        {"seq": 1},
        {"seq": 2},
        {"seq": -1},
        {"seq": 4},
    ]

    report = await engine.verify_all(history)
    assert not report.all_verified
    assert report.violated_count == 1
    result = report.results[0]
    assert result.status == VerificationStatus.VIOLATED
    assert result.counterexample == [{"seq": -1}]
    assert result.evidence["violated_at_index"] == 2


@pytest.mark.asyncio
async def test_transition_invariant_checks_consecutive_pairs(engine):
    invariant = Invariant(
        name="monotonic_seq",
        kind=InvariantKind.TRANSITION_INVARIANT,
        description="Sequence numbers must increase",
        predicate="after.seq > before.seq",
    )

    async def predicate(pair):
        return pair["after"].get("seq", 0) > pair["before"].get("seq", 0)

    engine.register_invariant(invariant, predicate)

    good_history = [{"seq": 1}, {"seq": 2}, {"seq": 3}]
    report = await engine.verify_all(good_history)
    assert report.all_verified

    bad_history = [{"seq": 1}, {"seq": 3}, {"seq": 2}]
    report = await engine.verify_all(bad_history)
    assert not report.all_verified
    assert report.results[0].checked_transitions == 2


@pytest.mark.asyncio
async def test_safety_property_detects_bad_state(engine):
    invariant = Invariant(
        name="no_unauthorized_exec",
        kind=InvariantKind.SAFETY_PROPERTY,
        description="No execution without prior grant",
        predicate="not (executed and not granted)",
    )

    async def predicate(event):
        if event.get("event_type") == "command.executed":
            return event.get("has_grant", False)
        return True

    engine.register_invariant(invariant, predicate)

    history = [
        {"event_type": "grant.issued", "has_grant": True},
        {"event_type": "command.executed", "has_grant": True},
        {"event_type": "command.executed", "has_grant": False},
    ]

    report = await engine.verify_all(history)
    assert report.violated_count == 1
    assert report.results[0].evidence["bad_state_reached_at"] == 2


@pytest.mark.asyncio
async def test_liveness_property_verified_when_good_state_reached(engine):
    invariant = Invariant(
        name="eventually_completes",
        kind=InvariantKind.LIVENESS_PROPERTY,
        description="Run must eventually reach completed state",
        predicate="event.status == 'completed'",
    )

    async def predicate(event):
        return event.get("status") == "completed"

    engine.register_invariant(invariant, predicate)

    good = [{"status": "running"}, {"status": "running"}, {"status": "completed"}]
    report = await engine.verify_all(good)
    assert report.all_verified

    bad = [{"status": "running"}, {"status": "running"}, {"status": "failed"}]
    report = await engine.verify_all(bad)
    assert not report.all_verified
    assert report.results[0].evidence["reason"] == "good state never reached"


@pytest.mark.asyncio
async def test_deadlock_detection_finds_sink_states(engine):
    engine.register_transition(StateTransition(
        from_state="idle", to_state="running", event_type="run.started"
    ))
    engine.register_transition(StateTransition(
        from_state="running", to_state="stuck", event_type="run.stuck"
    ))

    report = await engine.verify_all([])
    assert report.deadlock_report is not None
    assert report.deadlock_report.has_deadlock
    assert "stuck" in report.deadlock_report.deadlock_states


@pytest.mark.asyncio
async def test_deadlock_detection_ignores_terminal_states(engine):
    engine.register_transition(StateTransition(
        from_state="idle", to_state="running", event_type="run.started"
    ))
    engine.register_transition(StateTransition(
        from_state="running", to_state="completed", event_type="run.completed"
    ))
    engine.register_transition(StateTransition(
        from_state="running", to_state="failed", event_type="run.failed"
    ))

    report = await engine.verify_all([])
    assert report.deadlock_report is not None
    assert not report.deadlock_report.has_deadlock


@pytest.mark.asyncio
async def test_cycle_detection(engine):
    engine.register_transition(StateTransition(
        from_state="a", to_state="b", event_type="go"
    ))
    engine.register_transition(StateTransition(
        from_state="b", to_state="c", event_type="go"
    ))
    engine.register_transition(StateTransition(
        from_state="c", to_state="a", event_type="go"
    ))

    report = await engine.verify_all([])
    assert report.deadlock_report is not None
    assert report.deadlock_report.has_deadlock
    assert len(report.deadlock_report.cycle_path) > 0


@pytest.mark.asyncio
async def test_policy_completeness_detects_uncovered_capabilities(engine):
    history = [
        {"capability": "fs.read", "event_type": "policy.evaluated",
         "payload": {"capability": "fs.read", "decision": "allow"}},
        {"capability": "fs.write", "event_type": "command.executed",
         "payload": {}},
        {"capability": "shell.exec", "event_type": "command.executed",
         "payload": {}},
    ]

    report = await engine.verify_all(history)
    assert report.policy_report is not None
    assert not report.policy_report.is_complete
    assert "fs.write" in report.policy_report.uncovered_capabilities
    assert "shell.exec" in report.policy_report.uncovered_capabilities


@pytest.mark.asyncio
async def test_policy_completeness_detects_conflicting_rules(engine):
    history = [
        {"capability": "fs.write", "event_type": "policy.evaluated",
         "payload": {"capability": "fs.write", "decision": "allow"}},
        {"capability": "fs.write", "event_type": "policy.evaluated",
         "payload": {"capability": "fs.write", "decision": "deny"}},
    ]

    report = await engine.verify_all(history)
    assert report.policy_report is not None
    assert not report.policy_report.is_complete
    assert len(report.policy_report.conflicting_rules) == 1
