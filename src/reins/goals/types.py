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


class GoalStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    ABANDONED = "abandoned"


class GoalPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DecompositionStrategy(str, Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    CONDITIONAL = "conditional"
    ITERATIVE = "iterative"


class Goal(BaseModel):
    model_config = ConfigDict(frozen=True)

    goal_id: str = Field(default_factory=_new_ulid)
    name: str
    description: str = ""
    priority: GoalPriority = GoalPriority.MEDIUM
    status: GoalStatus = GoalStatus.PENDING
    parent_id: str | None = None
    dependencies: tuple[str, ...] = ()
    strategy: DecompositionStrategy = DecompositionStrategy.SEQUENTIAL
    acceptance_criteria: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)
    completed_at: datetime | None = None


class GoalProgress(BaseModel):
    model_config = ConfigDict(frozen=True)

    goal_id: str
    completion_ratio: float = 0.0
    subgoals_total: int = 0
    subgoals_completed: int = 0
    subgoals_blocked: int = 0
    depth: int = 0


class GoalTree(BaseModel):
    model_config = ConfigDict(frozen=True)

    root_id: str
    total_goals: int = 0
    max_depth: int = 0
    completion_ratio: float = 0.0
    critical_path: tuple[str, ...] = ()


class GoalStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_goals: int = 0
    active_goals: int = 0
    completed_goals: int = 0
    blocked_goals: int = 0
    failed_goals: int = 0
    avg_completion: float = 0.0
    by_priority: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)
