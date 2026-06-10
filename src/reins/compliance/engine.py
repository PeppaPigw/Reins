from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from reins.compliance.types import (
    AuditEntry,
    AuditReport,
    AuditSeverity,
    ComplianceEvaluation,
    ComplianceRule,
    ComplianceStats,
    ComplianceStatus,
    RuleCategory,
)


class ComplianceEngine:
    """Tamper-evident audit trail with compliance rule evaluation.

    Tracks every agent action, evaluates against registered compliance rules,
    and generates audit reports with compliance scoring.
    """

    def __init__(self) -> None:
        self._rules: dict[str, ComplianceRule] = {}
        self._entries: list[AuditEntry] = []
        self._evaluations: list[ComplianceEvaluation] = []

    def register_rule(self, rule: ComplianceRule) -> ComplianceRule:
        self._rules[rule.rule_id] = rule
        return rule

    def get_rule(self, rule_id: str) -> ComplianceRule | None:
        return self._rules.get(rule_id)

    def get_rules(self, category: RuleCategory | None = None) -> list[ComplianceRule]:
        rules = list(self._rules.values())
        if category:
            rules = [r for r in rules if r.category == category]
        return rules

    def log_action(self, agent_id: str, action: str, resource: str = "",
                   outcome: str = "", severity: AuditSeverity = AuditSeverity.INFO,
                   metadata: dict | None = None) -> AuditEntry:
        entry = AuditEntry(
            agent_id=agent_id,
            action=action,
            resource=resource,
            outcome=outcome,
            severity=severity,
            metadata=metadata or {},
        )
        self._entries.append(entry)
        return entry

    def evaluate_action(self, agent_id: str, action: str,
                        rule_ids: list[str] | None = None,
                        violated_ids: list[str] | None = None) -> ComplianceEvaluation:
        violated_ids = violated_ids or []
        if rule_ids is None:
            rules_to_check = list(self._rules.values())
        else:
            rules_to_check = [self._rules[rid] for rid in rule_ids if rid in self._rules]

        rules_checked = len(rules_to_check)
        violations = []
        for rule in rules_to_check:
            if rule.rule_id in violated_ids:
                violations.append(rule.rule_id)

        rules_failed = len(violations)
        rules_passed = rules_checked - rules_failed

        has_mandatory_violation = any(
            self._rules[vid].mandatory for vid in violations if vid in self._rules
        )

        if rules_failed == 0:
            status = ComplianceStatus.COMPLIANT
        elif has_mandatory_violation:
            status = ComplianceStatus.NON_COMPLIANT
        else:
            status = ComplianceStatus.PARTIALLY_COMPLIANT

        reasoning_parts = [f"Evaluated action '{action}' against {rules_checked} rules."]
        if violations:
            violated_names = [self._rules[v].name for v in violations if v in self._rules]
            reasoning_parts.append(f"Violations: {', '.join(violated_names)}.")
        else:
            reasoning_parts.append("All rules satisfied.")

        evaluation = ComplianceEvaluation(
            agent_id=agent_id,
            action=action,
            status=status,
            rules_checked=rules_checked,
            rules_passed=rules_passed,
            rules_failed=rules_failed,
            violations=tuple(violations),
            reasoning=" ".join(reasoning_parts),
        )
        self._evaluations.append(evaluation)
        return evaluation

    def get_entries(self, agent_id: str | None = None,
                    severity: AuditSeverity | None = None) -> list[AuditEntry]:
        entries = self._entries
        if agent_id:
            entries = [e for e in entries if e.agent_id == agent_id]
        if severity:
            entries = [e for e in entries if e.severity == severity]
        return entries

    def get_evaluations(self, agent_id: str | None = None,
                        status: ComplianceStatus | None = None) -> list[ComplianceEvaluation]:
        evals = self._evaluations
        if agent_id:
            evals = [e for e in evals if e.agent_id == agent_id]
        if status:
            evals = [e for e in evals if e.status == status]
        return evals

    def get_audit_report(self, agent_id: str) -> AuditReport:
        entries = [e for e in self._entries if e.agent_id == agent_id]
        evals = [e for e in self._evaluations if e.agent_id == agent_id]

        if not evals:
            return AuditReport(agent_id=agent_id, total_entries=len(entries))

        compliant_count = sum(1 for e in evals if e.status == ComplianceStatus.COMPLIANT)
        compliance_score = compliant_count / len(evals) if evals else 1.0

        violations_by_cat: dict[str, int] = defaultdict(int)
        critical_count = 0
        for ev in evals:
            for vid in ev.violations:
                rule = self._rules.get(vid)
                if rule:
                    violations_by_cat[rule.category.value] += 1
                    if rule.mandatory:
                        critical_count += 1

        if critical_count > 0:
            overall = ComplianceStatus.NON_COMPLIANT
        elif compliance_score >= 1.0:
            overall = ComplianceStatus.COMPLIANT
        elif compliance_score >= 0.8:
            overall = ComplianceStatus.PARTIALLY_COMPLIANT
        else:
            overall = ComplianceStatus.NON_COMPLIANT

        return AuditReport(
            agent_id=agent_id,
            total_entries=len(entries),
            total_evaluations=len(evals),
            compliance_score=compliance_score,
            overall_status=overall,
            violations_by_category=dict(violations_by_cat),
            critical_violations=critical_count,
        )

    def get_stats(self) -> ComplianceStats:
        agents = set(e.agent_id for e in self._entries)
        agents.update(e.agent_id for e in self._evaluations)

        by_category: dict[str, int] = defaultdict(int)
        for rule in self._rules.values():
            by_category[rule.category.value] += 1

        by_severity: dict[str, int] = defaultdict(int)
        for entry in self._entries:
            by_severity[entry.severity.value] += 1

        compliant = sum(1 for e in self._evaluations if e.status == ComplianceStatus.COMPLIANT)
        rate = compliant / len(self._evaluations) if self._evaluations else 1.0

        return ComplianceStats(
            total_rules=len(self._rules),
            total_entries=len(self._entries),
            total_evaluations=len(self._evaluations),
            agents_audited=len(agents),
            overall_compliance_rate=rate,
            by_category=dict(by_category),
            by_severity=dict(by_severity),
        )
