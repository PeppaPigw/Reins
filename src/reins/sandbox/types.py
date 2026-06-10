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


class ResourceKind(str, Enum):
    CPU_MS = "cpu_ms"
    MEMORY_BYTES = "memory_bytes"
    DISK_BYTES = "disk_bytes"
    NETWORK_BYTES = "network_bytes"
    API_CALLS = "api_calls"
    TOKEN_COUNT = "token_count"
    FILE_OPERATIONS = "file_operations"
    SUBPROCESS_COUNT = "subprocess_count"


class SandboxStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"
    BREACHED = "breached"


class ViolationAction(str, Enum):
    WARN = "warn"
    THROTTLE = "throttle"
    SUSPEND = "suspend"
    TERMINATE = "terminate"


class IsolationLevel(str, Enum):
    NONE = "none"
    PROCESS = "process"
    CONTAINER = "container"
    FULL = "full"


class ResourceLimit(BaseModel):
    model_config = ConfigDict(frozen=True)

    resource: ResourceKind
    soft_limit: float
    hard_limit: float
    window_ms: float = 0.0
    on_soft_breach: ViolationAction = ViolationAction.WARN
    on_hard_breach: ViolationAction = ViolationAction.TERMINATE


class ResourceUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    resource: ResourceKind
    current: float = 0.0
    peak: float = 0.0
    total: float = 0.0
    limit: ResourceLimit | None = None
    utilization_pct: float = 0.0


class CapabilityGrant(BaseModel):
    model_config = ConfigDict(frozen=True)

    grant_id: str = Field(default_factory=_new_ulid)
    capability: str
    allowed: bool = True
    conditions: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None


class SandboxViolation(BaseModel):
    model_config = ConfigDict(frozen=True)

    violation_id: str = Field(default_factory=_new_ulid)
    sandbox_id: str
    resource: ResourceKind | None = None
    capability: str = ""
    message: str
    action_taken: ViolationAction
    value: float = 0.0
    limit: float = 0.0
    timestamp: datetime = Field(default_factory=_utc_now)


class SandboxConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    sandbox_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    isolation_level: IsolationLevel = IsolationLevel.PROCESS
    resource_limits: tuple[ResourceLimit, ...] = ()
    capabilities: tuple[CapabilityGrant, ...] = ()
    max_lifetime_ms: float = 300000.0
    allow_network: bool = True
    allow_filesystem: bool = True
    allowed_paths: tuple[str, ...] = ()
    blocked_paths: tuple[str, ...] = ()


class SandboxState(BaseModel):
    model_config = ConfigDict(frozen=True)

    sandbox_id: str
    agent_id: str
    status: SandboxStatus = SandboxStatus.ACTIVE
    usage: tuple[ResourceUsage, ...] = ()
    violations: tuple[SandboxViolation, ...] = ()
    created_at: datetime = Field(default_factory=_utc_now)
    terminated_at: datetime | None = None


class SandboxStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_sandboxes: int = 0
    active: int = 0
    terminated: int = 0
    breached: int = 0
    total_violations: int = 0
    by_resource: dict[str, float] = Field(default_factory=dict)
