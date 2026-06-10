from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

import ulid
from pydantic import BaseModel, ConfigDict, Field


def _new_ulid() -> str:
    return str(ulid.new())


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Priority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EscalationLevel(str, Enum):
    NONE = "none"
    WARNING = "warning"
    ALERT = "alert"
    CRITICAL = "critical"
    BLOCKED = "blocked"


class ScheduleStatus(str, Enum):
    PENDING = "pending"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    ESCALATED = "escalated"


class SLA(BaseModel):
    model_config = ConfigDict(frozen=True)

    sla_id: str = Field(default_factory=_new_ulid)
    name: str
    max_duration_seconds: int
    warning_threshold_pct: float = 0.8
    escalation_policy: tuple[EscalationLevel, ...] = (
        EscalationLevel.WARNING,
        EscalationLevel.ALERT,
        EscalationLevel.CRITICAL,
    )


class Deadline(BaseModel):
    model_config = ConfigDict(frozen=True)

    deadline_id: str = Field(default_factory=_new_ulid)
    due_at: datetime
    priority: Priority = Priority.MEDIUM
    sla: SLA | None = None
    hard: bool = False


class ScheduledTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str = Field(default_factory=_new_ulid)
    name: str
    agent_id: str = ""
    deadline: Deadline | None = None
    dependencies: tuple[str, ...] = ()
    priority: Priority = Priority.MEDIUM
    status: ScheduleStatus = ScheduleStatus.PENDING
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    escalation_level: EscalationLevel = EscalationLevel.NONE
    metadata: dict[str, Any] = Field(default_factory=dict)


class EscalationEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=_new_ulid)
    task_id: str
    level: EscalationLevel
    reason: str
    elapsed_seconds: float = 0.0
    threshold_seconds: float = 0.0
    triggered_at: datetime = Field(default_factory=_utc_now)


class ScheduleReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    report_id: str = Field(default_factory=_new_ulid)
    total_tasks: int = 0
    on_track: int = 0
    at_risk: int = 0
    overdue: int = 0
    completed: int = 0
    escalations: tuple[EscalationEvent, ...] = ()
    generated_at: datetime = Field(default_factory=_utc_now)
