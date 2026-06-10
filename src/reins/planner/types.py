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


class TaskPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"
    BACKGROUND = "background"


class TaskState(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class SchedulingStrategy(str, Enum):
    EAGER = "eager"
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    COST_OPTIMIZED = "cost_optimized"


class PlanTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str = Field(default_factory=_new_ulid)
    name: str
    description: str = ""
    priority: TaskPriority = TaskPriority.NORMAL
    state: TaskState = TaskState.PENDING
    depends_on: tuple[str, ...] = ()
    estimated_duration_ms: float = 1000.0
    estimated_cost: float = 0.0
    resource_requirements: dict[str, float] = Field(default_factory=dict)
    parallelizable: bool = True
    retryable: bool = True
    max_retries: int = 3
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionSlot(BaseModel):
    model_config = ConfigDict(frozen=True)

    slot_id: str = Field(default_factory=_new_ulid)
    task_ids: tuple[str, ...] = ()
    start_offset_ms: float = 0.0
    estimated_duration_ms: float = 0.0
    parallel: bool = False


class ExecutionPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    plan_id: str = Field(default_factory=_new_ulid)
    goal: str
    tasks: tuple[PlanTask, ...] = ()
    slots: tuple[ExecutionSlot, ...] = ()
    total_estimated_duration_ms: float = 0.0
    total_estimated_cost: float = 0.0
    critical_path_length: int = 0
    parallelism_factor: float = 1.0
    strategy: SchedulingStrategy = SchedulingStrategy.BALANCED
    created_at: datetime = Field(default_factory=_utc_now)


class PlanOptimization(BaseModel):
    model_config = ConfigDict(frozen=True)

    optimization_id: str = Field(default_factory=_new_ulid)
    plan_id: str
    original_duration_ms: float = 0.0
    optimized_duration_ms: float = 0.0
    speedup_factor: float = 1.0
    optimizations_applied: tuple[str, ...] = ()


class PlannerStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_plans: int = 0
    total_tasks: int = 0
    avg_parallelism: float = 1.0
    avg_speedup: float = 1.0
    by_strategy: dict[str, int] = Field(default_factory=dict)
