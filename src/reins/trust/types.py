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


class TrustDimension(str, Enum):
    CORRECTNESS = "correctness"
    SAFETY = "safety"
    EFFICIENCY = "efficiency"
    COMPLIANCE = "compliance"
    RELIABILITY = "reliability"


class AutonomyLevel(str, Enum):
    SUPERVISED = "supervised"
    GUIDED = "guided"
    AUTONOMOUS = "autonomous"
    FULLY_TRUSTED = "fully_trusted"


class ReputationEventKind(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    VIOLATION = "violation"
    TIMEOUT = "timeout"
    RECOVERY = "recovery"
    ESCALATION = "escalation"


class TrustDecay(str, Enum):
    NONE = "none"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"


class TrustScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    dimension: TrustDimension
    score: float = 0.5
    confidence: float = 0.0
    sample_count: int = 0
    last_updated: datetime = Field(default_factory=_utc_now)


class ReputationEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    kind: ReputationEventKind
    dimension: TrustDimension
    magnitude: float = 1.0
    context: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utc_now)


class TrustProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str
    scores: tuple[TrustScore, ...] = ()
    autonomy_level: AutonomyLevel = AutonomyLevel.SUPERVISED
    total_events: int = 0
    created_at: datetime = Field(default_factory=_utc_now)
    last_event_at: datetime | None = None


class TrustThresholds(BaseModel):
    model_config = ConfigDict(frozen=True)

    guided_threshold: float = 0.4
    autonomous_threshold: float = 0.7
    fully_trusted_threshold: float = 0.9
    violation_penalty: float = 0.3
    failure_penalty: float = 0.1
    success_reward: float = 0.05
    recovery_bonus: float = 0.08
    min_samples_for_confidence: int = 10
    decay: TrustDecay = TrustDecay.EXPONENTIAL
    decay_half_life_hours: float = 168.0


class TrustDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str
    allowed: bool
    autonomy_level: AutonomyLevel
    composite_score: float
    limiting_dimension: TrustDimension | None = None
    reason: str = ""
