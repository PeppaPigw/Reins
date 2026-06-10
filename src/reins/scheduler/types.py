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
    BLOCKED = "blocked"


class SchedulingPolicy(str, Enum):
    FIFO = "fifo"
    PRIORITY = "priority"
    SHORTEST_FIRST = "shortest_first"
    CRITICAL_PATH = "critical_path"
    FAIR_SHARE = "fair_share"


class ScheduledTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str = Field(default_factory=_new_ulid)
    name: str
    priority: TaskPriority = TaskPriority.NORMAL
    state: TaskState = TaskState.PENDING
    estimated_duration_ms: float = 1000.0
    actual_duration_ms: float = 0.0
    dependencies: tuple[str, ...] = ()
    assigned_to: str = ""
    resource_requirements: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)


class Schedule(BaseModel):
    model_config = ConfigDict(frozen=True)

    schedule_id: str = Field(default_factory=_new_ulid)
    task_order: tuple[str, ...] = ()
    critical_path: tuple[str, ...] = ()
    makespan_ms: float = 0.0
    parallelism: int = 1
    generated_at: datetime = Field(default_factory=_utc_now)


class SchedulerStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_tasks: int = 0
    completed: int = 0
    running: int = 0
    blocked: int = 0
    avg_wait_ms: float = 0.0
    avg_duration_ms: float = 0.0
    critical_path_length: int = 0
    parallelism_factor: float = 1.0
    by_priority: dict[str, int] = Field(default_factory=dict)
