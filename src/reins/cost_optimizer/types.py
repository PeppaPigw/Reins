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


class ModelTier(str, Enum):
    ECONOMY = "economy"
    STANDARD = "standard"
    PREMIUM = "premium"
    FLAGSHIP = "flagship"


class CostCategory(str, Enum):
    INPUT_TOKENS = "input_tokens"
    OUTPUT_TOKENS = "output_tokens"
    TOOL_CALLS = "tool_calls"
    EMBEDDING = "embedding"
    FINE_TUNING = "fine_tuning"
    INFRASTRUCTURE = "infrastructure"


class BudgetStatus(str, Enum):
    UNDER_BUDGET = "under_budget"
    WARNING = "warning"
    AT_LIMIT = "at_limit"
    OVER_BUDGET = "over_budget"


class TokenUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    usage_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    task_id: str = ""
    timestamp: datetime = Field(default_factory=_utc_now)


class Budget(BaseModel):
    model_config = ConfigDict(frozen=True)

    budget_id: str = Field(default_factory=_new_ulid)
    name: str
    limit_usd: float = 10.0
    spent_usd: float = 0.0
    warning_threshold: float = 0.8
    period_hours: int = 24
    created_at: datetime = Field(default_factory=_utc_now)


class ModelPricing(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    tier: ModelTier = ModelTier.STANDARD
    input_cost_per_1k: float = 0.0
    output_cost_per_1k: float = 0.0
    context_window: int = 128000


class RoutingDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_id: str = Field(default_factory=_new_ulid)
    requested_model: str
    routed_model: str
    reason: str = ""
    estimated_cost: float = 0.0
    budget_remaining: float = 0.0


class CostReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str = ""
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_requests: int = 0
    cost_per_request: float = 0.0
    by_model: dict[str, float] = Field(default_factory=dict)
    by_task: dict[str, float] = Field(default_factory=dict)


class CostStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_spend_usd: float = 0.0
    total_tokens: int = 0
    total_requests: int = 0
    active_budgets: int = 0
    budgets_exceeded: int = 0
    avg_cost_per_request: float = 0.0
    by_model: dict[str, float] = Field(default_factory=dict)
    by_tier: dict[str, float] = Field(default_factory=dict)
