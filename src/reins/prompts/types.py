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


class OptimizationStrategy(str, Enum):
    FEW_SHOT_SELECTION = "few_shot_selection"
    TEMPLATE_REFINEMENT = "template_refinement"
    PARAMETER_TUNING = "parameter_tuning"
    CHAIN_OF_THOUGHT = "chain_of_thought"
    CONTEXT_PRUNING = "context_pruning"


class OutcomeSignal(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    REJECTED = "rejected"


class FewShotExample(BaseModel):
    model_config = ConfigDict(frozen=True)

    example_id: str = Field(default_factory=_new_ulid)
    input_text: str
    output_text: str
    tags: tuple[str, ...] = ()
    quality_score: float = 1.0


class PromptTemplate(BaseModel):
    model_config = ConfigDict(frozen=True)

    template_id: str = Field(default_factory=_new_ulid)
    name: str
    content: str
    variables: tuple[str, ...] = ()
    few_shot_examples: tuple[FewShotExample, ...] = ()
    parameters: dict[str, Any] = Field(default_factory=dict)
    version: int = 1
    created_at: datetime = Field(default_factory=_utc_now)


class PromptOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome_id: str = Field(default_factory=_new_ulid)
    template_id: str
    signal: OutcomeSignal
    latency_ms: float = 0.0
    token_count: int = 0
    cost: float = 0.0
    context: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utc_now)


class PromptVariant(BaseModel):
    model_config = ConfigDict(frozen=True)

    variant_id: str = Field(default_factory=_new_ulid)
    template_id: str
    strategy: OptimizationStrategy
    content: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    score: float = 0.0
    trial_count: int = 0
    success_count: int = 0
    created_at: datetime = Field(default_factory=_utc_now)


class OptimizationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    result_id: str = Field(default_factory=_new_ulid)
    template_id: str
    best_variant: PromptVariant | None = None
    variants_tested: int = 0
    improvement_pct: float = 0.0
    strategy_used: OptimizationStrategy = OptimizationStrategy.TEMPLATE_REFINEMENT
    computed_at: datetime = Field(default_factory=_utc_now)
