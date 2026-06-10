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


class BlameLevel(str, Enum):
    ROOT_CAUSE = "root_cause"
    CONTRIBUTING = "contributing"
    PROPAGATING = "propagating"
    BYSTANDER = "bystander"


class FailureKind(str, Enum):
    TIMEOUT = "timeout"
    ERROR = "error"
    POLICY_VIOLATION = "policy_violation"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    CASCADING = "cascading"
    DEADLOCK = "deadlock"


class AgentAction(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    action_type: str
    timestamp: datetime = Field(default_factory=_utc_now)
    caused_by: str = ""
    effects: list[str] = Field(default_factory=list)
    success: bool = True
    error: str = ""


class FailureEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    failure_id: str = Field(default_factory=_new_ulid)
    kind: FailureKind
    agent_id: str
    message: str = ""
    action_id: str = ""
    timestamp: datetime = Field(default_factory=_utc_now)


class BlameAssignment(BaseModel):
    model_config = ConfigDict(frozen=True)

    assignment_id: str = Field(default_factory=_new_ulid)
    failure_id: str
    agent_id: str
    level: BlameLevel
    confidence: float = 0.0
    evidence: list[str] = Field(default_factory=list)
    causal_chain: list[str] = Field(default_factory=list)


class BlameReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    report_id: str = Field(default_factory=_new_ulid)
    failure_id: str
    root_cause_agent: str = ""
    assignments: list[BlameAssignment] = Field(default_factory=list)
    causal_depth: int = 0
    generated_at: datetime = Field(default_factory=_utc_now)


class BlameStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_failures: int = 0
    total_reports: int = 0
    by_failure_kind: dict[str, int] = Field(default_factory=dict)
    by_blame_level: dict[str, int] = Field(default_factory=dict)
    blame_by_agent: dict[str, int] = Field(default_factory=dict)
