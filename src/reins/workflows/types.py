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


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RetryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_retries: int = 3
    backoff_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    max_backoff_seconds: float = 60.0


class Condition(BaseModel):
    model_config = ConfigDict(frozen=True)

    field: str
    operator: str = "eq"
    value: Any = None


class StepDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    step_id: str = Field(default_factory=_new_ulid)
    name: str
    agent_type: str = "default"
    prompt_template: str = ""
    depends_on: tuple[str, ...] = ()
    condition: Condition | None = None
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    timeout_seconds: float = 300.0
    parallel_group: str | None = None
    output_key: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class StepResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    step_id: str
    status: StepStatus
    output: Any = None
    error: str | None = None
    attempts: int = 1
    duration_ms: float = 0.0
    started_at: datetime = Field(default_factory=_utc_now)
    completed_at: datetime | None = None


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    workflow_id: str = Field(default_factory=_new_ulid)
    name: str
    steps: tuple[StepDefinition, ...] = ()
    inputs: dict[str, Any] = Field(default_factory=dict)
    max_parallel: int = 4
    fail_fast: bool = True
    created_at: datetime = Field(default_factory=_utc_now)


class WorkflowRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str = Field(default_factory=_new_ulid)
    workflow_id: str
    status: WorkflowStatus = WorkflowStatus.PENDING
    step_results: tuple[StepResult, ...] = ()
    context: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
