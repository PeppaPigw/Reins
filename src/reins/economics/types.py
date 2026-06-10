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
    COMPUTE = "compute"
    MEMORY = "memory"
    TOKENS = "tokens"
    API_CALLS = "api_calls"
    STORAGE = "storage"
    BANDWIDTH = "bandwidth"


class PricingModel(str, Enum):
    FIXED = "fixed"
    DYNAMIC = "dynamic"
    AUCTION = "auction"
    SUBSCRIPTION = "subscription"
    PAY_PER_USE = "pay_per_use"


class AllocationStrategy(str, Enum):
    PROPORTIONAL = "proportional"
    PRIORITY_BASED = "priority_based"
    MARKET_BASED = "market_based"
    FAIR_SHARE = "fair_share"
    UTILITY_MAXIMIZING = "utility_maximizing"


class Resource(BaseModel):
    model_config = ConfigDict(frozen=True)

    resource_id: str = Field(default_factory=_new_ulid)
    kind: ResourceKind
    name: str
    total_supply: float = 100.0
    unit_cost: float = 1.0
    pricing: PricingModel = PricingModel.PAY_PER_USE


class UtilityFunction(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str
    resource_id: str
    marginal_value: float = 1.0
    diminishing_rate: float = 0.1
    min_required: float = 0.0
    max_useful: float = 100.0


class Allocation(BaseModel):
    model_config = ConfigDict(frozen=True)

    allocation_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    resource_id: str
    amount: float = 0.0
    cost: float = 0.0
    utility_gained: float = 0.0
    allocated_at: datetime = Field(default_factory=_utc_now)


class MarketState(BaseModel):
    model_config = ConfigDict(frozen=True)

    resource_id: str
    current_price: float = 1.0
    supply_available: float = 100.0
    demand_total: float = 0.0
    utilization: float = 0.0


class EconomicStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_resources: int = 0
    total_allocations: int = 0
    total_cost: float = 0.0
    total_utility: float = 0.0
    efficiency_ratio: float = 0.0
    by_resource: dict[str, float] = Field(default_factory=dict)
    by_agent: dict[str, float] = Field(default_factory=dict)
