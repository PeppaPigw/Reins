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


class EthicalFramework(str, Enum):
    DEONTOLOGICAL = "deontological"
    CONSEQUENTIALIST = "consequentialist"
    VIRTUE_ETHICS = "virtue_ethics"
    CARE_ETHICS = "care_ethics"
    RIGHTS_BASED = "rights_based"


class AlignmentLevel(str, Enum):
    FULLY_ALIGNED = "fully_aligned"
    MOSTLY_ALIGNED = "mostly_aligned"
    PARTIALLY_ALIGNED = "partially_aligned"
    MISALIGNED = "misaligned"
    CRITICALLY_MISALIGNED = "critically_misaligned"


class ViolationSeverity(str, Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MODERATE = "moderate"
    MINOR = "minor"
    ADVISORY = "advisory"


class ValueDimension(str, Enum):
    AUTONOMY = "autonomy"
    BENEFICENCE = "beneficence"
    NON_MALEFICENCE = "non_maleficence"
    JUSTICE = "justice"
    TRANSPARENCY = "transparency"
    PRIVACY = "privacy"
    ACCOUNTABILITY = "accountability"
    TRUTHFULNESS = "truthfulness"


class EthicalPrinciple(BaseModel):
    model_config = ConfigDict(frozen=True)

    principle_id: str = Field(default_factory=_new_ulid)
    name: str
    dimension: ValueDimension
    description: str = ""
    weight: float = 1.0
    framework: EthicalFramework = EthicalFramework.DEONTOLOGICAL
    hard_constraint: bool = False


class EthicalEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    eval_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    action: str
    alignment: AlignmentLevel = AlignmentLevel.FULLY_ALIGNED
    score: float = 1.0
    violated_principles: tuple[str, ...] = ()
    satisfied_principles: tuple[str, ...] = ()
    reasoning: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    evaluated_at: datetime = Field(default_factory=_utc_now)


class EthicalViolation(BaseModel):
    model_config = ConfigDict(frozen=True)

    violation_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    principle_id: str
    severity: ViolationSeverity
    action: str
    description: str = ""
    mitigated: bool = False
    detected_at: datetime = Field(default_factory=_utc_now)


class AlignmentReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str
    overall_alignment: AlignmentLevel = AlignmentLevel.FULLY_ALIGNED
    overall_score: float = 1.0
    by_dimension: dict[str, float] = Field(default_factory=dict)
    total_evaluations: int = 0
    total_violations: int = 0
    critical_violations: int = 0


class EthicsStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_principles: int = 0
    total_evaluations: int = 0
    total_violations: int = 0
    agents_evaluated: int = 0
    avg_alignment_score: float = 0.0
    by_dimension: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)
