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


class MessageKind(str, Enum):
    REQUEST = "request"
    RESPONSE = "response"
    NOTIFY = "notify"
    NEGOTIATE = "negotiate"
    HEARTBEAT = "heartbeat"
    ERROR = "error"


class NegotiationStatus(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    COUNTER = "counter"


class ChannelState(str, Enum):
    OPEN = "open"
    NEGOTIATING = "negotiating"
    ESTABLISHED = "established"
    CLOSED = "closed"


class ProtocolVersion(str, Enum):
    V1 = "1.0"


class ProtocolMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    message_id: str = Field(default_factory=_new_ulid)
    kind: MessageKind
    sender: str
    receiver: str
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str = ""
    version: ProtocolVersion = ProtocolVersion.V1
    sent_at: datetime = Field(default_factory=_utc_now)


class CapabilityOffer(BaseModel):
    model_config = ConfigDict(frozen=True)

    offer_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    capabilities: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    max_concurrency: int = 1


class NegotiationRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    negotiation_id: str = Field(default_factory=_new_ulid)
    initiator: str
    responder: str
    status: NegotiationStatus = NegotiationStatus.PROPOSED
    offered_capabilities: list[str] = Field(default_factory=list)
    accepted_capabilities: list[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=_utc_now)


class Channel(BaseModel):
    model_config = ConfigDict(frozen=True)

    channel_id: str = Field(default_factory=_new_ulid)
    agent_a: str
    agent_b: str
    state: ChannelState = ChannelState.OPEN
    negotiation_id: str = ""
    messages_sent: int = 0
    created_at: datetime = Field(default_factory=_utc_now)


class ProtocolStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_messages: int = 0
    total_channels: int = 0
    active_channels: int = 0
    total_negotiations: int = 0
    successful_negotiations: int = 0
    by_kind: dict[str, int] = Field(default_factory=dict)
    by_channel_state: dict[str, int] = Field(default_factory=dict)
