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


class SlaMetric(str, Enum):
    LATENCY_P50 = "latency_p50"
    LATENCY_P95 = "latency_p95"
    LATENCY_P99 = "latency_p99"
    THROUGHPUT = "throughput"
    ERROR_RATE = "error_rate"
    AVAILABILITY = "availability"
    QUALITY_SCORE = "quality_score"


class SlaStatus(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    BREACHED = "breached"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class DegradationAction(str, Enum):
    NONE = "none"
    REDUCE_QUALITY = "reduce_quality"
    SHED_LOAD = "shed_load"
    CIRCUIT_BREAK = "circuit_break"
    FALLBACK = "fallback"


class SlaObjective(BaseModel):
    model_config = ConfigDict(frozen=True)

    objective_id: str = Field(default_factory=_new_ulid)
    metric: SlaMetric
    target: float
    warning_threshold: float = 0.0
    window_seconds: int = 300
    description: str = ""


class Measurement(BaseModel):
    model_config = ConfigDict(frozen=True)

    measurement_id: str = Field(default_factory=_new_ulid)
    objective_id: str
    value: float
    timestamp: datetime = Field(default_factory=_utc_now)


class SlaBreach(BaseModel):
    model_config = ConfigDict(frozen=True)

    breach_id: str = Field(default_factory=_new_ulid)
    objective_id: str
    metric: SlaMetric
    target: float
    actual: float
    severity: float = 0.0
    action_taken: DegradationAction = DegradationAction.NONE
    detected_at: datetime = Field(default_factory=_utc_now)


class ErrorBudget(BaseModel):
    model_config = ConfigDict(frozen=True)

    budget_id: str = Field(default_factory=_new_ulid)
    objective_id: str
    total_budget: float
    consumed: float = 0.0
    remaining: float = 0.0
    burn_rate: float = 0.0


class SlaStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_objectives: int = 0
    healthy: int = 0
    warning: int = 0
    breached: int = 0
    total_measurements: int = 0
    total_breaches: int = 0
    avg_budget_remaining: float = 1.0
    by_metric: dict[str, str] = Field(default_factory=dict)
