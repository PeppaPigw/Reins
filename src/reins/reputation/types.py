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


class ReputationTier(str, Enum):
    UNTRUSTED = "untrusted"
    NEWCOMER = "newcomer"
    ESTABLISHED = "established"
    TRUSTED = "trusted"
    ELITE = "elite"


class FeedbackKind(str, Enum):
    ENDORSEMENT = "endorsement"
    WARNING = "warning"
    PENALTY = "penalty"
    ACHIEVEMENT = "achievement"
    DECAY = "decay"


class ReputationEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    kind: FeedbackKind
    delta: float = 0.0
    reason: str = ""
    source_agent: str = ""
    timestamp: datetime = Field(default_factory=_utc_now)


class AgentReputation(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str
    score: float = 50.0
    tier: ReputationTier = ReputationTier.NEWCOMER
    total_endorsements: int = 0
    total_penalties: int = 0
    streak: int = 0
    last_activity: datetime | None = None


class Endorsement(BaseModel):
    model_config = ConfigDict(frozen=True)

    endorsement_id: str = Field(default_factory=_new_ulid)
    from_agent: str
    to_agent: str
    weight: float = 1.0
    category: str = ""
    timestamp: datetime = Field(default_factory=_utc_now)


class ReputationPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy_id: str = Field(default_factory=_new_ulid)
    min_score_for_action: float = 0.0
    required_tier: ReputationTier = ReputationTier.NEWCOMER
    action: str = ""


class ReputationStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_agents: int = 0
    avg_score: float = 0.0
    total_events: int = 0
    total_endorsements: int = 0
    by_tier: dict[str, int] = Field(default_factory=dict)
