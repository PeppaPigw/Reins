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


class EnvelopeVerdict(str, Enum):
    SAFE = "safe"
    CONDITIONALLY_SAFE = "conditionally_safe"
    UNSAFE = "unsafe"
    INCONCLUSIVE = "inconclusive"


class ThreatKind(str, Enum):
    PRIVILEGE_ESCALATION = "privilege_escalation"
    DATA_EXFILTRATION = "data_exfiltration"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    CASCADING_FAILURE = "cascading_failure"
    INVARIANT_VIOLATION = "invariant_violation"
    UNAUTHORIZED_COMPOSITION = "unauthorized_composition"


class MitigationStatus(str, Enum):
    ACTIVE = "active"
    TRIGGERED = "triggered"
    BYPASSED = "bypassed"
    DISABLED = "disabled"


class SafetyConstraint(BaseModel):
    model_config = ConfigDict(frozen=True)

    constraint_id: str = Field(default_factory=_new_ulid)
    name: str
    description: str = ""
    expression: str = ""
    agents: list[str] = Field(default_factory=list)
    enforced: bool = True


class ThreatModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    threat_id: str = Field(default_factory=_new_ulid)
    kind: ThreatKind
    description: str = ""
    affected_agents: list[str] = Field(default_factory=list)
    likelihood: float = 0.5
    impact: float = 0.5
    mitigations: list[str] = Field(default_factory=list)


class Mitigation(BaseModel):
    model_config = ConfigDict(frozen=True)

    mitigation_id: str = Field(default_factory=_new_ulid)
    name: str
    threat_id: str
    status: MitigationStatus = MitigationStatus.ACTIVE
    action: str = ""


class EnvelopeAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)

    assessment_id: str = Field(default_factory=_new_ulid)
    verdict: EnvelopeVerdict = EnvelopeVerdict.INCONCLUSIVE
    constraints_checked: int = 0
    constraints_satisfied: int = 0
    threats_identified: int = 0
    threats_mitigated: int = 0
    risk_score: float = 0.0
    conditions: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    assessed_at: datetime = Field(default_factory=_utc_now)


class SafetyEnvelopeStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_constraints: int = 0
    total_threats: int = 0
    total_mitigations: int = 0
    total_assessments: int = 0
    current_verdict: EnvelopeVerdict = EnvelopeVerdict.INCONCLUSIVE
    risk_score: float = 0.0
    by_threat_kind: dict[str, int] = Field(default_factory=dict)
    by_verdict: dict[str, int] = Field(default_factory=dict)
