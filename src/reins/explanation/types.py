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


class ExplanationDepth(str, Enum):
    BRIEF = "brief"
    STANDARD = "standard"
    DETAILED = "detailed"
    TECHNICAL = "technical"


class FactorKind(str, Enum):
    CAUSAL = "causal"
    SUPPORTING = "supporting"
    INHIBITING = "inhibiting"
    CONTEXTUAL = "contextual"
    CONSTRAINT = "constraint"


class AudienceLevel(str, Enum):
    END_USER = "end_user"
    DEVELOPER = "developer"
    AUDITOR = "auditor"
    SYSTEM = "system"


class DecisionFactor(BaseModel):
    model_config = ConfigDict(frozen=True)

    factor_id: str = Field(default_factory=_new_ulid)
    kind: FactorKind
    description: str
    weight: float = 1.0
    evidence: str = ""
    confidence: float = 1.0


class Counterfactual(BaseModel):
    model_config = ConfigDict(frozen=True)

    condition: str
    alternative_outcome: str
    likelihood: float = 0.0
    impact: str = ""


class Explanation(BaseModel):
    model_config = ConfigDict(frozen=True)

    explanation_id: str = Field(default_factory=_new_ulid)
    decision_id: str
    agent_id: str
    summary: str
    factors: tuple[DecisionFactor, ...] = ()
    counterfactuals: tuple[Counterfactual, ...] = ()
    depth: ExplanationDepth = ExplanationDepth.STANDARD
    audience: AudienceLevel = AudienceLevel.DEVELOPER
    confidence: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=_utc_now)


class DecisionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    action: str
    outcome: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    factors: tuple[DecisionFactor, ...] = ()
    alternatives_considered: tuple[str, ...] = ()
    recorded_at: datetime = Field(default_factory=_utc_now)


class ExplanationStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_decisions: int = 0
    total_explanations: int = 0
    avg_factors_per_decision: float = 0.0
    avg_confidence: float = 0.0
    by_depth: dict[str, int] = Field(default_factory=dict)
    by_audience: dict[str, int] = Field(default_factory=dict)
