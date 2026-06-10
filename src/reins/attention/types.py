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


class AttentionPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"
    BACKGROUND = "background"


class FocusState(str, Enum):
    SHARP = "sharp"
    NORMAL = "normal"
    DIFFUSE = "diffuse"
    OVERLOADED = "overloaded"
    IDLE = "idle"


class StreamKind(str, Enum):
    TASK = "task"
    ALERT = "alert"
    CONTEXT = "context"
    FEEDBACK = "feedback"
    OBSERVATION = "observation"
    MEMORY = "memory"


class AttentionItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    item_id: str = Field(default_factory=_new_ulid)
    stream: StreamKind
    priority: AttentionPriority
    content: str
    weight: float = 1.0
    decay_rate: float = 0.1
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)


class AttentionBudget(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_capacity: float = 100.0
    used: float = 0.0
    reserved: float = 0.0
    available: float = 100.0
    by_stream: dict[str, float] = Field(default_factory=dict)


class FocusWindow(BaseModel):
    model_config = ConfigDict(frozen=True)

    window_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    items: tuple[AttentionItem, ...] = ()
    state: FocusState = FocusState.NORMAL
    capacity: float = 100.0
    utilization: float = 0.0


class AttentionShift(BaseModel):
    model_config = ConfigDict(frozen=True)

    shift_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    from_state: FocusState
    to_state: FocusState
    reason: str = ""
    shifted_at: datetime = Field(default_factory=_utc_now)


class AttentionStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    agents_tracked: int = 0
    total_items: int = 0
    total_shifts: int = 0
    avg_utilization: float = 0.0
    overloaded_agents: int = 0
    by_priority: dict[str, int] = Field(default_factory=dict)
    by_stream: dict[str, int] = Field(default_factory=dict)
