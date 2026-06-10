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


class ReplayMode(str, Enum):
    FULL = "full"
    FAST_FORWARD = "fast_forward"
    STEP = "step"
    BREAKPOINT = "breakpoint"


class ReplayStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    DIVERGED = "diverged"
    ERROR = "error"


class EventRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=_new_ulid)
    sequence: int = 0
    agent_id: str = ""
    event_type: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    state_hash: str = ""
    timestamp: datetime = Field(default_factory=_utc_now)


class Breakpoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    breakpoint_id: str = Field(default_factory=_new_ulid)
    condition: str = ""
    at_sequence: int | None = None
    at_event_type: str | None = None
    at_agent: str | None = None
    enabled: bool = True


class ReplaySession(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str = Field(default_factory=_new_ulid)
    mode: ReplayMode = ReplayMode.FULL
    status: ReplayStatus = ReplayStatus.IDLE
    total_events: int = 0
    current_position: int = 0
    divergence_point: int | None = None
    started_at: datetime = Field(default_factory=_utc_now)


class Divergence(BaseModel):
    model_config = ConfigDict(frozen=True)

    divergence_id: str = Field(default_factory=_new_ulid)
    position: int
    expected_hash: str
    actual_hash: str
    expected_state: dict[str, Any] = Field(default_factory=dict)
    actual_state: dict[str, Any] = Field(default_factory=dict)


class ReplayStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_sessions: int = 0
    completed_sessions: int = 0
    diverged_sessions: int = 0
    total_events_replayed: int = 0
    avg_events_per_session: float = 0.0
    by_mode: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)
