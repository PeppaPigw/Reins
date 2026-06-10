from __future__ import annotations

import math
import random
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import ulid
from pydantic import BaseModel, ConfigDict, Field


def _new_ulid() -> str:
    return str(ulid.new())


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AcquisitionFunction(str, Enum):
    EXPECTED_IMPROVEMENT = "expected_improvement"
    UPPER_CONFIDENCE_BOUND = "upper_confidence_bound"
    PROBABILITY_OF_IMPROVEMENT = "probability_of_improvement"
    THOMPSON_SAMPLING = "thompson_sampling"


class ParameterKind(str, Enum):
    CONTINUOUS = "continuous"
    INTEGER = "integer"
    CATEGORICAL = "categorical"
    LOG_SCALE = "log_scale"


class OptimizationStatus(str, Enum):
    EXPLORING = "exploring"
    EXPLOITING = "exploiting"
    CONVERGED = "converged"
    BUDGET_EXHAUSTED = "budget_exhausted"


class Parameter(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    kind: ParameterKind = ParameterKind.CONTINUOUS
    lower: float = 0.0
    upper: float = 1.0
    categories: tuple[str, ...] = ()


class Trial(BaseModel):
    model_config = ConfigDict(frozen=True)

    trial_id: str = Field(default_factory=_new_ulid)
    params: dict[str, float] = Field(default_factory=dict)
    objective: float = 0.0
    iteration: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
    evaluated_at: datetime = Field(default_factory=_utc_now)


class SearchSpace(BaseModel):
    model_config = ConfigDict(frozen=True)

    space_id: str = Field(default_factory=_new_ulid)
    name: str
    parameters: tuple[Parameter, ...] = ()


class OptimizationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    result_id: str = Field(default_factory=_new_ulid)
    space_id: str
    best_params: dict[str, float] = Field(default_factory=dict)
    best_objective: float = 0.0
    total_trials: int = 0
    status: OptimizationStatus = OptimizationStatus.EXPLORING
    convergence_rate: float = 0.0


class BayesianStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_spaces: int = 0
    total_trials: int = 0
    avg_improvement: float = 0.0
    best_objective: float = 0.0
    by_status: dict[str, int] = Field(default_factory=dict)
