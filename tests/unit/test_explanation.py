"""Tests for explanation engine with causal attribution and counterfactual reasoning."""

from __future__ import annotations

import pytest

from reins.explanation import (
    AudienceLevel,
    Counterfactual,
    DecisionFactor,
    DecisionRecord,
    Explanation,
    ExplanationDepth,
    ExplanationEngine,
    ExplanationStats,
    FactorKind,
)


@pytest.fixture
def engine() -> ExplanationEngine:
    return ExplanationEngine()


def _factor(kind=FactorKind.CAUSAL, description="test factor", weight=1.0, confidence=0.9):
    return DecisionFactor(kind=kind, description=description, weight=weight, confidence=confidence)


def test_record_decision(engine):
    record = engine.record_decision("agent-1", "deploy service")
    assert record.agent_id == "agent-1"
    assert record.action == "deploy service"


def test_record_decision_with_factors(engine):
    factors = [_factor(description="high confidence"), _factor(kind=FactorKind.SUPPORTING)]
    record = engine.record_decision("agent-1", "deploy", factors=factors)
    assert len(record.factors) == 2


def test_record_decision_with_alternatives(engine):
    record = engine.record_decision("agent-1", "deploy", alternatives=["rollback", "wait"])
    assert "rollback" in record.alternatives_considered


def test_get_decision(engine):
    record = engine.record_decision("agent-1", "deploy")
    retrieved = engine.get_decision(record.decision_id)
    assert retrieved is not None
    assert retrieved.decision_id == record.decision_id


def test_get_decision_not_found(engine):
    assert engine.get_decision("nonexistent") is None


def test_get_decisions_all(engine):
    engine.record_decision("a", "action1")
    engine.record_decision("b", "action2")
    assert len(engine.get_decisions()) == 2


def test_get_decisions_by_agent(engine):
    engine.record_decision("a", "action1")
    engine.record_decision("b", "action2")
    decisions = engine.get_decisions(agent_id="a")
    assert len(decisions) == 1
    assert decisions[0].agent_id == "a"


def test_explain_basic(engine):
    record = engine.record_decision("agent-1", "deploy service")
    explanation = engine.explain(record.decision_id)
    assert explanation is not None
    assert "deploy service" in explanation.summary


def test_explain_nonexistent(engine):
    assert engine.explain("nonexistent") is None


def test_explain_brief_depth(engine):
    record = engine.record_decision("agent-1", "deploy")
    explanation = engine.explain(record.decision_id, depth=ExplanationDepth.BRIEF)
    assert explanation.depth == ExplanationDepth.BRIEF
    assert "Chose to" in explanation.summary


def test_explain_detailed_with_factors(engine):
    factors = [
        _factor(kind=FactorKind.CAUSAL, description="tests passed"),
        _factor(kind=FactorKind.SUPPORTING, description="low risk"),
        _factor(kind=FactorKind.INHIBITING, description="peak traffic"),
    ]
    record = engine.record_decision("agent-1", "deploy", factors=factors)
    explanation = engine.explain(record.decision_id, depth=ExplanationDepth.DETAILED)
    assert "tests passed" in explanation.summary
    assert "low risk" in explanation.summary
    assert "peak traffic" in explanation.summary


def test_explain_technical_includes_alternatives(engine):
    record = engine.record_decision("agent-1", "deploy",
                                    alternatives=["rollback", "wait"],
                                    factors=[_factor()])
    explanation = engine.explain(record.decision_id, depth=ExplanationDepth.TECHNICAL)
    assert "rollback" in explanation.summary or "alternatives" in explanation.summary


def test_explain_end_user_audience(engine):
    factors = [_factor(kind=FactorKind.CAUSAL, description="complex reason")]
    record = engine.record_decision("agent-1", "deploy", factors=factors)
    explanation = engine.explain(record.decision_id, audience=AudienceLevel.END_USER)
    assert explanation.audience == AudienceLevel.END_USER
    assert "complex reason" not in explanation.summary


def test_counterfactuals_from_alternatives(engine):
    record = engine.record_decision("agent-1", "deploy", alternatives=["rollback"])
    explanation = engine.explain(record.decision_id)
    assert len(explanation.counterfactuals) >= 1
    assert any("rollback" in cf.condition for cf in explanation.counterfactuals)


def test_counterfactuals_from_low_confidence_factors(engine):
    factors = [_factor(confidence=0.6)]
    record = engine.record_decision("agent-1", "deploy", factors=factors)
    explanation = engine.explain(record.decision_id)
    assert len(explanation.counterfactuals) >= 1


def test_confidence_with_factors(engine):
    factors = [_factor(confidence=0.9, weight=2.0)]
    record = engine.record_decision("agent-1", "deploy", factors=factors)
    explanation = engine.explain(record.decision_id)
    assert explanation.confidence > 0.5


def test_confidence_without_factors(engine):
    record = engine.record_decision("agent-1", "deploy")
    explanation = engine.explain(record.decision_id)
    assert explanation.confidence == pytest.approx(0.3)


def test_confidence_increases_with_causal_factors(engine):
    factors = [
        _factor(kind=FactorKind.CAUSAL, confidence=0.9),
        _factor(kind=FactorKind.CAUSAL, confidence=0.9),
        _factor(kind=FactorKind.CAUSAL, confidence=0.9),
    ]
    record = engine.record_decision("agent-1", "deploy", factors=factors)
    explanation = engine.explain(record.decision_id)
    assert explanation.confidence > 0.9


def test_add_counterfactual(engine):
    record = engine.record_decision("agent-1", "deploy")
    cf = engine.add_counterfactual(
        record.decision_id, "If tests had failed",
        "Would have rolled back", likelihood=0.8
    )
    assert cf is not None
    assert cf.condition == "If tests had failed"


def test_add_counterfactual_nonexistent(engine):
    assert engine.add_counterfactual("nonexistent", "x", "y") is None


def test_get_explanations_all(engine):
    r1 = engine.record_decision("a", "action1")
    r2 = engine.record_decision("b", "action2")
    engine.explain(r1.decision_id)
    engine.explain(r2.decision_id)
    assert len(engine.get_explanations()) == 2


def test_get_explanations_by_decision(engine):
    r1 = engine.record_decision("a", "action1")
    r2 = engine.record_decision("b", "action2")
    engine.explain(r1.decision_id)
    engine.explain(r2.decision_id)
    explanations = engine.get_explanations(decision_id=r1.decision_id)
    assert len(explanations) == 1


def test_get_explanations_by_audience(engine):
    record = engine.record_decision("a", "action")
    engine.explain(record.decision_id, audience=AudienceLevel.DEVELOPER)
    engine.explain(record.decision_id, audience=AudienceLevel.AUDITOR)
    dev_explanations = engine.get_explanations(audience=AudienceLevel.DEVELOPER)
    assert len(dev_explanations) == 1


def test_stats_empty():
    e = ExplanationEngine()
    stats = e.get_stats()
    assert stats.total_decisions == 0
    assert stats.total_explanations == 0


def test_stats_with_data(engine):
    factors = [_factor(), _factor(kind=FactorKind.SUPPORTING)]
    record = engine.record_decision("a", "deploy", factors=factors)
    engine.explain(record.decision_id, depth=ExplanationDepth.DETAILED)
    stats = engine.get_stats()
    assert stats.total_decisions == 1
    assert stats.total_explanations == 1
    assert stats.avg_factors_per_decision == 2.0
    assert stats.avg_confidence > 0
    assert ExplanationDepth.DETAILED.value in stats.by_depth


def test_multiple_agents_independent(engine):
    engine.record_decision("a", "action1")
    engine.record_decision("b", "action2")
    decisions_a = engine.get_decisions(agent_id="a")
    decisions_b = engine.get_decisions(agent_id="b")
    assert len(decisions_a) == 1
    assert len(decisions_b) == 1


def test_metadata_preserved(engine):
    record = engine.record_decision("a", "deploy", context={"env": "prod"})
    assert record.context == {"env": "prod"}
