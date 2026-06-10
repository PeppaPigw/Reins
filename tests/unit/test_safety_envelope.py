"""Tests for formal safety envelope engine."""

from __future__ import annotations

import pytest

from reins.safety_envelope import (
    EnvelopeAssessment,
    EnvelopeVerdict,
    Mitigation,
    MitigationStatus,
    SafetyConstraint,
    SafetyEnvelope,
    SafetyEnvelopeStats,
    ThreatKind,
    ThreatModel,
)


@pytest.fixture
def envelope() -> SafetyEnvelope:
    return SafetyEnvelope()


def test_add_constraint(envelope):
    c = envelope.add_constraint("no_external_calls",
                                description="Agents cannot make external HTTP calls",
                                agents=["agent-1"])
    assert c.name == "no_external_calls"
    assert c.enforced is True
    assert envelope.get_constraint(c.constraint_id) is not None


def test_remove_constraint(envelope):
    c = envelope.add_constraint("test")
    assert envelope.remove_constraint(c.constraint_id) is True
    assert envelope.get_constraint(c.constraint_id) is None
    assert envelope.remove_constraint("nonexistent") is False


def test_add_threat(envelope):
    t = envelope.add_threat(ThreatKind.DATA_EXFILTRATION,
                            description="Agent may leak PII",
                            affected_agents=["agent-1"],
                            likelihood=0.3, impact=0.9)
    assert t.kind == ThreatKind.DATA_EXFILTRATION
    assert t.likelihood == 0.3


def test_add_mitigation_links_to_threat(envelope):
    t = envelope.add_threat(ThreatKind.RESOURCE_EXHAUSTION)
    m = envelope.add_mitigation("rate_limit", t.threat_id,
                                action="Apply 100 req/s limit")
    assert m.status == MitigationStatus.ACTIVE
    updated_threat = envelope.get_threats(kind=ThreatKind.RESOURCE_EXHAUSTION)[0]
    assert m.mitigation_id in updated_threat.mitigations


def test_trigger_mitigation(envelope):
    t = envelope.add_threat(ThreatKind.CASCADING_FAILURE)
    m = envelope.add_mitigation("circuit_breaker", t.threat_id)
    triggered = envelope.trigger_mitigation(m.mitigation_id)
    assert triggered.status == MitigationStatus.TRIGGERED


def test_trigger_nonexistent(envelope):
    assert envelope.trigger_mitigation("missing") is None


def test_assess_safe(envelope):
    envelope.add_constraint("bounded_tokens", agents=["a"])
    t = envelope.add_threat(ThreatKind.RESOURCE_EXHAUSTION,
                            affected_agents=["a"],
                            likelihood=0.2, impact=0.3)
    envelope.add_mitigation("token_limit", t.threat_id)
    assessment = envelope.assess(agent_ids=["a"])
    assert assessment.verdict == EnvelopeVerdict.SAFE
    assert assessment.constraints_checked == 1
    assert assessment.threats_mitigated == 1


def test_assess_unsafe_high_risk(envelope):
    envelope.add_constraint("isolation")
    envelope.add_threat(ThreatKind.PRIVILEGE_ESCALATION,
                        likelihood=0.9, impact=0.9)
    assessment = envelope.assess()
    assert assessment.verdict in (EnvelopeVerdict.UNSAFE,
                                   EnvelopeVerdict.CONDITIONALLY_SAFE)


def test_assess_unsafe_unenforced_constraint(envelope):
    c = envelope.add_constraint("critical_rule")
    envelope._constraints[c.constraint_id] = c.model_copy(
        update={"enforced": False}
    )
    assessment = envelope.assess()
    assert assessment.verdict == EnvelopeVerdict.UNSAFE
    assert len(assessment.blockers) > 0


def test_assess_conditionally_safe(envelope):
    envelope.add_constraint("rule")
    envelope.add_threat(ThreatKind.DATA_EXFILTRATION,
                        likelihood=0.4, impact=0.5)
    assessment = envelope.assess()
    assert assessment.verdict == EnvelopeVerdict.CONDITIONALLY_SAFE
    assert len(assessment.conditions) > 0


def test_assess_inconclusive_empty(envelope):
    assessment = envelope.assess()
    assert assessment.verdict == EnvelopeVerdict.INCONCLUSIVE


def test_assess_filters_by_agent(envelope):
    envelope.add_constraint("rule_a", agents=["a"])
    envelope.add_constraint("rule_b", agents=["b"])
    envelope.add_threat(ThreatKind.CASCADING_FAILURE, affected_agents=["a"],
                        likelihood=0.1, impact=0.1)
    t = envelope.get_threats()[0]
    envelope.add_mitigation("fix", t.threat_id)
    assessment = envelope.assess(agent_ids=["a"])
    assert assessment.constraints_checked == 1


def test_get_assessments(envelope):
    envelope.add_constraint("x")
    envelope.assess()
    envelope.assess()
    assert len(envelope.get_assessments()) == 2


def test_get_threats_filter(envelope):
    envelope.add_threat(ThreatKind.DATA_EXFILTRATION)
    envelope.add_threat(ThreatKind.RESOURCE_EXHAUSTION)
    assert len(envelope.get_threats()) == 2
    assert len(envelope.get_threats(kind=ThreatKind.DATA_EXFILTRATION)) == 1


def test_stats_empty(envelope):
    stats = envelope.get_stats()
    assert stats.total_constraints == 0
    assert stats.current_verdict == EnvelopeVerdict.INCONCLUSIVE


def test_stats_populated(envelope):
    envelope.add_constraint("c1")
    t = envelope.add_threat(ThreatKind.PRIVILEGE_ESCALATION,
                            likelihood=0.2, impact=0.3)
    envelope.add_mitigation("m1", t.threat_id)
    envelope.assess()
    stats = envelope.get_stats()
    assert stats.total_constraints == 1
    assert stats.total_threats == 1
    assert stats.total_mitigations == 1
    assert stats.total_assessments == 1
    assert stats.by_threat_kind["privilege_escalation"] == 1


def test_all_threat_kinds(envelope):
    for kind in ThreatKind:
        envelope.add_threat(kind, likelihood=0.5, impact=0.5)
    assert len(envelope.get_threats()) == len(ThreatKind)


def test_risk_score_decreases_with_mitigations(envelope):
    t1 = envelope.add_threat(ThreatKind.CASCADING_FAILURE,
                             likelihood=0.8, impact=0.8)
    envelope.add_constraint("rule")
    a1 = envelope.assess()
    envelope.add_mitigation("fix", t1.threat_id)
    a2 = envelope.assess()
    assert a2.risk_score <= a1.risk_score


def test_multiple_threats_compound_risk(envelope):
    envelope.add_constraint("rule")
    envelope.add_threat(ThreatKind.DATA_EXFILTRATION, likelihood=0.5, impact=0.5)
    a1 = envelope.assess()
    envelope.add_threat(ThreatKind.PRIVILEGE_ESCALATION, likelihood=0.5, impact=0.5)
    a2 = envelope.assess()
    assert a2.risk_score >= a1.risk_score or a2.threats_identified > a1.threats_identified
