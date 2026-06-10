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


class EventPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class DeliveryGuarantee(str, Enum):
    AT_MOST_ONCE = "at_most_once"
    AT_LEAST_ONCE = "at_least_once"
    EXACTLY_ONCE = "exactly_once"


class BusEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=_ulid)
    topic: str
    source: str
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: EventPriority = EventPriority.NORMAL
    correlation_id: str | None = None
    causation_id: str | None = None
    ts: datetime = Field(default_factory=_now)


class Subscription(BaseModel):
    model_config = ConfigDict(frozen=True)

    sub_id: str = Field(default_factory=_ulid)
    topic_pattern: str
    subscriber_id: str
    filter_fn_id: str | None = None


class DeadLetter(BaseModel):
    model_config = ConfigDict(frozen=True)

    event: BusEvent
    subscriber_id: str
    error: str
    attempts: int = 1
    ts: datetime = Field(default_factory=_now)


class EventBusStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_published: int = 0
    total_delivered: int = 0
    total_dead_letters: int = 0
    active_subscriptions: int = 0
    topics: int = 0
    by_topic: dict[str, int] = Field(default_factory=dict)
