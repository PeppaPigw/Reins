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


class FailureKind(str, Enum):
    TRANSIENT = "transient"
    PERSISTENT = "persistent"
    CASCADING = "cascading"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    TIMEOUT = "timeout"
    CORRUPTION = "corruption"
    DEPENDENCY = "dependency"
    UNKNOWN = "unknown"


class RecoveryStrategy(str, Enum):
    RETRY = "retry"
    RETRY_WITH_BACKOFF = "retry_with_backoff"
    ROLLBACK = "rollback"
    CIRCUIT_BREAK = "circuit_break"
    FAILOVER = "failover"
    ESCALATE = "escalate"
    QUARANTINE = "quarantine"
    RESTART = "restart"


class RecoveryOutcome(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    ESCALATED = "escalated"


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    CRITICAL = "critical"


class Failure(BaseModel):
    model_config = ConfigDict(frozen=True)

    failure_id: str = Field(default_factory=_new_ulid)
    component_id: str
    kind: FailureKind
    message: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=_utc_now)


class RecoveryAttempt(BaseModel):
    model_config = ConfigDict(frozen=True)

    attempt_id: str = Field(default_factory=_new_ulid)
    failure_id: str
    component_id: str
    strategy: RecoveryStrategy
    outcome: RecoveryOutcome
    duration_ms: float = 0.0
    details: str = ""
    attempted_at: datetime = Field(default_factory=_utc_now)


class RecoveryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    failure_kind: FailureKind
    strategies: tuple[RecoveryStrategy, ...] = ()
    max_retries: int = 3
    backoff_base_ms: float = 100.0
    backoff_multiplier: float = 2.0
    circuit_break_threshold: int = 5
    quarantine_duration_ms: float = 30000.0


class ComponentHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    component_id: str
    status: HealthStatus = HealthStatus.HEALTHY
    consecutive_failures: int = 0
    total_failures: int = 0
    total_recoveries: int = 0
    last_failure_at: datetime | None = None
    last_recovery_at: datetime | None = None
    circuit_open: bool = False


class HealingStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_failures: int = 0
    total_recoveries: int = 0
    successful_recoveries: int = 0
    failed_recoveries: int = 0
    recovery_rate: float = 0.0
    components_monitored: int = 0
    components_healthy: int = 0
    components_degraded: int = 0
    components_critical: int = 0
    by_strategy: dict[str, int] = Field(default_factory=dict)
    by_failure_kind: dict[str, int] = Field(default_factory=dict)
