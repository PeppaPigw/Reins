"""Tests for autonomy engine with self-governance and escalation."""

from __future__ import annotations

import pytest

from reins.autonomy import (
    AutonomyBoundary,
    AutonomyDecision,
    AutonomyEngine,
    AutonomyLevel,
    AutonomyProfile,
    AutonomyStats,
    DecisionOutcome,
    EscalationReason,
    EscalationRequest,
)


@pytest.fixture
def engine() -> AutonomyEngine:
    return AutonomyEngine()


def test_register_agent(engine):
    profile = engine.register_agent("agent-1", level=AutonomyLevel.GUIDED)
    assert profile.agent_id == "agent-1"
    assert profile.current_level == AutonomyLevel.GUIDED


def test_get_profile(engine):
    engine.register_agent("agent-1")
    assert engine.get_profile("agent-1") is not None
    assert engine.get_profile("nonexistent") is None


def test_set_level(engine):
    engine.register_agent("agent-1")
    updated = engine.set_level("agent-1", AutonomyLevel.AUTONOMOUS)
    assert updated.current_level == AutonomyLevel.AUTONOMOUS


def test_set_level_not_found(engine):
    assert engine.set_level("nonexistent", AutonomyLevel.GUIDED) is None


def test_evaluate_supervised_escalates(engine):
    engine.register_agent("agent-1", level=AutonomyLevel.SUPERVISED)
    decision = engine.evaluate_action("agent-1", "deploy", confidence=0.9)
    assert decision.outcome == DecisionOutcome.ESCALATED


def test_evaluate_autonomous_approves(engine):
    engine.register_agent("agent-1", level=AutonomyLevel.AUTONOMOUS)
    decision = engine.evaluate_action("agent-1", "deploy", confidence=0.8, risk_score=0.2)
    assert decision.outcome == DecisionOutcome.APPROVED


def test_evaluate_forbidden_action(engine):
    engine.register_agent("agent-1", level=AutonomyLevel.FULLY_AUTONOMOUS)
    engine.set_boundary("safety", forbidden_actions=["delete_all"])
    decision = engine.evaluate_action("agent-1", "delete_all", confidence=1.0)
    assert decision.outcome == DecisionOutcome.DENIED


def test_evaluate_high_risk_escalates(engine):
    engine.register_agent("agent-1", level=AutonomyLevel.GUIDED)
    engine.set_boundary("ops", risk_tolerance=0.3)
    decision = engine.evaluate_action("agent-1", "risky_op", confidence=0.8, risk_score=0.9)
    assert decision.outcome == DecisionOutcome.ESCALATED


def test_evaluate_low_confidence_escalates(engine):
    engine.register_agent("agent-1", level=AutonomyLevel.SEMI_AUTONOMOUS)
    decision = engine.evaluate_action("agent-1", "uncertain_op", confidence=0.1, risk_score=0.1)
    assert decision.outcome == DecisionOutcome.ESCALATED


def test_evaluate_semi_autonomous_approves_safe(engine):
    engine.register_agent("agent-1", level=AutonomyLevel.SEMI_AUTONOMOUS)
    decision = engine.evaluate_action("agent-1", "safe_op", confidence=0.8, risk_score=0.2)
    assert decision.outcome == DecisionOutcome.APPROVED


def test_evaluate_guided_high_confidence(engine):
    engine.register_agent("agent-1", level=AutonomyLevel.GUIDED)
    decision = engine.evaluate_action("agent-1", "simple_op", confidence=0.95, risk_score=0.05)
    assert decision.outcome == DecisionOutcome.APPROVED


def test_evaluate_unregistered_agent(engine):
    decision = engine.evaluate_action("new-agent", "action", confidence=0.5)
    assert decision.outcome == DecisionOutcome.ESCALATED


def test_resolve_escalation(engine):
    engine.register_agent("agent-1", level=AutonomyLevel.SUPERVISED)
    engine.evaluate_action("agent-1", "deploy")
    escalations = engine.get_escalations(unresolved_only=True)
    assert len(escalations) == 1
    resolved = engine.resolve_escalation(escalations[0].request_id, DecisionOutcome.APPROVED)
    assert resolved.resolved is True
    assert resolved.resolution == DecisionOutcome.APPROVED


def test_resolve_escalation_not_found(engine):
    assert engine.resolve_escalation("nonexistent", DecisionOutcome.DENIED) is None


def test_get_escalations_by_agent(engine):
    engine.register_agent("a", level=AutonomyLevel.SUPERVISED)
    engine.register_agent("b", level=AutonomyLevel.SUPERVISED)
    engine.evaluate_action("a", "op1")
    engine.evaluate_action("b", "op2")
    assert len(engine.get_escalations(agent_id="a")) == 1


def test_get_decisions_by_outcome(engine):
    engine.register_agent("a", level=AutonomyLevel.AUTONOMOUS)
    engine.register_agent("b", level=AutonomyLevel.SUPERVISED)
    engine.evaluate_action("a", "op1", confidence=0.9, risk_score=0.1)
    engine.evaluate_action("b", "op2")
    approved = engine.get_decisions(outcome=DecisionOutcome.APPROVED)
    assert len(approved) == 1


def test_promote_agent(engine):
    engine.register_agent("agent-1", level=AutonomyLevel.GUIDED)
    promoted = engine.promote_agent("agent-1")
    assert promoted.current_level == AutonomyLevel.SEMI_AUTONOMOUS


def test_promote_at_max(engine):
    engine.register_agent("agent-1", level=AutonomyLevel.FULLY_AUTONOMOUS)
    result = engine.promote_agent("agent-1")
    assert result.current_level == AutonomyLevel.FULLY_AUTONOMOUS


def test_promote_not_found(engine):
    assert engine.promote_agent("nonexistent") is None


def test_demote_agent(engine):
    engine.register_agent("agent-1", level=AutonomyLevel.AUTONOMOUS)
    demoted = engine.demote_agent("agent-1")
    assert demoted.current_level == AutonomyLevel.SEMI_AUTONOMOUS


def test_demote_at_min(engine):
    engine.register_agent("agent-1", level=AutonomyLevel.SUPERVISED)
    result = engine.demote_agent("agent-1")
    assert result.current_level == AutonomyLevel.SUPERVISED


def test_demote_not_found(engine):
    assert engine.demote_agent("nonexistent") is None


def test_set_boundary(engine):
    boundary = engine.set_boundary("safety", max_level=AutonomyLevel.GUIDED,
                                   forbidden_actions=["rm_rf"])
    assert boundary.name == "safety"
    assert "rm_rf" in boundary.forbidden_actions


def test_stats_empty(engine):
    stats = engine.get_stats()
    assert stats.total_agents == 0
    assert stats.total_decisions == 0


def test_stats_populated(engine):
    engine.register_agent("a", level=AutonomyLevel.AUTONOMOUS)
    engine.register_agent("b", level=AutonomyLevel.SUPERVISED)
    engine.evaluate_action("a", "op1", confidence=0.9, risk_score=0.1)
    engine.evaluate_action("b", "op2", confidence=0.5)
    stats = engine.get_stats()
    assert stats.total_agents == 2
    assert stats.total_decisions == 2
    assert stats.auto_approved >= 1
    assert "autonomous" in stats.by_level
