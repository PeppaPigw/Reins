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


class TraceKind(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    EXPLORATION = "exploration"
    WARNING = "warning"
    RECOMMENDATION = "recommendation"
    OBSTACLE = "obstacle"


class DecayModel(str, Enum):
    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    STEP = "step"
    NONE = "none"


class Trace(BaseModel):
    model_config = ConfigDict(frozen=True)

    trace_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    kind: TraceKind
    location: str
    intensity: float = 1.0
    payload: dict[str, Any] = Field(default_factory=dict)
    deposited_at: datetime = Field(default_factory=_utc_now)


class TraceQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    location: str = ""
    kind: TraceKind | None = None
    min_intensity: float = 0.0
    max_results: int = 10


class StigmergyStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_traces: int = 0
    active_traces: int = 0
    evaporated: int = 0
    by_kind: dict[str, int] = Field(default_factory=dict)
    avg_intensity: float = 0.0
    hotspots: tuple[str, ...] = ()
