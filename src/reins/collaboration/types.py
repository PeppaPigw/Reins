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


class ChannelKind(str, Enum):
    PUBSUB = "pubsub"
    REQUEST_REPLY = "request_reply"
    BROADCAST = "broadcast"
    DIRECT = "direct"
    PIPELINE = "pipeline"


class MessagePriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class DeliveryStatus(str, Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    ACKNOWLEDGED = "acknowledged"
    FAILED = "failed"
    EXPIRED = "expired"


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class Message(BaseModel):
    model_config = ConfigDict(frozen=True)

    message_id: str = Field(default_factory=_new_ulid)
    channel_id: str
    sender_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: MessagePriority = MessagePriority.NORMAL
    reply_to: str | None = None
    correlation_id: str | None = None
    ttl_ms: float = 30000.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)


class Channel(BaseModel):
    model_config = ConfigDict(frozen=True)

    channel_id: str = Field(default_factory=_new_ulid)
    name: str
    kind: ChannelKind
    description: str = ""
    max_subscribers: int = 0
    message_ttl_ms: float = 60000.0
    created_at: datetime = Field(default_factory=_utc_now)


class Subscription(BaseModel):
    model_config = ConfigDict(frozen=True)

    subscription_id: str = Field(default_factory=_new_ulid)
    channel_id: str
    subscriber_id: str
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    filter_tags: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=_utc_now)


class Delivery(BaseModel):
    model_config = ConfigDict(frozen=True)

    delivery_id: str = Field(default_factory=_new_ulid)
    message_id: str
    recipient_id: str
    status: DeliveryStatus = DeliveryStatus.PENDING
    delivered_at: datetime | None = None
    acknowledged_at: datetime | None = None


class ChannelStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_channels: int = 0
    total_messages: int = 0
    total_subscriptions: int = 0
    messages_delivered: int = 0
    messages_failed: int = 0
    avg_delivery_time_ms: float = 0.0
    by_channel_kind: dict[str, int] = Field(default_factory=dict)
