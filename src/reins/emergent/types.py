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


class PatternKind(str, Enum):
    HERDING = "herding"
    CASCADE = "cascade"
    FEEDBACK_LOOP = "feedback_loop"
    SYNCHRONIZATION = "synchronization"
    POLARIZATION = "polarization"
    ECHO_CHAMBER = "echo_chamber"
    DEADLOCK_SPIRAL = "deadlock_spiral"
    RESOURCE_HOARDING = "resource_hoarding"


class Severity(str, Enum):
    BENIGN = "benign"
    NOTABLE = "notable"
    CONCERNING = "concerning"
    CRITICAL = "critical"


class AgentAction(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    action_type: str
    target: str = ""
    value: float = 0.0
    timestamp: datetime = Field(default_factory=_utc_now)


class EmergentPattern(BaseModel):
    model_config = ConfigDict(frozen=True)

    pattern_id: str = Field(default_factory=_new_ulid)
    kind: PatternKind
    severity: Severity = Severity.NOTABLE
    agents_involved: tuple[str, ...] = ()
    description: str = ""
    confidence: float = 0.5
    evidence_count: int = 0
    detected_at: datetime = Field(default_factory=_utc_now)


class CollectiveMetric(BaseModel):
    model_config = ConfigDict(frozen=True)

    metric_id: str = Field(default_factory=_new_ulid)
    name: str
    value: float = 0.0
    agents_sampled: int = 0
    timestamp: datetime = Field(default_factory=_utc_now)


class EmergentStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_actions: int = 0
    total_patterns: int = 0
    agents_monitored: int = 0
    by_pattern_kind: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)
    avg_confidence: float = 0.0
