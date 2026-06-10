"""Tests for ethical reasoning with value alignment verification."""

from __future__ import annotations

import pytest

from reins.ethics import (
    AlignmentLevel,
    AlignmentReport,
    EthicalEvaluation,
    EthicalFramework,
    EthicalPrinciple,
    EthicalReasoner,
    EthicalViolation,
    EthicsStats,
    ValueDimension,
    ViolationSeverity,
)


@pytest.fixture
def reasoner() -> EthicalReasoner:
    return EthicalReasoner()


def test_default_principles_registered(reasoner):
    principles = reasoner.get_principles()
    assert len(principles) >= 8


def test_register_custom_principle(reasoner):
    p = EthicalPrinciple(
        name="Custom Rule",
        dimension=ValueDimension.JUSTICE,
        weight=1.5,
    )
    registered = reasoner.register_principle(p)
    assert reasoner.get_principle(registered.principle_id) is not None


def test_get_principle_not_found(reasoner):
    assert reasoner.get_principle("nonexistent") is None


def test_get_principles_by_dimension(reasoner):
    principles = reasoner.get_principles(dimension=ValueDimension.TRANSPARENCY)
    assert len(principles) >= 1
    assert all(p.dimension == ValueDimension.TRANSPARENCY for p in principles)


def test_get_principles_by_framework(reasoner):
    principles = reasoner.get_principles(framework=EthicalFramework.CONSEQUENTIALIST)
    assert len(principles) >= 1


def test_evaluate_no_violations(reasoner):
    principles = reasoner.get_principles()
    satisfied = [p.principle_id for p in principles[:3]]
    evaluation = reasoner.evaluate("agent-1", "help user", satisfied=satisfied)
    assert evaluation.alignment == AlignmentLevel.FULLY_ALIGNED
    assert evaluation.score == pytest.approx(1.0)


def test_evaluate_with_violations(reasoner):
    principles = reasoner.get_principles()
    soft_principles = [p for p in principles if not p.hard_constraint]
    violated = [soft_principles[0].principle_id] if soft_principles else []
    satisfied = [p.principle_id for p in principles[:2]]
    evaluation = reasoner.evaluate("agent-1", "risky action",
                                   satisfied=satisfied, violated=violated)
    assert evaluation.score < 1.0


def test_evaluate_hard_constraint_violation(reasoner):
    principles = reasoner.get_principles()
    hard = [p for p in principles if p.hard_constraint]
    assert len(hard) >= 1
    evaluation = reasoner.evaluate("agent-1", "harmful action",
                                   violated=[hard[0].principle_id])
    assert evaluation.alignment == AlignmentLevel.CRITICALLY_MISALIGNED


def test_evaluate_creates_violations(reasoner):
    principles = reasoner.get_principles()
    reasoner.evaluate("agent-1", "bad action", violated=[principles[0].principle_id])
    violations = reasoner.get_violations(agent_id="agent-1")
    assert len(violations) >= 1


def test_evaluate_no_violations_no_records(reasoner):
    principles = reasoner.get_principles()
    reasoner.evaluate("agent-1", "good action", satisfied=[principles[0].principle_id])
    violations = reasoner.get_violations(agent_id="agent-1")
    assert len(violations) == 0


def test_get_evaluations_all(reasoner):
    reasoner.evaluate("a", "action1")
    reasoner.evaluate("b", "action2")
    assert len(reasoner.get_evaluations()) == 2


def test_get_evaluations_by_agent(reasoner):
    reasoner.evaluate("a", "action1")
    reasoner.evaluate("b", "action2")
    evals = reasoner.get_evaluations(agent_id="a")
    assert len(evals) == 1


def test_get_violations_by_severity(reasoner):
    principles = reasoner.get_principles()
    hard = [p for p in principles if p.hard_constraint]
    soft = [p for p in principles if not p.hard_constraint]
    reasoner.evaluate("a", "action1", violated=[hard[0].principle_id])
    reasoner.evaluate("a", "action2", violated=[soft[0].principle_id] if soft else [])
    critical = reasoner.get_violations(severity=ViolationSeverity.CRITICAL)
    assert len(critical) >= 1


def test_alignment_report_clean(reasoner):
    principles = reasoner.get_principles()
    reasoner.evaluate("agent-1", "good", satisfied=[principles[0].principle_id])
    report = reasoner.get_alignment_report("agent-1")
    assert report.overall_score > 0.5
    assert report.total_evaluations == 1
    assert report.total_violations == 0


def test_alignment_report_with_violations(reasoner):
    principles = reasoner.get_principles()
    hard = [p for p in principles if p.hard_constraint]
    reasoner.evaluate("agent-1", "bad", violated=[hard[0].principle_id])
    report = reasoner.get_alignment_report("agent-1")
    assert report.overall_alignment == AlignmentLevel.CRITICALLY_MISALIGNED
    assert report.critical_violations >= 1


def test_alignment_report_empty(reasoner):
    report = reasoner.get_alignment_report("unknown")
    assert report.total_evaluations == 0


def test_alignment_report_by_dimension(reasoner):
    principles = reasoner.get_principles()
    transparency = [p for p in principles if p.dimension == ValueDimension.TRANSPARENCY]
    if transparency:
        reasoner.evaluate("a", "action", satisfied=[transparency[0].principle_id])
        report = reasoner.get_alignment_report("a")
        assert ValueDimension.TRANSPARENCY.value in report.by_dimension


def test_check_hard_constraints_blocked(reasoner):
    principles = reasoner.get_principles()
    hard = [p for p in principles if p.hard_constraint]
    blocked = reasoner.check_hard_constraints("action", [hard[0].principle_id])
    assert len(blocked) == 1


def test_check_hard_constraints_none_violated(reasoner):
    principles = reasoner.get_principles()
    soft = [p for p in principles if not p.hard_constraint]
    if soft:
        blocked = reasoner.check_hard_constraints("action", [soft[0].principle_id])
        assert len(blocked) == 0


def test_reasoning_includes_action(reasoner):
    principles = reasoner.get_principles()
    evaluation = reasoner.evaluate("a", "deploy to prod",
                                   satisfied=[principles[0].principle_id])
    assert "deploy to prod" in evaluation.reasoning


def test_reasoning_includes_satisfied(reasoner):
    principles = reasoner.get_principles()
    evaluation = reasoner.evaluate("a", "action",
                                   satisfied=[principles[0].principle_id])
    assert "Satisfies" in evaluation.reasoning


def test_reasoning_includes_violated(reasoner):
    principles = reasoner.get_principles()
    evaluation = reasoner.evaluate("a", "action",
                                   violated=[principles[0].principle_id])
    assert "Violates" in evaluation.reasoning


def test_stats_empty():
    r = EthicalReasoner()
    stats = r.get_stats()
    assert stats.total_principles >= 8
    assert stats.total_evaluations == 0
    assert stats.total_violations == 0


def test_stats_with_data(reasoner):
    principles = reasoner.get_principles()
    reasoner.evaluate("a", "action1", satisfied=[principles[0].principle_id])
    reasoner.evaluate("b", "action2", violated=[principles[1].principle_id])
    stats = reasoner.get_stats()
    assert stats.total_evaluations == 2
    assert stats.agents_evaluated == 2
    assert stats.avg_alignment_score > 0


def test_metadata_preserved(reasoner):
    evaluation = reasoner.evaluate("a", "action", metadata={"context": "testing"})
    assert evaluation.metadata == {"context": "testing"}


def test_multiple_agents_independent(reasoner):
    principles = reasoner.get_principles()
    reasoner.evaluate("a", "good", satisfied=[principles[0].principle_id])
    reasoner.evaluate("b", "bad", violated=[principles[0].principle_id])
    report_a = reasoner.get_alignment_report("a")
    report_b = reasoner.get_alignment_report("b")
    assert report_a.overall_score > report_b.overall_score
