from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

import ulid
from pydantic import BaseModel, ConfigDict, Field


def _new_ulid() -> str:
    return str(ulid.new())


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ComplianceStatus(str, Enum):
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    PARTIALLY_COMPLIANT = "partially_compliant"
    EXEMPT = "exempt"
    PENDING_REVIEW = "pending_review"


class RuleCategory(str, Enum):
    DATA_PRIVACY = "data_privacy"
    ACCESS_CONTROL = "access_control"
    AUDIT_TRAIL = "audit_trail"
    RETENTION = "retention"
    TRANSPARENCY = "transparency"
    SAFETY = "safety"
    FAIRNESS = "fairness"
    ACCOUNTABILITY = "accountability"


class AuditSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ComplianceRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_id: str = Field(default_factory=_new_ulid)
    name: str
    description: str = ""
    category: RuleCategory = RuleCategory.AUDIT_TRAIL
    mandatory: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuditEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    entry_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    action: str
    resource: str = ""
    outcome: str = ""
    severity: AuditSeverity = AuditSeverity.INFO
    rule_ids_evaluated: tuple[str, ...] = ()
    violations: tuple[str, ...] = ()
    timestamp: datetime = Field(default_factory=_utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ComplianceEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    evaluation_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    action: str
    status: ComplianceStatus = ComplianceStatus.COMPLIANT
    rules_checked: int = 0
    rules_passed: int = 0
    rules_failed: int = 0
    violations: tuple[str, ...] = ()
    reasoning: str = ""
    evaluated_at: datetime = Field(default_factory=_utc_now)


class AuditReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    report_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    total_entries: int = 0
    total_evaluations: int = 0
    compliance_score: float = 1.0
    overall_status: ComplianceStatus = ComplianceStatus.COMPLIANT
    violations_by_category: dict[str, int] = Field(default_factory=dict)
    critical_violations: int = 0
    generated_at: datetime = Field(default_factory=_utc_now)


class ComplianceStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_rules: int = 0
    total_entries: int = 0
    total_evaluations: int = 0
    agents_audited: int = 0
    overall_compliance_rate: float = 1.0
    by_category: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)
