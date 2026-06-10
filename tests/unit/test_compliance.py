"""Tests for compliance and audit trail with tamper-evident logging."""

from __future__ import annotations

import pytest

from reins.compliance import (
    AuditEntry,
    AuditReport,
    AuditSeverity,
    ComplianceEngine,
    ComplianceEvaluation,
    ComplianceRule,
    ComplianceStats,
    ComplianceStatus,
    RuleCategory,
)


@pytest.fixture
def engine() -> ComplianceEngine:
    return ComplianceEngine()


@pytest.fixture
def rules(engine) -> list[ComplianceRule]:
    r1 = engine.register_rule(ComplianceRule(
        name="Data Encryption", category=RuleCategory.DATA_PRIVACY, mandatory=True,
    ))
    r2 = engine.register_rule(ComplianceRule(
        name="Access Logging", category=RuleCategory.AUDIT_TRAIL, mandatory=False,
    ))
    r3 = engine.register_rule(ComplianceRule(
        name="Role Check", category=RuleCategory.ACCESS_CONTROL, mandatory=True,
    ))
    return [r1, r2, r3]


def test_register_rule(engine):
    rule = engine.register_rule(ComplianceRule(name="Test Rule"))
    assert engine.get_rule(rule.rule_id) is not None


def test_get_rule_not_found(engine):
    assert engine.get_rule("nonexistent") is None


def test_get_rules_all(engine, rules):
    assert len(engine.get_rules()) == 3


def test_get_rules_by_category(engine, rules):
    privacy_rules = engine.get_rules(category=RuleCategory.DATA_PRIVACY)
    assert len(privacy_rules) == 1
    assert privacy_rules[0].name == "Data Encryption"


def test_log_action(engine):
    entry = engine.log_action("agent-1", "read_file", resource="/etc/config")
    assert entry.agent_id == "agent-1"
    assert entry.action == "read_file"
    assert entry.severity == AuditSeverity.INFO


def test_log_action_with_severity(engine):
    entry = engine.log_action("agent-1", "delete_db", severity=AuditSeverity.CRITICAL)
    assert entry.severity == AuditSeverity.CRITICAL


def test_log_action_with_metadata(engine):
    entry = engine.log_action("agent-1", "deploy", metadata={"env": "prod"})
    assert entry.metadata == {"env": "prod"}


def test_get_entries_all(engine):
    engine.log_action("a", "action1")
    engine.log_action("b", "action2")
    assert len(engine.get_entries()) == 2


def test_get_entries_by_agent(engine):
    engine.log_action("a", "action1")
    engine.log_action("b", "action2")
    entries = engine.get_entries(agent_id="a")
    assert len(entries) == 1


def test_get_entries_by_severity(engine):
    engine.log_action("a", "action1", severity=AuditSeverity.INFO)
    engine.log_action("a", "action2", severity=AuditSeverity.HIGH)
    entries = engine.get_entries(severity=AuditSeverity.HIGH)
    assert len(entries) == 1


def test_evaluate_compliant(engine, rules):
    evaluation = engine.evaluate_action("agent-1", "safe action")
    assert evaluation.status == ComplianceStatus.COMPLIANT
    assert evaluation.rules_checked == 3
    assert evaluation.rules_failed == 0


def test_evaluate_non_compliant_mandatory(engine, rules):
    evaluation = engine.evaluate_action(
        "agent-1", "bad action", violated_ids=[rules[0].rule_id]
    )
    assert evaluation.status == ComplianceStatus.NON_COMPLIANT


def test_evaluate_partially_compliant(engine, rules):
    evaluation = engine.evaluate_action(
        "agent-1", "risky action", violated_ids=[rules[1].rule_id]
    )
    assert evaluation.status == ComplianceStatus.PARTIALLY_COMPLIANT


def test_evaluate_specific_rules(engine, rules):
    evaluation = engine.evaluate_action(
        "agent-1", "action", rule_ids=[rules[0].rule_id]
    )
    assert evaluation.rules_checked == 1


def test_evaluate_reasoning_includes_action(engine, rules):
    evaluation = engine.evaluate_action("agent-1", "deploy to prod")
    assert "deploy to prod" in evaluation.reasoning


def test_evaluate_reasoning_includes_violations(engine, rules):
    evaluation = engine.evaluate_action(
        "agent-1", "action", violated_ids=[rules[0].rule_id]
    )
    assert "Data Encryption" in evaluation.reasoning


def test_get_evaluations_all(engine, rules):
    engine.evaluate_action("a", "action1")
    engine.evaluate_action("b", "action2")
    assert len(engine.get_evaluations()) == 2


def test_get_evaluations_by_agent(engine, rules):
    engine.evaluate_action("a", "action1")
    engine.evaluate_action("b", "action2")
    evals = engine.get_evaluations(agent_id="a")
    assert len(evals) == 1


def test_get_evaluations_by_status(engine, rules):
    engine.evaluate_action("a", "good")
    engine.evaluate_action("a", "bad", violated_ids=[rules[0].rule_id])
    non_compliant = engine.get_evaluations(status=ComplianceStatus.NON_COMPLIANT)
    assert len(non_compliant) == 1


def test_audit_report_clean(engine, rules):
    engine.log_action("agent-1", "action1")
    engine.evaluate_action("agent-1", "action1")
    report = engine.get_audit_report("agent-1")
    assert report.compliance_score == 1.0
    assert report.overall_status == ComplianceStatus.COMPLIANT
    assert report.critical_violations == 0


def test_audit_report_with_violations(engine, rules):
    engine.evaluate_action("agent-1", "bad", violated_ids=[rules[0].rule_id])
    report = engine.get_audit_report("agent-1")
    assert report.compliance_score == 0.0
    assert report.overall_status == ComplianceStatus.NON_COMPLIANT
    assert report.critical_violations >= 1


def test_audit_report_violations_by_category(engine, rules):
    engine.evaluate_action("agent-1", "bad", violated_ids=[rules[0].rule_id])
    report = engine.get_audit_report("agent-1")
    assert RuleCategory.DATA_PRIVACY.value in report.violations_by_category


def test_audit_report_empty(engine):
    report = engine.get_audit_report("unknown")
    assert report.total_entries == 0
    assert report.total_evaluations == 0


def test_stats_empty():
    eng = ComplianceEngine()
    stats = eng.get_stats()
    assert stats.total_rules == 0
    assert stats.total_entries == 0
    assert stats.overall_compliance_rate == 1.0


def test_stats_with_data(engine, rules):
    engine.log_action("a", "action1", severity=AuditSeverity.HIGH)
    engine.evaluate_action("a", "action1")
    engine.evaluate_action("b", "action2", violated_ids=[rules[1].rule_id])
    stats = engine.get_stats()
    assert stats.total_rules == 3
    assert stats.total_entries == 1
    assert stats.total_evaluations == 2
    assert stats.agents_audited == 2
    assert 0 < stats.overall_compliance_rate < 1.0
    assert AuditSeverity.HIGH.value in stats.by_severity


def test_multiple_agents_independent(engine, rules):
    engine.evaluate_action("a", "good")
    engine.evaluate_action("b", "bad", violated_ids=[rules[0].rule_id])
    report_a = engine.get_audit_report("a")
    report_b = engine.get_audit_report("b")
    assert report_a.compliance_score > report_b.compliance_score
