"""Tests for counterfactual reasoning engine."""

from __future__ import annotations

import pytest

from reins.counterfactual import (
    CausalClaim,
    CausalStrength,
    CounterfactualEngine,
    CounterfactualResult,
    Decision,
    Intervention,
    InterventionType,
    OutcomeComparison,
    WorldKind,
)


@pytest.fixture
def engine() -> CounterfactualEngine:
    return CounterfactualEngine(regret_threshold=0.1, causal_confidence_min=0.6)


def test_record_decision(engine):
    d = engine.record_decision("agent-1", "deploy", outcome_value=0.8)
    assert d.agent_id == "agent-1"
    assert d.action_taken == "deploy"
    assert d.outcome_value == 0.8


def test_record_decision_with_alternatives(engine):
    d = engine.record_decision("a", "left", alternatives=["right", "stay"])
    assert "right" in d.alternatives
    assert "stay" in d.alternatives


def test_intervene(engine):
    d = engine.record_decision("a", "deploy", outcome_value=0.5)
    iv = engine.intervene(d.decision_id, "rollback", simulated_outcome=0.9)
    assert iv is not None
    assert iv.original_action == "deploy"
    assert iv.counterfactual_action == "rollback"


def test_intervene_nonexistent(engine):
    result = engine.intervene("fake-id", "anything")
    assert result is None


def test_analyze_decision_no_counterfactuals(engine):
    d = engine.record_decision("a", "act", outcome_value=1.0)
    result = engine.analyze_decision(d.decision_id)
    assert result is not None
    assert result.regret == 0.0
    assert result.comparison == OutcomeComparison.EQUIVALENT


def test_analyze_with_better_counterfactual(engine):
    d = engine.record_decision("a", "slow_path", outcome_value=0.3)
    engine.intervene(d.decision_id, "fast_path", simulated_outcome=0.9)
    result = engine.analyze_decision(d.decision_id)
    assert result.regret == pytest.approx(0.6, abs=0.01)
    assert result.comparison == OutcomeComparison.WORSE


def test_analyze_with_worse_counterfactual(engine):
    d = engine.record_decision("a", "good_choice", outcome_value=0.9)
    engine.intervene(d.decision_id, "bad_choice", simulated_outcome=0.2)
    result = engine.analyze_decision(d.decision_id)
    assert result.regret == 0.0
    assert result.comparison == OutcomeComparison.BETTER


def test_compute_regret(engine):
    d = engine.record_decision("a", "action", outcome_value=0.4)
    engine.intervene(d.decision_id, "alt1", simulated_outcome=0.8)
    engine.intervene(d.decision_id, "alt2", simulated_outcome=0.6)
    regret = engine.compute_regret(d.decision_id)
    assert regret == pytest.approx(0.4, abs=0.01)


def test_high_regret_decisions(engine):
    d1 = engine.record_decision("a", "bad", outcome_value=0.1)
    engine.intervene(d1.decision_id, "good", simulated_outcome=0.9)
    d2 = engine.record_decision("b", "fine", outcome_value=0.8)
    engine.intervene(d2.decision_id, "also_fine", simulated_outcome=0.82)
    high = engine.get_high_regret_decisions()
    assert len(high) == 1
    assert high[0].decision_id == d1.decision_id


def test_assess_causality_necessary_and_sufficient(engine):
    d = engine.record_decision("a", "critical_fix", outcome_value=1.0)
    engine.intervene(d.decision_id, "skip", simulated_outcome=0.2)
    engine.intervene(d.decision_id, "delay", simulated_outcome=0.3)
    engine.intervene(d.decision_id, "partial", simulated_outcome=0.4)
    strength = engine.assess_causality(d.decision_id)
    assert strength == CausalStrength.NECESSARY_AND_SUFFICIENT


def test_assess_causality_irrelevant(engine):
    d = engine.record_decision("a", "noop", outcome_value=0.5)
    engine.intervene(d.decision_id, "other", simulated_outcome=0.5)
    strength = engine.assess_causality(d.decision_id)
    assert strength == CausalStrength.IRRELEVANT


def test_assess_causality_no_interventions(engine):
    d = engine.record_decision("a", "solo", outcome_value=0.5)
    strength = engine.assess_causality(d.decision_id)
    assert strength == CausalStrength.IRRELEVANT


def test_causal_claims_generated(engine):
    d = engine.record_decision("a", "key_action", outcome_value=0.9)
    engine.intervene(d.decision_id, "alt1", simulated_outcome=0.1)
    engine.intervene(d.decision_id, "alt2", simulated_outcome=0.2)
    engine.intervene(d.decision_id, "alt3", simulated_outcome=0.15)
    result = engine.analyze_decision(d.decision_id)
    assert len(result.causal_claims) >= 1
    assert result.causal_claims[0].strength == CausalStrength.NECESSARY_AND_SUFFICIENT


def test_intervention_types(engine):
    d = engine.record_decision("a", "act", outcome_value=0.5)
    iv = engine.intervene(
        d.decision_id, "removed",
        intervention_type=InterventionType.AGENT_REMOVAL,
        simulated_outcome=0.3,
    )
    assert iv.intervention_type == InterventionType.AGENT_REMOVAL


def test_multiple_decisions_independent(engine):
    d1 = engine.record_decision("a", "x", outcome_value=0.5)
    d2 = engine.record_decision("b", "y", outcome_value=0.7)
    engine.intervene(d1.decision_id, "z", simulated_outcome=0.9)
    r1 = engine.analyze_decision(d1.decision_id)
    r2 = engine.analyze_decision(d2.decision_id)
    assert r1.regret > 0
    assert r2.regret == 0.0


def test_stats_empty():
    e = CounterfactualEngine()
    stats = e.get_stats()
    assert stats.total_decisions == 0
    assert stats.total_interventions == 0


def test_stats_with_data(engine):
    d = engine.record_decision("a", "act", outcome_value=0.5)
    engine.intervene(d.decision_id, "alt", simulated_outcome=0.8)
    stats = engine.get_stats()
    assert stats.total_decisions == 1
    assert stats.total_interventions == 1
    assert stats.total_worlds == 2


def test_context_preserved(engine):
    d = engine.record_decision("a", "act", context={"temperature": 0.7, "model": "gpt-4"})
    assert d.context["temperature"] == 0.7
    assert d.context["model"] == "gpt-4"


def test_outcome_comparison_equivalent(engine):
    d = engine.record_decision("a", "act", outcome_value=0.5)
    engine.intervene(d.decision_id, "similar", simulated_outcome=0.52)
    result = engine.analyze_decision(d.decision_id)
    assert result.comparison == OutcomeComparison.EQUIVALENT
