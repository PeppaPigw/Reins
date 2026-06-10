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
    TOKENS = "tokens"
    API_CALLS = "api_calls"
    FILE_OPS = "file_ops"
    WALL_TIME_SEC = "wall_time_sec"
    MEMORY_MB = "memory_mb"
    NETWORK_BYTES = "network_bytes"


class QuotaStatus(str, Enum):
    AVAILABLE = "available"
    WARNING = "warning"
    EXHAUSTED = "exhausted"
    PREEMPTED = "preempted"


class AllocationResult(str, Enum):
    GRANTED = "granted"
    DENIED = "denied"
    THROTTLED = "throttled"


class ResourceQuota(BaseModel):
    model_config = ConfigDict(frozen=True)

    quota_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    resource: ResourceKind
    limit: float
    used: float = 0.0
    warning_threshold: float = 0.8


class ResourceRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    resource: ResourceKind
    amount: float
    result: AllocationResult = AllocationResult.DENIED
    requested_at: datetime = Field(default_factory=_utc_now)


class ResourceAccountingStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_quotas: int = 0
    total_requests: int = 0
    granted: int = 0
    denied: int = 0
    throttled: int = 0
    by_resource: dict[str, float] = Field(default_factory=dict)
    by_agent: dict[str, float] = Field(default_factory=dict)
