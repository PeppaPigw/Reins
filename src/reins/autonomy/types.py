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


class AutonomyLevel(str, Enum):
    SUPERVISED = "supervised"
    GUIDED = "guided"
    SEMI_AUTONOMOUS = "semi_autonomous"
    AUTONOMOUS = "autonomous"
    FULLY_AUTONOMOUS = "fully_autonomous"


class EscalationReason(str, Enum):
    UNCERTAINTY = "uncertainty"
    RISK_THRESHOLD = "risk_threshold"
    POLICY_VIOLATION = "policy_violation"
    RESOURCE_LIMIT = "resource_limit"
    NOVEL_SITUATION = "novel_situation"
    EXPLICIT_REQUEST = "explicit_request"


class DecisionOutcome(str, Enum):
    APPROVED = "approved"
    DENIED = "denied"
    DEFERRED = "deferred"
    ESCALATED = "escalated"


class AutonomyBoundary(BaseModel):
    model_config = ConfigDict(frozen=True)

    boundary_id: str = Field(default_factory=_new_ulid)
    name: str
    max_level: AutonomyLevel = AutonomyLevel.GUIDED
    allowed_actions: tuple[str, ...] = ()
    forbidden_actions: tuple[str, ...] = ()
    risk_tolerance: float = 0.5
    requires_confirmation: bool = False


class AutonomyDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    action: str
    outcome: DecisionOutcome = DecisionOutcome.DEFERRED
    autonomy_level: AutonomyLevel = AutonomyLevel.SUPERVISED
    confidence: float = 0.0
    risk_score: float = 0.0
    reasoning: str = ""
    timestamp: datetime = Field(default_factory=_utc_now)


class EscalationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    action: str
    reason: EscalationReason
    context: dict[str, Any] = Field(default_factory=dict)
    resolved: bool = False
    resolution: DecisionOutcome | None = None
    created_at: datetime = Field(default_factory=_utc_now)


class AutonomyProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str
    current_level: AutonomyLevel = AutonomyLevel.SUPERVISED
    decisions_made: int = 0
    escalations: int = 0
    success_rate: float = 0.0
    trust_score: float = 0.5


class AutonomyStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_agents: int = 0
    total_decisions: int = 0
    total_escalations: int = 0
    auto_approved: int = 0
    avg_confidence: float = 0.0
    by_level: dict[str, int] = Field(default_factory=dict)
    by_outcome: dict[str, int] = Field(default_factory=dict)
