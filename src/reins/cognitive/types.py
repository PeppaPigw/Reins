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


class MemoryKind(str, Enum):
    SENSORY = "sensory"
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class CognitiveState(str, Enum):
    IDLE = "idle"
    FOCUSED = "focused"
    OVERLOADED = "overloaded"
    FATIGUED = "fatigued"
    FLOW = "flow"
    RECOVERING = "recovering"


class ExecutiveFunction(str, Enum):
    PLANNING = "planning"
    INHIBITION = "inhibition"
    SWITCHING = "switching"
    MONITORING = "monitoring"
    UPDATING = "updating"


class CognitiveLoad(str, Enum):
    INTRINSIC = "intrinsic"
    EXTRANEOUS = "extraneous"
    GERMANE = "germane"


class MemoryItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    item_id: str = Field(default_factory=_new_ulid)
    kind: MemoryKind
    content: str
    salience: float = 0.5
    decay_rate: float = 0.1
    associations: tuple[str, ...] = ()
    stored_at: datetime = Field(default_factory=_utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkingMemorySlot(BaseModel):
    model_config = ConfigDict(frozen=True)

    slot_id: str = Field(default_factory=_new_ulid)
    item_id: str
    activation: float = 1.0
    rehearsals: int = 0
    loaded_at: datetime = Field(default_factory=_utc_now)


class CognitiveProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str
    state: CognitiveState = CognitiveState.IDLE
    working_memory_load: float = 0.0
    working_memory_capacity: int = 7
    total_load: float = 0.0
    intrinsic_load: float = 0.0
    extraneous_load: float = 0.0
    germane_load: float = 0.0
    fatigue_level: float = 0.0
    focus_duration_ms: float = 0.0


class CognitiveStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_agents: int = 0
    total_memory_items: int = 0
    avg_working_memory_load: float = 0.0
    avg_fatigue: float = 0.0
    by_state: dict[str, int] = Field(default_factory=dict)
    by_memory_kind: dict[str, int] = Field(default_factory=dict)
