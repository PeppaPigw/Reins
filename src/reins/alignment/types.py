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


class ValueKind(str, Enum):
    SAFETY = "safety"
    HELPFULNESS = "helpfulness"
    HONESTY = "honesty"
    EFFICIENCY = "efficiency"
    FAIRNESS = "fairness"
    PRIVACY = "privacy"
    AUTONOMY = "autonomy"


class AlignmentStatus(str, Enum):
    ALIGNED = "aligned"
    DRIFTING = "drifting"
    MISALIGNED = "misaligned"
    UNCERTAIN = "uncertain"


class PreferenceSource(str, Enum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    DEFAULT = "default"
    CONSTITUTIONAL = "constitutional"


class Value(BaseModel):
    model_config = ConfigDict(frozen=True)

    value_id: str = Field(default_factory=_new_ulid)
    kind: ValueKind
    weight: float = 1.0
    description: str = ""
    constraints: tuple[str, ...] = ()


class Preference(BaseModel):
    model_config = ConfigDict(frozen=True)

    preference_id: str = Field(default_factory=_new_ulid)
    action_preferred: str
    action_dispreferred: str
    strength: float = 1.0
    source: PreferenceSource = PreferenceSource.EXPLICIT
    context: dict[str, Any] = Field(default_factory=dict)


class AlignmentCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    check_id: str = Field(default_factory=_new_ulid)
    action: str
    agent_id: str
    status: AlignmentStatus = AlignmentStatus.UNCERTAIN
    score: float = 0.0
    violations: tuple[str, ...] = ()
    satisfied_values: tuple[str, ...] = ()
    checked_at: datetime = Field(default_factory=_utc_now)


class AlignmentStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_checks: int = 0
    aligned: int = 0
    misaligned: int = 0
    drifting: int = 0
    total_values: int = 0
    total_preferences: int = 0
    avg_alignment_score: float = 0.0
    by_value: dict[str, float] = Field(default_factory=dict)
