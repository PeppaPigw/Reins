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


class NegotiationStatus(str, Enum):
    OPEN = "open"
    COUNTER_OFFERED = "counter_offered"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    DEADLOCKED = "deadlocked"


class OfferKind(str, Enum):
    RESOURCE = "resource"
    TASK_ASSIGNMENT = "task_assignment"
    PRIORITY_SWAP = "priority_swap"
    TIME_SLOT = "time_slot"
    CAPABILITY_SHARE = "capability_share"


class ResolutionStrategy(str, Enum):
    FIRST_ACCEPT = "first_accept"
    BEST_OFFER = "best_offer"
    SPLIT_DIFFERENCE = "split_difference"
    MEDIATOR = "mediator"
    AUCTION = "auction"


class Offer(BaseModel):
    model_config = ConfigDict(frozen=True)

    offer_id: str = Field(default_factory=_new_ulid)
    negotiation_id: str
    from_agent: str
    to_agent: str
    kind: OfferKind
    value: float = 0.0
    terms: dict[str, Any] = Field(default_factory=dict)
    is_counter: bool = False
    parent_offer_id: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)


class Negotiation(BaseModel):
    model_config = ConfigDict(frozen=True)

    negotiation_id: str = Field(default_factory=_new_ulid)
    kind: OfferKind
    initiator: str
    responder: str
    status: NegotiationStatus = NegotiationStatus.OPEN
    strategy: ResolutionStrategy = ResolutionStrategy.FIRST_ACCEPT
    offers: tuple[Offer, ...] = ()
    max_rounds: int = 5
    current_round: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)
    resolved_at: datetime | None = None


class Agreement(BaseModel):
    model_config = ConfigDict(frozen=True)

    agreement_id: str = Field(default_factory=_new_ulid)
    negotiation_id: str
    parties: tuple[str, ...] = ()
    final_value: float = 0.0
    terms: dict[str, Any] = Field(default_factory=dict)
    agreed_at: datetime = Field(default_factory=_utc_now)


class NegotiationStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_negotiations: int = 0
    open_negotiations: int = 0
    accepted: int = 0
    rejected: int = 0
    deadlocked: int = 0
    total_offers: int = 0
    avg_rounds: float = 0.0
    agreement_rate: float = 0.0
    by_kind: dict[str, int] = Field(default_factory=dict)
