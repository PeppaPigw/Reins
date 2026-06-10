from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

import ulid
from pydantic import BaseModel, ConfigDict, Field


def _ulid() -> str:
    return str(ulid.new())


def _now() -> datetime:
    return datetime.now(UTC)


class PipelineStage(str, Enum):
    IDENTITY = "identity"
    RESOURCE_CHECK = "resource_check"
    POLICY = "policy"
    INVARIANTS = "invariants"
    BEHAVIOR_CHECK = "behavior_check"
    TEMPORAL_CHECK = "temporal_check"
    COMPOSABILITY = "composability"
    AUDIT = "audit"


class StageVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"


class PipelineMode(str, Enum):
    STRICT = "strict"
    PERMISSIVE = "permissive"
    DRY_RUN = "dry_run"


class StageResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    result_id: str = Field(default_factory=_ulid)
    stage: PipelineStage
    verdict: StageVerdict
    message: str = ""
    duration_ms: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class PipelineEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=_ulid)
    event_type: str
    agent_id: str
    stage: PipelineStage | None = None
    verdict: StageVerdict | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    ts: datetime = Field(default_factory=_now)


class PipelineExecution(BaseModel):
    model_config = ConfigDict(frozen=True)

    execution_id: str = Field(default_factory=_ulid)
    agent_id: str
    mode: PipelineMode = PipelineMode.STRICT
    final_verdict: StageVerdict = StageVerdict.FAIL
    stages: list[StageResult] = Field(default_factory=list)
    events: list[PipelineEvent] = Field(default_factory=list)
    total_duration_ms: float = 0.0
    failed_at: PipelineStage | None = None
    started_at: datetime = Field(default_factory=_now)
    completed_at: datetime | None = None


class PipelineConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    stages: list[PipelineStage] = Field(default_factory=lambda: list(PipelineStage))
    mode: PipelineMode = PipelineMode.STRICT
    timeout_ms: float = 5000.0
    emit_events: bool = True


class SafetyPipelineStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_executions: int = 0
    passed: int = 0
    failed: int = 0
    warned: int = 0
    avg_duration_ms: float = 0.0
    failure_by_stage: dict[str, int] = Field(default_factory=dict)
    events_emitted: int = 0
