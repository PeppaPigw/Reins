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


class ContextPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    BACKGROUND = "background"


class DecayStrategy(str, Enum):
    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    STEP = "step"
    NONE = "none"


class EvictionReason(str, Enum):
    TOKEN_BUDGET = "token_budget"
    RELEVANCE_DECAY = "relevance_decay"
    STALENESS = "staleness"
    MANUAL = "manual"
    PRIORITY_DISPLACEMENT = "priority_displacement"


class ContextShard(BaseModel):
    model_config = ConfigDict(frozen=True)

    shard_id: str = Field(default_factory=_new_ulid)
    content: str
    source: str = ""
    priority: ContextPriority = ContextPriority.MEDIUM
    token_count: int = 0
    relevance_score: float = 1.0
    decay_strategy: DecayStrategy = DecayStrategy.EXPONENTIAL
    tags: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=_utc_now)
    last_accessed: datetime = Field(default_factory=_utc_now)
    access_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class TokenBudget(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_tokens: int = 128000
    reserved_system: int = 4000
    reserved_output: int = 4096
    max_context_pct: float = 0.75
    min_shard_tokens: int = 50


class ContextWindow(BaseModel):
    model_config = ConfigDict(frozen=True)

    window_id: str = Field(default_factory=_new_ulid)
    shards: tuple[ContextShard, ...] = ()
    total_tokens_used: int = 0
    budget: TokenBudget = Field(default_factory=TokenBudget)
    assembled_at: datetime = Field(default_factory=_utc_now)


class EvictionEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=_new_ulid)
    shard_id: str
    reason: EvictionReason
    relevance_at_eviction: float = 0.0
    tokens_freed: int = 0
    evicted_at: datetime = Field(default_factory=_utc_now)


class ContextStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_shards: int = 0
    total_tokens: int = 0
    budget_utilization: float = 0.0
    avg_relevance: float = 0.0
    evictions_total: int = 0
    cache_hit_rate: float = 0.0
