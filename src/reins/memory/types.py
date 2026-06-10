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
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    WORKING = "working"


class ConsolidationStrategy(str, Enum):
    RECENCY = "recency"
    FREQUENCY = "frequency"
    IMPORTANCE = "importance"
    HYBRID = "hybrid"


class ForgetCurve(str, Enum):
    EBBINGHAUS = "ebbinghaus"
    POWER_LAW = "power_law"
    EXPONENTIAL = "exponential"
    NONE = "none"


class MemoryEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    entry_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    kind: MemoryKind
    content: str
    importance: float = 0.5
    access_count: int = 0
    reinforcement_count: int = 0
    tags: tuple[str, ...] = ()
    associations: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)
    last_accessed: datetime = Field(default_factory=_utc_now)
    last_reinforced: datetime | None = None


class ConsolidationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    entries_reviewed: int = 0
    entries_consolidated: int = 0
    entries_forgotten: int = 0
    entries_strengthened: int = 0
    duration_ms: float = 0.0


class MemoryQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str = ""
    kind: MemoryKind | None = None
    tags: tuple[str, ...] = ()
    min_importance: float = 0.0
    max_results: int = 10
    include_forgotten: bool = False


class MemoryStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_entries: int = 0
    by_kind: dict[str, int] = Field(default_factory=dict)
    avg_importance: float = 0.0
    avg_access_count: float = 0.0
    forgotten_count: int = 0
    consolidation_cycles: int = 0
