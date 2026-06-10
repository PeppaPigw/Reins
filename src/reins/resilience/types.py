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


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class DegradationLevel(str, Enum):
    NONE = "none"
    MINOR = "minor"
    MODERATE = "moderate"
    SEVERE = "severe"
    CRITICAL = "critical"


class FaultKind(str, Enum):
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"
    RATE_LIMIT = "rate_limit"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    DEPENDENCY_FAILURE = "dependency_failure"
    DATA_CORRUPTION = "data_corruption"


class RecoveryAction(str, Enum):
    RETRY = "retry"
    FALLBACK = "fallback"
    SHED_LOAD = "shed_load"
    ISOLATE = "isolate"
    RESTART = "restart"
    ESCALATE = "escalate"


class CircuitBreaker(BaseModel):
    model_config = ConfigDict(frozen=True)

    breaker_id: str = Field(default_factory=_new_ulid)
    name: str
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    failure_threshold: int = 5
    recovery_timeout_ms: int = 30000
    half_open_max_calls: int = 3
    last_failure_at: datetime | None = None
    opened_at: datetime | None = None


class BulkheadPartition(BaseModel):
    model_config = ConfigDict(frozen=True)

    partition_id: str = Field(default_factory=_new_ulid)
    name: str
    max_concurrent: int = 10
    current_load: int = 0
    queued: int = 0
    rejected: int = 0


class FaultEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=_new_ulid)
    service: str
    kind: FaultKind
    severity: DegradationLevel = DegradationLevel.MINOR
    message: str = ""
    recovery_action: RecoveryAction = RecoveryAction.RETRY
    resolved: bool = False
    occurred_at: datetime = Field(default_factory=_utc_now)


class ResiliencePolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy_id: str = Field(default_factory=_new_ulid)
    service: str
    max_retries: int = 3
    retry_delay_ms: int = 1000
    timeout_ms: int = 5000
    fallback_service: str = ""
    circuit_breaker_threshold: int = 5


class ResilienceStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_breakers: int = 0
    open_breakers: int = 0
    total_partitions: int = 0
    total_faults: int = 0
    unresolved_faults: int = 0
    degradation_level: DegradationLevel = DegradationLevel.NONE
    by_fault_kind: dict[str, int] = Field(default_factory=dict)
    by_recovery_action: dict[str, int] = Field(default_factory=dict)
