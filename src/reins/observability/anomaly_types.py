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


class AnomalyKind(str, Enum):
    LATENCY_SPIKE = "latency_spike"
    ERROR_RATE_SPIKE = "error_rate_spike"
    THROUGHPUT_DROP = "throughput_drop"
    BEHAVIORAL_DRIFT = "behavioral_drift"
    COST_ANOMALY = "cost_anomaly"
    TOKEN_EXPLOSION = "token_explosion"
    RETRY_STORM = "retry_storm"
    DEADLOCK_SUSPECTED = "deadlock_suspected"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class MetricPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: datetime = Field(default_factory=_utc_now)
    value: float
    labels: dict[str, str] = Field(default_factory=dict)


class Anomaly(BaseModel):
    model_config = ConfigDict(frozen=True)

    anomaly_id: str = Field(default_factory=_new_ulid)
    kind: AnomalyKind
    severity: Severity
    metric_name: str
    observed_value: float
    expected_range: tuple[float, float]
    deviation_sigma: float = 0.0
    agent_id: str | None = None
    description: str = ""
    detected_at: datetime = Field(default_factory=_utc_now)
    context: dict[str, Any] = Field(default_factory=dict)


class BaselineStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    metric_name: str
    mean: float = 0.0
    std_dev: float = 0.0
    min_val: float = 0.0
    max_val: float = 0.0
    p50: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    sample_count: int = 0
    computed_at: datetime = Field(default_factory=_utc_now)


class DetectorConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    sigma_threshold: float = 3.0
    min_samples: int = 10
    window_size: int = 100
    error_rate_threshold: float = 0.1
    latency_spike_multiplier: float = 3.0
    cost_spike_multiplier: float = 5.0
    throughput_drop_pct: float = 0.5
    drift_threshold: float = 0.3


class AnomalyReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    report_id: str = Field(default_factory=_new_ulid)
    anomalies: tuple[Anomaly, ...] = ()
    baselines: tuple[BaselineStats, ...] = ()
    window_start: datetime = Field(default_factory=_utc_now)
    window_end: datetime = Field(default_factory=_utc_now)
    total_points_analyzed: int = 0
    has_critical: bool = False
