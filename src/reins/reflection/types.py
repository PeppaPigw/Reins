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


class ReflectionKind(str, Enum):
    DECISION_REVIEW = "decision_review"
    OUTCOME_ANALYSIS = "outcome_analysis"
    STRATEGY_ASSESSMENT = "strategy_assessment"
    BIAS_DETECTION = "bias_detection"
    CONFIDENCE_CALIBRATION = "confidence_calibration"
    MISTAKE_ANALYSIS = "mistake_analysis"


class InsightCategory(str, Enum):
    PATTERN_RECOGNIZED = "pattern_recognized"
    BIAS_IDENTIFIED = "bias_identified"
    STRATEGY_EFFECTIVE = "strategy_effective"
    STRATEGY_INEFFECTIVE = "strategy_ineffective"
    CALIBRATION_ERROR = "calibration_error"
    NOVEL_APPROACH = "novel_approach"
    REPEATED_MISTAKE = "repeated_mistake"


class ConfidenceLevel(str, Enum):
    VERY_LOW = "very_low"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    VERY_HIGH = "very_high"


class Decision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    action: str
    reasoning: str = ""
    confidence: float = 0.5
    alternatives: tuple[str, ...] = ()
    context: dict[str, Any] = Field(default_factory=dict)
    made_at: datetime = Field(default_factory=_utc_now)


class Outcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome_id: str = Field(default_factory=_new_ulid)
    decision_id: str
    success: bool = True
    actual_result: str = ""
    expected_result: str = ""
    deviation_score: float = 0.0
    recorded_at: datetime = Field(default_factory=_utc_now)


class Insight(BaseModel):
    model_config = ConfigDict(frozen=True)

    insight_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    category: InsightCategory
    description: str
    confidence: float = 0.5
    source_decisions: tuple[str, ...] = ()
    actionable: bool = True
    discovered_at: datetime = Field(default_factory=_utc_now)


class Reflection(BaseModel):
    model_config = ConfigDict(frozen=True)

    reflection_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    kind: ReflectionKind
    decision_ids: tuple[str, ...] = ()
    insights: tuple[str, ...] = ()
    calibration_error: float = 0.0
    summary: str = ""
    reflected_at: datetime = Field(default_factory=_utc_now)


class ReflectionStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_decisions: int = 0
    total_outcomes: int = 0
    total_reflections: int = 0
    total_insights: int = 0
    agents_reflecting: int = 0
    avg_calibration_error: float = 0.0
    success_rate: float = 0.0
    by_category: dict[str, int] = Field(default_factory=dict)
