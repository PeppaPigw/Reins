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


class FailureCategory(str, Enum):
    TIMEOUT = "timeout"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    LOGIC_ERROR = "logic_error"
    DEPENDENCY_FAILURE = "dependency_failure"
    RATE_LIMIT = "rate_limit"
    CONTEXT_OVERFLOW = "context_overflow"
    POLICY_VIOLATION = "policy_violation"
    CASCADING = "cascading"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PredictionConfidence(str, Enum):
    SPECULATIVE = "speculative"
    PROBABLE = "probable"
    LIKELY = "likely"
    NEAR_CERTAIN = "near_certain"


class SignalKind(str, Enum):
    LATENCY_SPIKE = "latency_spike"
    ERROR_RATE_INCREASE = "error_rate_increase"
    RESOURCE_PRESSURE = "resource_pressure"
    PATTERN_MATCH = "pattern_match"
    THRESHOLD_BREACH = "threshold_breach"
    TREND_EXTRAPOLATION = "trend_extrapolation"


class FailureSignal(BaseModel):
    model_config = ConfigDict(frozen=True)

    signal_id: str = Field(default_factory=_new_ulid)
    kind: SignalKind
    source: str
    value: float
    threshold: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime = Field(default_factory=_utc_now)


class FailurePattern(BaseModel):
    model_config = ConfigDict(frozen=True)

    pattern_id: str = Field(default_factory=_new_ulid)
    name: str
    category: FailureCategory
    signals: tuple[SignalKind, ...] = ()
    min_signals_required: int = 1
    lookback_window_ms: float = 60000.0
    historical_occurrences: int = 0
    avg_time_to_failure_ms: float = 0.0


class FailurePrediction(BaseModel):
    model_config = ConfigDict(frozen=True)

    prediction_id: str = Field(default_factory=_new_ulid)
    pattern_id: str
    category: FailureCategory
    risk_level: RiskLevel
    confidence: PredictionConfidence
    probability: float = 0.0
    estimated_time_to_failure_ms: float = 0.0
    contributing_signals: tuple[FailureSignal, ...] = ()
    recommended_actions: tuple[str, ...] = ()
    predicted_at: datetime = Field(default_factory=_utc_now)


class MitigationAction(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_id: str = Field(default_factory=_new_ulid)
    prediction_id: str
    description: str
    automated: bool = False
    executed: bool = False
    success: bool = False
    executed_at: datetime | None = None


class PredictionStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_predictions: int = 0
    true_positives: int = 0
    false_positives: int = 0
    missed_failures: int = 0
    precision: float = 0.0
    recall: float = 0.0
    avg_lead_time_ms: float = 0.0
    by_category: dict[str, int] = Field(default_factory=dict)
