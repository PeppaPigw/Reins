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


class ExperimentStatus(str, Enum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    CONCLUDED = "concluded"
    ABORTED = "aborted"


class VariantOutcome(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    ERROR = "error"


class AllocationStrategy(str, Enum):
    UNIFORM = "uniform"
    EPSILON_GREEDY = "epsilon_greedy"
    THOMPSON_SAMPLING = "thompson_sampling"
    UCB = "ucb"


class SignificanceLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class Variant(BaseModel):
    model_config = ConfigDict(frozen=True)

    variant_id: str = Field(default_factory=_new_ulid)
    name: str
    description: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    weight: float = 1.0


class TrialResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    trial_id: str = Field(default_factory=_new_ulid)
    experiment_id: str
    variant_id: str
    outcome: VariantOutcome
    metric_value: float = 0.0
    latency_ms: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    recorded_at: datetime = Field(default_factory=_utc_now)


class Experiment(BaseModel):
    model_config = ConfigDict(frozen=True)

    experiment_id: str = Field(default_factory=_new_ulid)
    name: str
    description: str = ""
    variants: tuple[Variant, ...] = ()
    status: ExperimentStatus = ExperimentStatus.DRAFT
    allocation: AllocationStrategy = AllocationStrategy.UNIFORM
    min_trials_per_variant: int = 30
    max_total_trials: int = 1000
    created_at: datetime = Field(default_factory=_utc_now)
    concluded_at: datetime | None = None


class VariantStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    variant_id: str
    variant_name: str
    trial_count: int = 0
    success_count: int = 0
    success_rate: float = 0.0
    avg_metric: float = 0.0
    avg_latency_ms: float = 0.0
    std_dev: float = 0.0


class ExperimentConclusion(BaseModel):
    model_config = ConfigDict(frozen=True)

    experiment_id: str
    winner_variant_id: str | None = None
    winner_name: str = ""
    confidence: float = 0.0
    significance: SignificanceLevel = SignificanceLevel.LOW
    variant_stats: tuple[VariantStats, ...] = ()
    recommendation: str = ""


class ExperimentManagerStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_experiments: int = 0
    running: int = 0
    concluded: int = 0
    total_trials: int = 0
    avg_trials_per_experiment: float = 0.0
