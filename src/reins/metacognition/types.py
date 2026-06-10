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


class CognitiveState(str, Enum):
    FOCUSED = "focused"
    UNCERTAIN = "uncertain"
    CONFUSED = "confused"
    LOOPING = "looping"
    HALLUCINATING = "hallucinating"
    STUCK = "stuck"
    OVERCONFIDENT = "overconfident"


class InterventionKind(str, Enum):
    PAUSE = "pause"
    REFRAME = "reframe"
    ESCALATE = "escalate"
    BACKTRACK = "backtrack"
    SIMPLIFY = "simplify"
    VERIFY = "verify"
    ABORT = "abort"


class SignalSource(str, Enum):
    REPETITION_DETECTOR = "repetition_detector"
    CONFIDENCE_MONITOR = "confidence_monitor"
    PROGRESS_TRACKER = "progress_tracker"
    CONTRADICTION_CHECKER = "contradiction_checker"
    COMPLEXITY_MONITOR = "complexity_monitor"
    OUTPUT_VALIDATOR = "output_validator"


class CognitiveSignal(BaseModel):
    model_config = ConfigDict(frozen=True)

    signal_id: str = Field(default_factory=_new_ulid)
    source: SignalSource
    state: CognitiveState
    confidence: float = 0.5
    evidence: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime = Field(default_factory=_utc_now)


class Intervention(BaseModel):
    model_config = ConfigDict(frozen=True)

    intervention_id: str = Field(default_factory=_new_ulid)
    kind: InterventionKind
    trigger_state: CognitiveState
    trigger_signals: tuple[str, ...] = ()
    description: str = ""
    applied: bool = False
    effective: bool = False
    applied_at: datetime | None = None


class ReasoningStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    step_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    action: str
    output_hash: str = ""
    confidence: float = 0.5
    duration_ms: float = 0.0
    tokens_used: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utc_now)


class MetacognitionConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    repetition_threshold: int = 3
    confidence_floor: float = 0.2
    confidence_ceiling: float = 0.95
    max_steps_without_progress: int = 5
    contradiction_window: int = 10
    complexity_budget: int = 50
    auto_intervene: bool = True


class MetacognitionStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_steps: int = 0
    total_signals: int = 0
    total_interventions: int = 0
    interventions_effective: int = 0
    states_detected: dict[str, int] = Field(default_factory=dict)
    avg_confidence: float = 0.0
    loop_count: int = 0
