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


class ThrottleStrategy(str, Enum):
    TOKEN_BUCKET = "token_bucket"
    SLIDING_WINDOW = "sliding_window"
    FIXED_WINDOW = "fixed_window"
    LEAKY_BUCKET = "leaky_bucket"


class BackpressureAction(str, Enum):
    ALLOW = "allow"
    THROTTLE = "throttle"
    QUEUE = "queue"
    REJECT = "reject"
    SHED_LOAD = "shed_load"


class ThrottleScope(str, Enum):
    GLOBAL = "global"
    PER_AGENT = "per_agent"
    PER_RESOURCE = "per_resource"
    PER_OPERATION = "per_operation"


class RateLimitConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    config_id: str = Field(default_factory=_new_ulid)
    name: str
    strategy: ThrottleStrategy = ThrottleStrategy.TOKEN_BUCKET
    scope: ThrottleScope = ThrottleScope.PER_AGENT
    max_rate: float = 100.0
    burst_size: int = 10
    window_seconds: float = 60.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class ThrottleDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    resource: str = ""
    action: BackpressureAction = BackpressureAction.ALLOW
    tokens_remaining: float = 0.0
    wait_ms: float = 0.0
    reason: str = ""
    decided_at: datetime = Field(default_factory=_utc_now)


class QueueEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    entry_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    resource: str = ""
    priority: int = 0
    enqueued_at: datetime = Field(default_factory=_utc_now)


class ThrottleStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_requests: int = 0
    allowed: int = 0
    throttled: int = 0
    queued: int = 0
    rejected: int = 0
    avg_wait_ms: float = 0.0
    by_agent: dict[str, int] = Field(default_factory=dict)
    by_resource: dict[str, int] = Field(default_factory=dict)
