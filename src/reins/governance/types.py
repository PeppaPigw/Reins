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


class BudgetPeriod(str, Enum):
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class BudgetAlertKind(str, Enum):
    THRESHOLD_WARNING = "threshold_warning"
    THRESHOLD_CRITICAL = "threshold_critical"
    BUDGET_EXHAUSTED = "budget_exhausted"
    RATE_SPIKE = "rate_spike"
    FORECAST_OVERRUN = "forecast_overrun"


class CircuitBreakerStatus(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class ThrottleAction(str, Enum):
    ALLOW = "allow"
    THROTTLE = "throttle"
    DENY = "deny"


class AgentBudget(BaseModel):
    model_config = ConfigDict(frozen=True)

    budget_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    period: BudgetPeriod = BudgetPeriod.DAILY
    limit: float
    warning_threshold: float = 0.8
    critical_threshold: float = 0.95
    created_at: datetime = Field(default_factory=_utc_now)


class SpendRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    record_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    amount: float
    model_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    operation: str = ""
    timestamp: datetime = Field(default_factory=_utc_now)


class BudgetAlert(BaseModel):
    model_config = ConfigDict(frozen=True)

    alert_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    kind: BudgetAlertKind
    current_spend: float
    budget_limit: float
    utilization_pct: float
    message: str = ""
    triggered_at: datetime = Field(default_factory=_utc_now)


class CircuitBreakerState(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str
    status: CircuitBreakerStatus = CircuitBreakerStatus.CLOSED
    failure_count: int = 0
    last_failure_at: datetime | None = None
    opened_at: datetime | None = None
    half_open_at: datetime | None = None
    cooldown_seconds: int = 60


class CostForecast(BaseModel):
    model_config = ConfigDict(frozen=True)

    forecast_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    period: BudgetPeriod
    projected_spend: float
    current_spend: float
    burn_rate_per_hour: float
    hours_until_exhaustion: float | None = None
    confidence: float = 0.0
    computed_at: datetime = Field(default_factory=_utc_now)


class ThrottlePolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    action: ThrottleAction
    reason: str = ""
    retry_after_seconds: int = 0
    decided_at: datetime = Field(default_factory=_utc_now)
