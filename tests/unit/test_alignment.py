"""Tests for alignment engine."""

from __future__ import annotations

import pytest

from reins.alignment import (
    AlignmentCheck,
    AlignmentEngine,
    AlignmentStatus,
    Preference,
    PreferenceSource,
    Value,
    ValueKind,
)


@pytest.fixture
def engine() -> AlignmentEngine:
    e = AlignmentEngine(alignment_threshold=0.7, drift_threshold=0.5)
    e.register_value(ValueKind.SAFETY, weight=2.0, description="Do no harm")
    e.register_value(ValueKind.HELPFULNESS, weight=1.5, description="Be useful")
    e.register_value(ValueKind.HONESTY, weight=1.0, description="Be truthful")
    return e


def test_register_value(engine):
    v = engine.register_value(ValueKind.FAIRNESS, weight=1.0)
    assert v.kind == ValueKind.FAIRNESS


def test_add_preference(engine):
    p = engine.add_preference("explain", "ignore", strength=0.8)
    assert p.action_preferred == "explain"
    assert p.action_dispreferred == "ignore"


def test_check_aligned(engine):
    check = engine.check_alignment(
        "agent-1", "help_user",
        value_scores={"safety": 0.9, "helpfulness": 0.9, "honesty": 0.8},
    )
    assert check.status == AlignmentStatus.ALIGNED
    assert check.score >= 0.7


def test_check_misaligned(engine):
    check = engine.check_alignment(
        "agent-1", "dangerous_action",
        value_scores={"safety": 0.1, "helpfulness": 0.2, "honesty": 0.1},
    )
    assert check.status == AlignmentStatus.MISALIGNED


def test_check_drifting(engine):
    check = engine.check_alignment(
        "agent-1", "borderline",
        value_scores={"safety": 0.6, "helpfulness": 0.5, "honesty": 0.6},
    )
    assert check.status == AlignmentStatus.DRIFTING


def test_is_aligned_true(engine):
    assert engine.is_aligned(
        "a", "good_action",
        value_scores={"safety": 0.9, "helpfulness": 0.8, "honesty": 0.9},
    )


def test_is_aligned_false(engine):
    assert not engine.is_aligned(
        "a", "bad_action",
        value_scores={"safety": 0.1, "helpfulness": 0.1, "honesty": 0.1},
    )


def test_violations_detected(engine):
    engine.check_alignment(
        "a", "act",
        value_scores={"safety": 0.1, "helpfulness": 0.9, "honesty": 0.9},
    )
    violations = engine.get_violations()
    assert len(violations) >= 1


def test_violations_by_agent(engine):
    engine.check_alignment("a", "x", value_scores={"safety": 0.1})
    engine.check_alignment("b", "y", value_scores={"safety": 0.1})
    violations = engine.get_violations(agent_id="a")
    assert all(c.agent_id == "a" for c in violations)


def test_constraint_violation(engine):
    engine.register_value(ValueKind.PRIVACY, constraints=["delete_user_data"])
    check = engine.check_alignment(
        "a", "delete_user_data",
        value_scores={"safety": 0.9, "helpfulness": 0.9, "honesty": 0.9, "privacy": 0.9},
    )
    assert any("Constraint violated" in v for v in check.violations)


def test_preference_penalty(engine):
    engine.add_preference("explain_first", "skip_explanation", strength=2.0)
    check = engine.check_alignment(
        "a", "skip_explanation",
        value_scores={"safety": 0.9, "helpfulness": 0.9, "honesty": 0.9},
    )
    assert check.score < 0.9


def test_detect_drift_no_data(engine):
    drift = engine.detect_drift("agent-1")
    assert drift == 0.0


def test_detect_drift_declining(engine):
    for i in range(5):
        engine.check_alignment("a", "good", value_scores={"safety": 0.9, "helpfulness": 0.9, "honesty": 0.9})
    for i in range(5):
        engine.check_alignment("a", "worse", value_scores={"safety": 0.4, "helpfulness": 0.4, "honesty": 0.4})
    drift = engine.detect_drift("a")
    assert drift > 0.1


def test_detect_drift_stable(engine):
    for _ in range(10):
        engine.check_alignment("a", "consistent", value_scores={"safety": 0.8, "helpfulness": 0.8, "honesty": 0.8})
    drift = engine.detect_drift("a")
    assert drift < 0.05


def test_satisfied_values_tracked(engine):
    check = engine.check_alignment(
        "a", "safe_action",
        value_scores={"safety": 0.9, "helpfulness": 0.8, "honesty": 0.9},
    )
    assert "safety" in check.satisfied_values
    assert "honesty" in check.satisfied_values


def test_stats_empty():
    e = AlignmentEngine()
    stats = e.get_stats()
    assert stats.total_checks == 0
    assert stats.avg_alignment_score == 0.0


def test_stats_with_data(engine):
    engine.check_alignment("a", "x", value_scores={"safety": 0.9, "helpfulness": 0.9, "honesty": 0.9})
    engine.check_alignment("b", "y", value_scores={"safety": 0.1, "helpfulness": 0.1, "honesty": 0.1})
    stats = engine.get_stats()
    assert stats.total_checks == 2
    assert stats.aligned >= 1
    assert stats.misaligned >= 1
    assert stats.total_values == 3


def test_multiple_values_weighted(engine):
    check = engine.check_alignment(
        "a", "act",
        value_scores={"safety": 1.0, "helpfulness": 0.0, "honesty": 0.0},
    )
    assert check.score > 0.3
