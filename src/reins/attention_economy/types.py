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


class AttentionPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"
    BACKGROUND = "background"


class ContentType(str, Enum):
    INSTRUCTION = "instruction"
    CONTEXT = "context"
    EXAMPLE = "example"
    CONSTRAINT = "constraint"
    FEEDBACK = "feedback"
    MEMORY = "memory"


class EvictionPolicy(str, Enum):
    LRU = "lru"
    LFU = "lfu"
    PRIORITY = "priority"
    RELEVANCE = "relevance"
    HYBRID = "hybrid"


class AttentionSlot(BaseModel):
    model_config = ConfigDict(frozen=True)

    slot_id: str = Field(default_factory=_new_ulid)
    content: str
    content_type: ContentType
    priority: AttentionPriority = AttentionPriority.NORMAL
    token_cost: int = 0
    relevance_score: float = 0.5
    access_count: int = 0
    last_accessed_at: datetime = Field(default_factory=_utc_now)
    created_at: datetime = Field(default_factory=_utc_now)


class AttentionBudget(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_tokens: int
    used_tokens: int = 0
    reserved_tokens: int = 0
    available_tokens: int = 0


class EvictionEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=_new_ulid)
    evicted_slot_id: str
    reason: str
    tokens_freed: int = 0
    evicted_at: datetime = Field(default_factory=_utc_now)


class AttentionStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_slots: int = 0
    total_tokens_used: int = 0
    budget_utilization: float = 0.0
    evictions: int = 0
    avg_relevance: float = 0.0
    by_type: dict[str, int] = Field(default_factory=dict)
    by_priority: dict[str, int] = Field(default_factory=dict)
