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


class WorldKind(str, Enum):
    ACTUAL = "actual"
    COUNTERFACTUAL = "counterfactual"
    HYPOTHETICAL = "hypothetical"


class InterventionType(str, Enum):
    ACTION_SWAP = "action_swap"
    PARAMETER_CHANGE = "parameter_change"
    CONTEXT_REMOVAL = "context_removal"
    TIMING_SHIFT = "timing_shift"
    AGENT_REMOVAL = "agent_removal"


class CausalStrength(str, Enum):
    NECESSARY = "necessary"
    SUFFICIENT = "sufficient"
    NECESSARY_AND_SUFFICIENT = "necessary_and_sufficient"
    CONTRIBUTORY = "contributory"
    IRRELEVANT = "irrelevant"


class OutcomeComparison(str, Enum):
    BETTER = "better"
    WORSE = "worse"
    EQUIVALENT = "equivalent"
    INCOMPARABLE = "incomparable"


class Decision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    action_taken: str
    alternatives: tuple[str, ...] = ()
    context: dict[str, Any] = Field(default_factory=dict)
    outcome_value: float = 0.0
    timestamp: datetime = Field(default_factory=_utc_now)


class Intervention(BaseModel):
    model_config = ConfigDict(frozen=True)

    intervention_id: str = Field(default_factory=_new_ulid)
    intervention_type: InterventionType
    target_decision_id: str
    original_action: str
    counterfactual_action: str
    description: str = ""


class WorldState(BaseModel):
    model_config = ConfigDict(frozen=True)

    world_id: str = Field(default_factory=_new_ulid)
    kind: WorldKind = WorldKind.ACTUAL
    decisions: tuple[str, ...] = ()
    outcome_value: float = 0.0
    metrics: dict[str, float] = Field(default_factory=dict)
    intervention: Intervention | None = None


class CausalClaim(BaseModel):
    model_config = ConfigDict(frozen=True)

    claim_id: str = Field(default_factory=_new_ulid)
    cause_decision_id: str
    effect_description: str
    strength: CausalStrength
    confidence: float = 0.0
    evidence_worlds: tuple[str, ...] = ()


class CounterfactualResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    result_id: str = Field(default_factory=_new_ulid)
    actual_world: WorldState
    counterfactual_worlds: tuple[WorldState, ...] = ()
    comparison: OutcomeComparison = OutcomeComparison.EQUIVALENT
    regret: float = 0.0
    causal_claims: tuple[CausalClaim, ...] = ()


class CounterfactualStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_decisions: int = 0
    total_interventions: int = 0
    total_worlds: int = 0
    avg_regret: float = 0.0
    causal_claims_found: int = 0
    by_strength: dict[str, int] = Field(default_factory=dict)
