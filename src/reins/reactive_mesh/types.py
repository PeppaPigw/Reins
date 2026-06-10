from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

import ulid
from pydantic import BaseModel, ConfigDict, Field


def _ulid() -> str:
    return str(ulid.new())


def _now() -> datetime:
    return datetime.now(UTC)


class ReactionKind(str, Enum):
    BLOCK = "block"
    THROTTLE = "throttle"
    ALERT = "alert"
    QUARANTINE = "quarantine"
    ROLLBACK = "rollback"
    ESCALATE = "escalate"


class TriggerCondition(str, Enum):
    EVENT_MATCH = "event_match"
    THRESHOLD_BREACH = "threshold_breach"
    PATTERN_DETECTED = "pattern_detected"
    ANOMALY = "anomaly"


class ReactiveRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_id: str = Field(default_factory=_ulid)
    name: str
    trigger: TriggerCondition
    topic_pattern: str
    reaction: ReactionKind
    threshold: float = 0.0
    window_seconds: float = 60.0
    cooldown_seconds: float = 10.0
    enabled: bool = True


class Reaction(BaseModel):
    model_config = ConfigDict(frozen=True)

    reaction_id: str = Field(default_factory=_ulid)
    rule_id: str
    rule_name: str
    kind: ReactionKind
    trigger_event_id: str
    agent_id: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    ts: datetime = Field(default_factory=_now)


class MeshStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_rules: int = 0
    total_reactions: int = 0
    by_reaction_kind: dict[str, int] = Field(default_factory=dict)
    by_trigger: dict[str, int] = Field(default_factory=dict)
    agents_quarantined: int = 0
