"""Tests for interpretability engine."""

from __future__ import annotations

import pytest

from reins.interpretability import (
    Audience,
    Explanation,
    ExplanationKind,
    Factor,
    Fidelity,
    InterpretabilityEngine,
)


@pytest.fixture
def engine() -> InterpretabilityEngine:
    return InterpretabilityEngine(min_contribution=0.05)


def test_record_decision(engine):
    d = engine.record_decision("agent-1", "deploy", inputs={"version": "2.0"})
    assert d.agent_id == "agent-1"
    assert d.action == "deploy"


def test_explain_by_attribution(engine):
    d = engine.record_decision("a", "scale_up")
    factors = [("cpu_usage", 0.6, "CPU at 90%"), ("memory", 0.3, "Memory at 70%")]
    exp = engine.explain_by_attribution(d.decision_id, factors)
    assert exp is not None
    assert exp.kind == ExplanationKind.FEATURE_ATTRIBUTION
    assert len(exp.factors) == 2
    assert exp.factors[0].name == "cpu_usage"


def test_attribution_filters_small_contributions(engine):
    d = engine.record_decision("a", "act")
    factors = [("big", 0.8, ""), ("tiny", 0.01, ""), ("medium", 0.15, "")]
    exp = engine.explain_by_attribution(d.decision_id, factors)
    names = [f.name for f in exp.factors]
    assert "tiny" not in names
    assert "big" in names


def test_attribution_nonexistent_decision(engine):
    result = engine.explain_by_attribution("fake", [("x", 0.5, "")])
    assert result is None


def test_explain_contrastive(engine):
    d = engine.record_decision("a", "retry")
    factors = [("error_rate", 0.7, "High error rate"), ("cost", -0.2, "Retry is cheap")]
    exp = engine.explain_contrastive(d.decision_id, "abort", factors)
    assert exp is not None
    assert exp.kind == ExplanationKind.CONTRASTIVE
    assert "retry" in exp.summary
    assert "abort" in exp.summary


def test_contrastive_nonexistent(engine):
    result = engine.explain_contrastive("fake", "x", [])
    assert result is None


def test_explain_chain_of_thought(engine):
    d = engine.record_decision("a", "refactor")
    steps = ["Identified code smell", "Found 3 duplications", "Applied extract method"]
    exp = engine.explain_chain_of_thought(d.decision_id, steps)
    assert exp is not None
    assert exp.kind == ExplanationKind.CHAIN_OF_THOUGHT
    assert len(exp.factors) == 3
    assert exp.fidelity == Fidelity.HIGH


def test_chain_of_thought_long(engine):
    d = engine.record_decision("a", "complex_action")
    steps = [f"step {i}" for i in range(10)]
    exp = engine.explain_chain_of_thought(d.decision_id, steps)
    assert "10 steps total" in exp.summary


def test_chain_of_thought_nonexistent(engine):
    result = engine.explain_chain_of_thought("fake", ["step"])
    assert result is None


def test_get_explanations_by_decision(engine):
    d1 = engine.record_decision("a", "x")
    d2 = engine.record_decision("b", "y")
    engine.explain_by_attribution(d1.decision_id, [("f", 0.5, "")])
    engine.explain_by_attribution(d2.decision_id, [("g", 0.6, "")])
    results = engine.get_explanations(decision_id=d1.decision_id)
    assert len(results) == 1


def test_get_explanations_by_kind(engine):
    d = engine.record_decision("a", "act")
    engine.explain_by_attribution(d.decision_id, [("f", 0.5, "")])
    engine.explain_chain_of_thought(d.decision_id, ["step1"])
    results = engine.get_explanations(kind=ExplanationKind.CHAIN_OF_THOUGHT)
    assert len(results) == 1


def test_get_explanations_by_audience(engine):
    d = engine.record_decision("a", "act")
    engine.explain_by_attribution(d.decision_id, [("f", 0.5, "")], audience=Audience.AUDITOR)
    engine.explain_by_attribution(d.decision_id, [("g", 0.3, "")], audience=Audience.END_USER)
    results = engine.get_explanations(audience=Audience.AUDITOR)
    assert len(results) == 1


def test_simplify_for_end_user(engine):
    d = engine.record_decision("a", "act")
    factors = [(f"f{i}", 0.1, f"desc {i}") for i in range(8)]
    exp = engine.explain_by_attribution(d.decision_id, factors)
    simplified = engine.simplify_for_audience(exp, Audience.END_USER)
    assert simplified.audience == Audience.END_USER
    assert len(simplified.factors) <= 3


def test_simplify_for_operator(engine):
    d = engine.record_decision("a", "act")
    factors = [(f"f{i}", 0.1, f"desc {i}") for i in range(8)]
    exp = engine.explain_by_attribution(d.decision_id, factors)
    simplified = engine.simplify_for_audience(exp, Audience.OPERATOR)
    assert len(simplified.factors) <= 5


def test_fidelity_high(engine):
    d = engine.record_decision("a", "act")
    factors = [("dominant", 0.9, "")]
    exp = engine.explain_by_attribution(d.decision_id, factors)
    assert exp.fidelity == Fidelity.HIGH


def test_fidelity_medium(engine):
    d = engine.record_decision("a", "act")
    factors = [("partial", 0.6, "")]
    exp = engine.explain_by_attribution(d.decision_id, factors)
    assert exp.fidelity == Fidelity.MEDIUM


def test_fidelity_low(engine):
    d = engine.record_decision("a", "act")
    factors = [("weak", 0.1, "")]
    exp = engine.explain_by_attribution(d.decision_id, factors)
    assert exp.fidelity == Fidelity.LOW


def test_stats_empty():
    e = InterpretabilityEngine()
    stats = e.get_stats()
    assert stats.total_decisions == 0
    assert stats.total_explanations == 0
    assert stats.coverage == 0.0


def test_stats_with_data(engine):
    d1 = engine.record_decision("a", "x")
    d2 = engine.record_decision("b", "y")
    engine.explain_by_attribution(d1.decision_id, [("f", 0.5, "")])
    stats = engine.get_stats()
    assert stats.total_decisions == 2
    assert stats.total_explanations == 1
    assert stats.coverage == 0.5


def test_factor_direction(engine):
    d = engine.record_decision("a", "act")
    factors = [("positive_f", 0.5, ""), ("negative_f", -0.3, "")]
    exp = engine.explain_by_attribution(d.decision_id, factors)
    pos = [f for f in exp.factors if f.direction == "positive"]
    neg = [f for f in exp.factors if f.direction == "negative"]
    assert len(pos) == 1
    assert len(neg) == 1
