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


class TaskStatus(str, Enum):
    ANNOUNCED = "announced"
    BIDDING = "bidding"
    AWARDED = "awarded"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BidStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class SelectionStrategy(str, Enum):
    LOWEST_COST = "lowest_cost"
    HIGHEST_QUALITY = "highest_quality"
    BEST_VALUE = "best_value"
    FASTEST = "fastest"
    REPUTATION = "reputation"


class TaskAnnouncement(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str = Field(default_factory=_new_ulid)
    manager_id: str
    description: str
    requirements: dict[str, Any] = Field(default_factory=dict)
    deadline_ms: float = 0.0
    max_cost: float = 0.0
    status: TaskStatus = TaskStatus.ANNOUNCED
    created_at: datetime = Field(default_factory=_utc_now)


class Bid(BaseModel):
    model_config = ConfigDict(frozen=True)

    bid_id: str = Field(default_factory=_new_ulid)
    task_id: str
    bidder_id: str
    cost: float = 0.0
    estimated_duration_ms: float = 0.0
    quality_score: float = 0.5
    capabilities: tuple[str, ...] = ()
    status: BidStatus = BidStatus.PENDING
    submitted_at: datetime = Field(default_factory=_utc_now)


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True)

    contract_id: str = Field(default_factory=_new_ulid)
    task_id: str
    manager_id: str
    contractor_id: str
    agreed_cost: float = 0.0
    agreed_duration_ms: float = 0.0
    awarded_at: datetime = Field(default_factory=_utc_now)


class ContractNetStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_announcements: int = 0
    total_bids: int = 0
    total_contracts: int = 0
    completed: int = 0
    failed: int = 0
    avg_bids_per_task: float = 0.0
    avg_cost: float = 0.0
    by_status: dict[str, int] = Field(default_factory=dict)
