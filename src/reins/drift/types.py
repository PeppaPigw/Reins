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


class DriftKind(str, Enum):
    QUALITY = "quality"
    LATENCY = "latency"
    COST = "cost"
    STYLE = "style"
    SAFETY = "safety"
    ACCURACY = "accuracy"


class DriftSeverity(str, Enum):
    NONE = "none"
    MINOR = "minor"
    MODERATE = "moderate"
    MAJOR = "major"
    CRITICAL = "critical"


class DriftDirection(str, Enum):
    IMPROVING = "improving"
    STABLE = "stable"
    DEGRADING = "degrading"


class BehaviorSample(BaseModel):
    model_config = ConfigDict(frozen=True)

    sample_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    dimension: DriftKind
    value: float
    version: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    recorded_at: datetime = Field(default_factory=_utc_now)


class Baseline(BaseModel):
    model_config = ConfigDict(frozen=True)

    baseline_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    dimension: DriftKind
    mean: float = 0.0
    std_dev: float = 0.0
    sample_count: int = 0
    version: str = ""
    established_at: datetime = Field(default_factory=_utc_now)


class DriftAlert(BaseModel):
    model_config = ConfigDict(frozen=True)

    alert_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    dimension: DriftKind
    severity: DriftSeverity
    direction: DriftDirection
    deviation_sigma: float = 0.0
    baseline_mean: float = 0.0
    current_value: float = 0.0
    message: str = ""
    detected_at: datetime = Field(default_factory=_utc_now)


class BehaviorVersion(BaseModel):
    model_config = ConfigDict(frozen=True)

    version_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    version: str
    baselines: tuple[Baseline, ...] = ()
    sample_count: int = 0
    created_at: datetime = Field(default_factory=_utc_now)


class DriftReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    report_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    alerts: tuple[DriftAlert, ...] = ()
    overall_direction: DriftDirection = DriftDirection.STABLE
    dimensions_drifting: int = 0
    generated_at: datetime = Field(default_factory=_utc_now)


class DriftStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_samples: int = 0
    total_alerts: int = 0
    total_versions: int = 0
    agents_monitored: int = 0
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_dimension: dict[str, int] = Field(default_factory=dict)
