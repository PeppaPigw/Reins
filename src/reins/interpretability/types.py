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


class ExplanationKind(str, Enum):
    FEATURE_ATTRIBUTION = "feature_attribution"
    CONTRASTIVE = "contrastive"
    COUNTERFACTUAL = "counterfactual"
    EXAMPLE_BASED = "example_based"
    RULE_BASED = "rule_based"
    CHAIN_OF_THOUGHT = "chain_of_thought"


class Audience(str, Enum):
    DEVELOPER = "developer"
    OPERATOR = "operator"
    END_USER = "end_user"
    AUDITOR = "auditor"


class Fidelity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class Factor(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    contribution: float = 0.0
    direction: str = "positive"
    description: str = ""


class Explanation(BaseModel):
    model_config = ConfigDict(frozen=True)

    explanation_id: str = Field(default_factory=_new_ulid)
    decision_id: str
    kind: ExplanationKind
    audience: Audience = Audience.DEVELOPER
    summary: str = ""
    factors: tuple[Factor, ...] = ()
    fidelity: Fidelity = Fidelity.UNKNOWN
    confidence: float = 0.0
    generated_at: datetime = Field(default_factory=_utc_now)


class DecisionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    action: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    outcome: str = ""
    outcome_value: float = 0.0
    timestamp: datetime = Field(default_factory=_utc_now)


class ContrastiveExplanation(BaseModel):
    model_config = ConfigDict(frozen=True)

    chosen_action: str
    rejected_action: str
    reason: str
    differentiating_factors: tuple[Factor, ...] = ()


class InterpretabilityStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_decisions: int = 0
    total_explanations: int = 0
    by_kind: dict[str, int] = Field(default_factory=dict)
    by_audience: dict[str, int] = Field(default_factory=dict)
    avg_fidelity_score: float = 0.0
    coverage: float = 0.0
