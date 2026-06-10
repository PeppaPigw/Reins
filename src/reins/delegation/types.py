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


class DelegationStatus(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ESCALATED = "escalated"
    REVOKED = "revoked"


class EscalationReason(str, Enum):
    CAPABILITY_MISMATCH = "capability_mismatch"
    TIMEOUT = "timeout"
    REPEATED_FAILURE = "repeated_failure"
    TRUST_INSUFFICIENT = "trust_insufficient"
    RESOURCE_UNAVAILABLE = "resource_unavailable"
    COMPLEXITY_EXCEEDED = "complexity_exceeded"


class DelegationPolicy(str, Enum):
    STRICT = "strict"
    FLEXIBLE = "flexible"
    CASCADING = "cascading"
    ROUND_ROBIN = "round_robin"


class Capability(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    level: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class DelegationTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str = Field(default_factory=_new_ulid)
    description: str
    required_capabilities: tuple[Capability, ...] = ()
    priority: int = 0
    max_attempts: int = 3
    timeout_ms: float = 60000.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)


class DelegationRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    record_id: str = Field(default_factory=_new_ulid)
    task_id: str
    delegator: str
    delegate: str
    status: DelegationStatus = DelegationStatus.PENDING
    attempt: int = 1
    escalation_reason: EscalationReason | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    assigned_at: datetime = Field(default_factory=_utc_now)
    completed_at: datetime | None = None


class AgentProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str
    capabilities: tuple[Capability, ...] = ()
    max_concurrent: int = 5
    current_load: int = 0
    trust_score: float = 1.0
    available: bool = True


class DelegationStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_delegations: int = 0
    completed: int = 0
    failed: int = 0
    escalated: int = 0
    avg_attempts: float = 0.0
    success_rate: float = 0.0
    agents_registered: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
