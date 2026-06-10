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


class RewardDimension(str, Enum):
    CORRECTNESS = "correctness"
    EFFICIENCY = "efficiency"
    SAFETY = "safety"
    CREATIVITY = "creativity"
    COMPLIANCE = "compliance"
    USER_SATISFACTION = "user_satisfaction"
    COST = "cost"
    SPEED = "speed"


class ShapingStrategy(str, Enum):
    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    THRESHOLD = "threshold"
    DIMINISHING = "diminishing"
    PENALTY_DOMINANT = "penalty_dominant"


class RewardSignal(BaseModel):
    model_config = ConfigDict(frozen=True)

    signal_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    dimension: RewardDimension
    raw_value: float
    shaped_value: float = 0.0
    weight: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    recorded_at: datetime = Field(default_factory=_utc_now)


class RewardPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    dimension: RewardDimension
    weight: float = 1.0
    strategy: ShapingStrategy = ShapingStrategy.LINEAR
    floor: float = -1.0
    ceiling: float = 1.0
    threshold: float = 0.5
    decay: float = 0.95


class RewardProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str
    total_reward: float = 0.0
    avg_reward: float = 0.0
    signal_count: int = 0
    by_dimension: dict[str, float] = Field(default_factory=dict)
    trend: float = 0.0


class RewardStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    agents_tracked: int = 0
    total_signals: int = 0
    avg_shaped_reward: float = 0.0
    by_dimension: dict[str, int] = Field(default_factory=dict)
    by_strategy: dict[str, int] = Field(default_factory=dict)
