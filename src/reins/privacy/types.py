from __future__ import annotations

import math
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import ulid
from pydantic import BaseModel, ConfigDict, Field


def _new_ulid() -> str:
    return str(ulid.new())


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PrivacyMechanism(str, Enum):
    LAPLACE = "laplace"
    GAUSSIAN = "gaussian"
    EXPONENTIAL = "exponential"
    RANDOMIZED_RESPONSE = "randomized_response"


class PrivacyLevel(str, Enum):
    PUBLIC = "public"
    LOW_SENSITIVITY = "low_sensitivity"
    MODERATE_SENSITIVITY = "moderate_sensitivity"
    HIGH_SENSITIVITY = "high_sensitivity"
    CRITICAL = "critical"


class BudgetStatus(str, Enum):
    AVAILABLE = "available"
    LOW = "low"
    EXHAUSTED = "exhausted"
    EXCEEDED = "exceeded"


class PrivacyBudget(BaseModel):
    model_config = ConfigDict(frozen=True)

    budget_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    epsilon_total: float = 1.0
    epsilon_spent: float = 0.0
    delta_total: float = 1e-5
    delta_spent: float = 0.0
    queries_made: int = 0


class PrivacyQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    query_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    data_key: str
    mechanism: PrivacyMechanism = PrivacyMechanism.LAPLACE
    epsilon_cost: float = 0.0
    delta_cost: float = 0.0
    sensitivity: float = 1.0
    true_value: float = 0.0
    noisy_value: float = 0.0
    noise_added: float = 0.0
    queried_at: datetime = Field(default_factory=_utc_now)


class DataRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    record_id: str = Field(default_factory=_new_ulid)
    key: str
    value: float = 0.0
    sensitivity: float = 1.0
    level: PrivacyLevel = PrivacyLevel.MODERATE_SENSITIVITY
    metadata: dict[str, Any] = Field(default_factory=dict)


class PrivacyStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_agents: int = 0
    total_queries: int = 0
    total_records: int = 0
    avg_epsilon_spent: float = 0.0
    budgets_exhausted: int = 0
    by_mechanism: dict[str, int] = Field(default_factory=dict)
    by_level: dict[str, int] = Field(default_factory=dict)
