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


class CellState(str, Enum):
    UNDIFFERENTIATED = "undifferentiated"
    SPECIALIZING = "specializing"
    MATURE = "mature"
    DIVIDING = "dividing"
    MERGING = "merging"
    APOPTOSIS = "apoptosis"


class Signal(str, Enum):
    GROWTH = "growth"
    DIFFERENTIATE = "differentiate"
    DIVIDE = "divide"
    MERGE = "merge"
    APOPTOSIS = "apoptosis"
    QUIESCE = "quiesce"


class Specialization(str, Enum):
    GENERALIST = "generalist"
    PLANNER = "planner"
    EXECUTOR = "executor"
    REVIEWER = "reviewer"
    RESEARCHER = "researcher"
    COORDINATOR = "coordinator"


class AgentCell(BaseModel):
    model_config = ConfigDict(frozen=True)

    cell_id: str = Field(default_factory=_new_ulid)
    state: CellState = CellState.UNDIFFERENTIATED
    specialization: Specialization = Specialization.GENERALIST
    fitness: float = 0.5
    load: float = 0.0
    generation: int = 0
    parent_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)


class MorphEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=_new_ulid)
    cell_id: str
    signal: Signal
    result: str = ""
    occurred_at: datetime = Field(default_factory=_utc_now)


class MorphogenesisStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_cells: int = 0
    active_cells: int = 0
    by_state: dict[str, int] = Field(default_factory=dict)
    by_specialization: dict[str, int] = Field(default_factory=dict)
    avg_fitness: float = 0.0
    avg_load: float = 0.0
    total_divisions: int = 0
    total_merges: int = 0
    max_generation: int = 0
