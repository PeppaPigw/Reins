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
    MEDIUM = "medium"
    LOW = "low"
    BACKGROUND = "background"


class TaskState(str, Enum):
    PENDING = "pending"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SchedulingStrategy(str, Enum):
    FIFO = "fifo"
    PRIORITY = "priority"
    SHORTEST_FIRST = "shortest_first"
    DEADLINE_FIRST = "deadline_first"
    ROUND_ROBIN = "round_robin"


class ScheduledTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str = Field(default_factory=_new_ulid)
    name: str
    priority: TaskPriority = TaskPriority.MEDIUM
    state: TaskState = TaskState.PENDING
    estimated_duration_ms: int = 1000
    deadline: datetime | None = None
    assigned_to: str = ""
    dependencies: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=_utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResourcePool(BaseModel):
    model_config = ConfigDict(frozen=True)

    pool_id: str = Field(default_factory=_new_ulid)
    name: str
    capacity: int = 10
    allocated: int = 0
    reserved: int = 0


class ScheduleSlot(BaseModel):
    model_config = ConfigDict(frozen=True)

    slot_id: str = Field(default_factory=_new_ulid)
    task_id: str
    agent_id: str
    start_time: datetime = Field(default_factory=_utc_now)
    estimated_end: datetime | None = None


class SchedulingStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_tasks: int = 0
    pending_tasks: int = 0
    running_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    avg_wait_time_ms: float = 0.0
    by_priority: dict[str, int] = Field(default_factory=dict)
    by_state: dict[str, int] = Field(default_factory=dict)
