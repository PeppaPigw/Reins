"""Tests for reflection engine with calibration tracking and insight extraction."""

from __future__ import annotations

import pytest

from reins.reflection import (
    ConfidenceLevel,
    Decision,
    Insight,
    InsightCategory,
    Outcome,
    Reflection,
    ReflectionEngine,
    ReflectionKind,
    ReflectionStats,
)


@pytest.fixture
def engine() -> ReflectionEngine:
    return ReflectionEngine()


def test_record_decision(engine):
    d = engine.record_decision("agent-1", "deploy", confidence=0.8)
    assert d.agent_id == "agent-1"
    assert d.confidence == 0.8


def test_record_decision_with_alternatives(engine):
    d = engine.record_decision("a", "deploy", alternatives=["rollback", "wait"])
    assert len(d.alternatives) == 2


def test_get_decision(engine):
    d = engine.record_decision("a", "action")
    assert engine.get_decision(d.decision_id) is not None


def test_get_decision_not_found(engine):
    assert engine.get_decision("nonexistent") is None


def test_get_decisions_all(engine):
    engine.record_decision("a", "action1")
    engine.record_decision("b", "action2")
    assert len(engine.get_decisions()) == 2


def test_get_decisions_by_agent(engine):
    engine.record_decision("a", "action1")
    engine.record_decision("b", "action2")
    assert len(engine.get_decisions(agent_id="a")) == 1


def test_record_outcome_success(engine):
    d = engine.record_decision("a", "deploy", confidence=0.9)
    o = engine.record_outcome(d.decision_id, success=True)
    assert o is not None
    assert o.success is True
    assert o.deviation_score == pytest.approx(0.1)


def test_record_outcome_failure(engine):
    d = engine.record_decision("a", "deploy", confidence=0.9)
    o = engine.record_outcome(d.decision_id, success=False)
    assert o.deviation_score == pytest.approx(0.9)


def test_record_outcome_nonexistent_decision(engine):
    assert engine.record_outcome("nonexistent", success=True) is None


def test_get_outcome(engine):
    d = engine.record_decision("a", "action")
    engine.record_outcome(d.decision_id, success=True)
    assert engine.get_outcome(d.decision_id) is not None


def test_calibration_error_perfect(engine):
    d = engine.record_decision("a", "action", confidence=1.0)
    engine.record_outcome(d.decision_id, success=True)
    assert engine.get_calibration_error("a") == pytest.approx(0.0)


def test_calibration_error_overconfident(engine):
    for _ in range(5):
        d = engine.record_decision("a", "action", confidence=0.9)
        engine.record_outcome(d.decision_id, success=False)
    error = engine.get_calibration_error("a")
    assert error > 0.5


def test_calibration_error_no_outcomes(engine):
    engine.record_decision("a", "action")
    assert engine.get_calibration_error("a") == 0.0


def test_confidence_level_high(engine):
    d = engine.record_decision("a", "action", confidence=0.95)
    engine.record_outcome(d.decision_id, success=True)
    level = engine.get_confidence_level("a")
    assert level in (ConfidenceLevel.VERY_HIGH, ConfidenceLevel.HIGH)


def test_confidence_level_low(engine):
    for _ in range(5):
        d = engine.record_decision("a", "action", confidence=0.9)
        engine.record_outcome(d.decision_id, success=False)
    level = engine.get_confidence_level("a")
    assert level in (ConfidenceLevel.VERY_LOW, ConfidenceLevel.LOW)


def test_reflect_basic(engine):
    d = engine.record_decision("a", "action", confidence=0.8)
    engine.record_outcome(d.decision_id, success=True)
    reflection = engine.reflect("a")
    assert reflection.agent_id == "a"
    assert reflection.kind == ReflectionKind.OUTCOME_ANALYSIS


def test_reflect_generates_summary(engine):
    d = engine.record_decision("a", "action", confidence=0.8)
    engine.record_outcome(d.decision_id, success=True)
    reflection = engine.reflect("a")
    assert len(reflection.summary) > 0


def test_reflect_detects_repeated_mistakes(engine):
    for _ in range(3):
        d = engine.record_decision("a", "same_action", confidence=0.5)
        engine.record_outcome(d.decision_id, success=False)
    reflection = engine.reflect("a")
    assert "Repeated mistakes" in reflection.summary


def test_reflect_detects_effective_strategy(engine):
    for _ in range(3):
        d = engine.record_decision("a", "good_action", confidence=0.7)
        engine.record_outcome(d.decision_id, success=True)
    reflection = engine.reflect("a")
    assert "Effective strategies" in reflection.summary


def test_reflect_detects_calibration_gap(engine):
    for _ in range(5):
        d = engine.record_decision("a", "action", confidence=0.9)
        engine.record_outcome(d.decision_id, success=False)
    reflection = engine.reflect("a")
    assert "calibration" in reflection.summary.lower()


def test_insight_overconfidence(engine):
    d = engine.record_decision("a", "risky", confidence=0.95)
    engine.record_outcome(d.decision_id, success=False)
    engine.reflect("a")
    insights = engine.get_insights(agent_id="a", category=InsightCategory.CALIBRATION_ERROR)
    assert len(insights) >= 1


def test_get_insights_all(engine):
    for _ in range(3):
        d = engine.record_decision("a", "action", confidence=0.7)
        engine.record_outcome(d.decision_id, success=True)
    engine.reflect("a")
    assert len(engine.get_insights()) >= 1


def test_reflect_specific_decisions(engine):
    d1 = engine.record_decision("a", "action1", confidence=0.8)
    d2 = engine.record_decision("a", "action2", confidence=0.6)
    engine.record_outcome(d1.decision_id, success=True)
    engine.record_outcome(d2.decision_id, success=False)
    reflection = engine.reflect("a", decision_ids=[d1.decision_id])
    assert d1.decision_id in reflection.decision_ids
    assert d2.decision_id not in reflection.decision_ids


def test_stats_empty():
    eng = ReflectionEngine()
    stats = eng.get_stats()
    assert stats.total_decisions == 0
    assert stats.total_outcomes == 0


def test_stats_with_data(engine):
    d1 = engine.record_decision("a", "action1", confidence=0.8)
    d2 = engine.record_decision("b", "action2", confidence=0.6)
    engine.record_outcome(d1.decision_id, success=True)
    engine.record_outcome(d2.decision_id, success=False)
    engine.reflect("a")
    stats = engine.get_stats()
    assert stats.total_decisions == 2
    assert stats.total_outcomes == 2
    assert stats.total_reflections == 1
    assert stats.agents_reflecting == 2
    assert stats.success_rate == pytest.approx(0.5)


def test_multiple_agents_independent(engine):
    d1 = engine.record_decision("a", "action", confidence=1.0)
    engine.record_outcome(d1.decision_id, success=True)
    d2 = engine.record_decision("b", "action", confidence=0.9)
    engine.record_outcome(d2.decision_id, success=False)
    assert engine.get_calibration_error("a") < engine.get_calibration_error("b")
