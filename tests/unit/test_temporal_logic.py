"""Tests for LTL temporal logic checker."""

from __future__ import annotations

import pytest

from reins.temporal_logic import (
    PropertyCheck,
    PropertyStatus,
    TemporalChecker,
    TemporalOp,
    TemporalProperty,
    Trace,
    TraceEvent,
)


@pytest.fixture
def checker() -> TemporalChecker:
    return TemporalChecker()


def _trace(steps: list[set[str]]) -> Trace:
    events = [TraceEvent(step=i, propositions=props if props else set()) for i, props in enumerate(steps)]
    return Trace(events=events)


def test_define_property(checker):
    prop = checker.define_property("safe", TemporalOp.ALWAYS, "approved")
    assert prop.name == "safe"
    assert prop.operator == TemporalOp.ALWAYS


def test_get_property(checker):
    prop = checker.define_property("x", TemporalOp.ALWAYS, "p")
    assert checker.get_property(prop.property_id) is not None
    assert checker.get_property("missing") is None


def test_always_satisfied(checker):
    prop = checker.define_property("always_auth", TemporalOp.ALWAYS, "authenticated")
    trace = _trace([{"authenticated"}, {"authenticated"}, {"authenticated"}])
    result = checker.check(prop.property_id, trace)
    assert result.status == PropertyStatus.SATISFIED
    assert result.steps_checked == 3


def test_always_violated(checker):
    prop = checker.define_property("always_auth", TemporalOp.ALWAYS, "authenticated")
    trace = _trace([{"authenticated"}, set(), {"authenticated"}])
    result = checker.check(prop.property_id, trace)
    assert result.status == PropertyStatus.VIOLATED
    assert result.violated_at_step == 1


def test_eventually_satisfied(checker):
    prop = checker.define_property("completes", TemporalOp.EVENTUALLY, "done")
    trace = _trace([{"running"}, {"running"}, {"done"}])
    result = checker.check(prop.property_id, trace)
    assert result.status == PropertyStatus.SATISFIED


def test_eventually_violated(checker):
    prop = checker.define_property("completes", TemporalOp.EVENTUALLY, "done")
    trace = _trace([{"running"}, {"running"}, {"running"}])
    result = checker.check(prop.property_id, trace)
    assert result.status == PropertyStatus.VIOLATED


def test_never_satisfied(checker):
    prop = checker.define_property("no_crash", TemporalOp.NEVER, "crashed")
    trace = _trace([{"running"}, {"idle"}, {"running"}])
    result = checker.check(prop.property_id, trace)
    assert result.status == PropertyStatus.SATISFIED


def test_never_violated(checker):
    prop = checker.define_property("no_crash", TemporalOp.NEVER, "crashed")
    trace = _trace([{"running"}, {"crashed"}, {"recovered"}])
    result = checker.check(prop.property_id, trace)
    assert result.status == PropertyStatus.VIOLATED
    assert result.violated_at_step == 1


def test_next_satisfied(checker):
    prop = checker.define_property("init_then_ready", TemporalOp.NEXT, "ready")
    trace = _trace([{"init"}, {"ready"}, {"working"}])
    result = checker.check(prop.property_id, trace)
    assert result.status == PropertyStatus.SATISFIED


def test_next_violated(checker):
    prop = checker.define_property("init_then_ready", TemporalOp.NEXT, "ready")
    trace = _trace([{"init"}, {"loading"}, {"ready"}])
    result = checker.check(prop.property_id, trace)
    assert result.status == PropertyStatus.VIOLATED


def test_next_too_short(checker):
    prop = checker.define_property("x", TemporalOp.NEXT, "p")
    trace = _trace([{"init"}])
    result = checker.check(prop.property_id, trace)
    assert result.status == PropertyStatus.PENDING


def test_until_satisfied(checker):
    prop = checker.define_property("wait_until", TemporalOp.UNTIL,
                                    "waiting", secondary="ready")
    trace = _trace([{"waiting"}, {"waiting"}, {"ready"}])
    result = checker.check(prop.property_id, trace)
    assert result.status == PropertyStatus.SATISFIED


def test_until_violated_p_fails(checker):
    prop = checker.define_property("hold", TemporalOp.UNTIL,
                                    "holding", secondary="released")
    trace = _trace([{"holding"}, set(), {"released"}])
    result = checker.check(prop.property_id, trace)
    assert result.status == PropertyStatus.VIOLATED
    assert result.violated_at_step == 1


def test_until_violated_q_never(checker):
    prop = checker.define_property("hold", TemporalOp.UNTIL,
                                    "holding", secondary="released")
    trace = _trace([{"holding"}, {"holding"}, {"holding"}])
    result = checker.check(prop.property_id, trace)
    assert result.status == PropertyStatus.VIOLATED


def test_implies_satisfied(checker):
    prop = checker.define_property("auth_implies_logged", TemporalOp.IMPLIES,
                                    "write_access", secondary="audit_logged")
    trace = _trace([
        {"write_access", "audit_logged"},
        {"read_only"},
        {"write_access", "audit_logged"},
    ])
    result = checker.check(prop.property_id, trace)
    assert result.status == PropertyStatus.SATISFIED


def test_implies_violated(checker):
    prop = checker.define_property("auth_implies_logged", TemporalOp.IMPLIES,
                                    "write_access", secondary="audit_logged")
    trace = _trace([
        {"write_access", "audit_logged"},
        {"write_access"},
    ])
    result = checker.check(prop.property_id, trace)
    assert result.status == PropertyStatus.VIOLATED
    assert result.violated_at_step == 1


def test_check_empty_trace(checker):
    prop = checker.define_property("x", TemporalOp.ALWAYS, "p")
    result = checker.check(prop.property_id, Trace())
    assert result.status == PropertyStatus.PENDING


def test_check_unknown_property(checker):
    result = checker.check("nonexistent", _trace([{"x"}]))
    assert result.status == PropertyStatus.UNKNOWN


def test_check_all(checker):
    p1 = checker.define_property("a", TemporalOp.ALWAYS, "ok")
    p2 = checker.define_property("b", TemporalOp.NEVER, "bad")
    trace = _trace([{"ok"}, {"ok"}])
    results = checker.check_all(trace)
    assert len(results) == 2
    assert all(r.status == PropertyStatus.SATISFIED for r in results)


def test_check_online_eventually(checker):
    prop = checker.define_property("done", TemporalOp.EVENTUALLY, "complete")
    events = [TraceEvent(step=0, propositions={"running"})]
    result = checker.check_online(prop.property_id, events)
    assert result.status == PropertyStatus.VIOLATED

    events.append(TraceEvent(step=1, propositions={"complete"}))
    result = checker.check_online(prop.property_id, events)
    assert result.status == PropertyStatus.SATISFIED


def test_check_online_always_pending(checker):
    prop = checker.define_property("safe", TemporalOp.ALWAYS, "ok")
    events = [TraceEvent(step=0, propositions={"ok"})]
    result = checker.check_online(prop.property_id, events)
    assert result.status == PropertyStatus.PENDING


def test_get_checks_filter(checker):
    prop = checker.define_property("x", TemporalOp.ALWAYS, "p")
    checker.check(prop.property_id, _trace([{"p"}]))
    checker.check(prop.property_id, _trace([set()]))
    satisfied = checker.get_checks(status=PropertyStatus.SATISFIED)
    violated = checker.get_checks(status=PropertyStatus.VIOLATED)
    assert len(satisfied) == 1
    assert len(violated) == 1


def test_stats(checker):
    p1 = checker.define_property("a", TemporalOp.ALWAYS, "x")
    p2 = checker.define_property("b", TemporalOp.EVENTUALLY, "y")
    checker.check(p1.property_id, _trace([{"x"}]))
    checker.check(p2.property_id, _trace([{"y"}]))
    stats = checker.get_stats()
    assert stats.total_properties == 2
    assert stats.total_checks == 2
    assert stats.satisfied == 2
    assert stats.by_operator["always"] == 1
    assert stats.by_operator["eventually"] == 1
