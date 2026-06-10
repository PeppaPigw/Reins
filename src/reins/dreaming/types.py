from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Iterable

import ulid
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def new_ulid() -> str:
    return str(ulid.new())


def utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_datetime(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def normalize_unique(value: Iterable[object] | None, *, sort: bool = False) -> tuple[str, ...]:
    if value is None:
        return ()
    items = [str(item).strip() for item in value if str(item).strip()]
    unique = tuple(dict.fromkeys(items))
    return tuple(sorted(unique)) if sort else unique


class OptimizationType(str, Enum):
    CONTEXT = "context"
    POLICY = "policy"
    ROUTING = "routing"
    TOOL = "tool"
    TIMEOUT = "timeout"


class PatternKind(str, Enum):
    SUCCESS_SEQUENCE = "success_sequence"
    FAILURE_SEQUENCE = "failure_sequence"
    TOOL_USAGE = "tool_usage"
    CONTEXT = "context"
    TEMPORAL = "temporal"


class OptimizationStatus(str, Enum):
    PROPOSED = "proposed"
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"
    REJECTED = "rejected"


class DreamingModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class ActionRecord(DreamingModel):
    action: str = Field(..., min_length=1)
    tool: str | None = None
    success: bool | None = None
    duration_seconds: float | None = Field(default=None, ge=0.0)
    timestamp: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _validate_timestamp(cls, value: datetime | str | None) -> datetime | None:
        return normalize_datetime(value) if value is not None else None


class FailureRecord(DreamingModel):
    failure_id: str = Field(default_factory=new_ulid, min_length=1)
    session_id: str = Field(..., min_length=1)
    failure_type: str = Field(..., min_length=1)
    message: str = Field(default="")
    action_sequence: tuple[str, ...] = Field(default_factory=tuple)
    tool: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    severity: float = Field(default=1.0, ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=utc_now)

    @field_validator("action_sequence", mode="before")
    @classmethod
    def _validate_action_sequence(cls, value: Iterable[object] | None) -> tuple[str, ...]:
        return normalize_unique(value)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _validate_timestamp(cls, value: datetime | str) -> datetime:
        return normalize_datetime(value)

    @property
    def signature(self) -> str:
        context_domain = str(self.context.get("domain", "")).strip().lower()
        message_terms = " ".join(self.message.lower().split()[:8])
        return "|".join(
            item
            for item in (self.failure_type.lower(), self.tool or "", context_domain, message_terms)
            if item
        )


class SuccessRecord(DreamingModel):
    success_id: str = Field(default_factory=new_ulid, min_length=1)
    session_id: str = Field(..., min_length=1)
    outcome: str = Field(..., min_length=1)
    action_sequence: tuple[str, ...] = Field(default_factory=tuple)
    tools: tuple[str, ...] = Field(default_factory=tuple)
    context: dict[str, Any] = Field(default_factory=dict)
    duration_seconds: float | None = Field(default=None, ge=0.0)
    timestamp: datetime = Field(default_factory=utc_now)

    @field_validator("action_sequence", "tools", mode="before")
    @classmethod
    def _validate_unique_tuple(cls, value: Iterable[object] | None) -> tuple[str, ...]:
        return normalize_unique(value)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _validate_timestamp(cls, value: datetime | str) -> datetime:
        return normalize_datetime(value)


class SessionSummary(DreamingModel):
    session_id: str = Field(..., min_length=1)
    objective: str = Field(default="")
    started_at: datetime = Field(default_factory=utc_now)
    ended_at: datetime | None = None
    status: str = Field(default="completed", min_length=1)
    events: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    actions: tuple[ActionRecord, ...] = Field(default_factory=tuple)
    failures: tuple[FailureRecord, ...] = Field(default_factory=tuple)
    successes: tuple[SuccessRecord, ...] = Field(default_factory=tuple)
    context: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("started_at", "ended_at", mode="before")
    @classmethod
    def _validate_datetime(cls, value: datetime | str | None) -> datetime | None:
        return normalize_datetime(value) if value is not None else None

    @field_validator("actions", mode="before")
    @classmethod
    def _validate_actions(
        cls,
        value: Iterable[ActionRecord | dict[str, Any]] | None,
    ) -> tuple[ActionRecord, ...]:
        if value is None:
            return ()
        return tuple(
            item if isinstance(item, ActionRecord) else ActionRecord.model_validate(item)
            for item in value
        )

    @field_validator("failures", mode="before")
    @classmethod
    def _validate_failures(
        cls,
        value: Iterable[FailureRecord | dict[str, Any]] | None,
    ) -> tuple[FailureRecord, ...]:
        if value is None:
            return ()
        return tuple(
            item if isinstance(item, FailureRecord) else FailureRecord.model_validate(item)
            for item in value
        )

    @field_validator("successes", mode="before")
    @classmethod
    def _validate_successes(
        cls,
        value: Iterable[SuccessRecord | dict[str, Any]] | None,
    ) -> tuple[SuccessRecord, ...]:
        if value is None:
            return ()
        return tuple(
            item if isinstance(item, SuccessRecord) else SuccessRecord.model_validate(item)
            for item in value
        )

    @property
    def duration_seconds(self) -> float | None:
        if self.ended_at is None:
            return None
        return max((self.ended_at - self.started_at).total_seconds(), 0.0)

    @property
    def succeeded(self) -> bool:
        return self.status.lower() in {"completed", "success", "succeeded"} and not self.failures


class Pattern(DreamingModel):
    pattern_id: str = Field(default_factory=new_ulid, min_length=1)
    kind: PatternKind
    signature: str = Field(..., min_length=1)
    description: str = Field(default="")
    sequence: tuple[str, ...] = Field(default_factory=tuple)
    tools: tuple[str, ...] = Field(default_factory=tuple)
    contexts: tuple[str, ...] = Field(default_factory=tuple)
    support: int = Field(default=1, ge=1)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    outcome: str = Field(default="")
    session_ids: tuple[str, ...] = Field(default_factory=tuple)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("sequence", "tools", "contexts", "session_ids", mode="before")
    @classmethod
    def _validate_tuples(cls, value: Iterable[object] | None) -> tuple[str, ...]:
        return normalize_unique(value)


class FailureCluster(DreamingModel):
    cluster_id: str = Field(default_factory=new_ulid, min_length=1)
    signature: str = Field(..., min_length=1)
    failure_type: str = Field(..., min_length=1)
    failures: tuple[FailureRecord, ...]
    count: int = Field(default=1, ge=1)
    representative_message: str = Field(default="")
    common_tools: tuple[str, ...] = Field(default_factory=tuple)
    common_context: dict[str, Any] = Field(default_factory=dict)
    severity: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("common_tools", mode="before")
    @classmethod
    def _validate_common_tools(cls, value: Iterable[object] | None) -> tuple[str, ...]:
        return normalize_unique(value, sort=True)

    @model_validator(mode="after")
    def _validate_count(self) -> FailureCluster:
        if self.count != len(self.failures):
            object.__setattr__(self, "count", len(self.failures))
        return self


class Strategy(DreamingModel):
    strategy_id: str = Field(default_factory=new_ulid, min_length=1)
    name: str = Field(..., min_length=1)
    action_sequence: tuple[str, ...] = Field(default_factory=tuple)
    tools: tuple[str, ...] = Field(default_factory=tuple)
    contexts: tuple[str, ...] = Field(default_factory=tuple)
    support: int = Field(default=1, ge=1)
    success_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    average_duration_seconds: float | None = Field(default=None, ge=0.0)
    rationale: str = Field(default="")

    @field_validator("action_sequence", "tools", "contexts", mode="before")
    @classmethod
    def _validate_tuples(cls, value: Iterable[object] | None) -> tuple[str, ...]:
        return normalize_unique(value)


class HarnessOptimization(DreamingModel):
    optimization_id: str = Field(default_factory=new_ulid, min_length=1)
    optimization_type: OptimizationType
    target: str = Field(..., min_length=1)
    change: dict[str, Any] = Field(default_factory=dict)
    rationale: str = Field(default="")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    expected_impact: float = Field(default=0.0, ge=-1.0, le=1.0)
    evidence: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("evidence", mode="before")
    @classmethod
    def _validate_evidence(cls, value: Iterable[object] | None) -> tuple[str, ...]:
        return normalize_unique(value)


class Optimization(HarnessOptimization):
    status: OptimizationStatus = OptimizationStatus.PROPOSED
    created_at: datetime = Field(default_factory=utc_now)
    applied_at: datetime | None = None
    rolled_back_at: datetime | None = None

    @field_validator("created_at", "applied_at", "rolled_back_at", mode="before")
    @classmethod
    def _validate_datetime(cls, value: datetime | str | None) -> datetime | None:
        return normalize_datetime(value) if value is not None else None


class ApplyResult(DreamingModel):
    optimization_id: str = Field(..., min_length=1)
    applied: bool
    status: OptimizationStatus
    previous_value: Any = None
    new_value: Any = None
    message: str = Field(default="")


class ImpactMetrics(DreamingModel):
    optimization_id: str = Field(..., min_length=1)
    sample_size: int = Field(default=0, ge=0)
    baseline_success_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    current_success_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    baseline_duration_seconds: float | None = Field(default=None, ge=0.0)
    current_duration_seconds: float | None = Field(default=None, ge=0.0)
    regression_detected: bool = False
    improvement_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    measured_at: datetime = Field(default_factory=utc_now)

    @field_validator("measured_at", mode="before")
    @classmethod
    def _validate_measured_at(cls, value: datetime | str) -> datetime:
        return normalize_datetime(value)


class PruneResult(DreamingModel):
    pruned_ids: tuple[str, ...] = Field(default_factory=tuple)
    retained_ids: tuple[str, ...] = Field(default_factory=tuple)
    confidence_adjustments: dict[str, float] = Field(default_factory=dict)
    reasons: dict[str, str] = Field(default_factory=dict)

    @field_validator("pruned_ids", "retained_ids", mode="before")
    @classmethod
    def _validate_ids(cls, value: Iterable[object] | None) -> tuple[str, ...]:
        return normalize_unique(value)


class DreamReport(DreamingModel):
    report_id: str = Field(default_factory=new_ulid, min_length=1)
    session_ids: tuple[str, ...] = Field(default_factory=tuple)
    generated_at: datetime = Field(default_factory=utc_now)
    patterns: tuple[Pattern, ...] = Field(default_factory=tuple)
    failure_clusters: tuple[FailureCluster, ...] = Field(default_factory=tuple)
    strategies: tuple[Strategy, ...] = Field(default_factory=tuple)
    recommendations: tuple[HarnessOptimization, ...] = Field(default_factory=tuple)
    prune_result: PruneResult | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)

    @field_validator("session_ids", mode="before")
    @classmethod
    def _validate_session_ids(cls, value: Iterable[object] | None) -> tuple[str, ...]:
        return normalize_unique(value)

    @field_validator("generated_at", mode="before")
    @classmethod
    def _validate_generated_at(cls, value: datetime | str) -> datetime:
        return normalize_datetime(value)
