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


class TemporalOp(str, Enum):
    ALWAYS = "always"
    EVENTUALLY = "eventually"
    NEXT = "next"
    UNTIL = "until"
    NEVER = "never"
    IMPLIES = "implies"


class PropertyStatus(str, Enum):
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    PENDING = "pending"
    UNKNOWN = "unknown"


class TraceEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=_new_ulid)
    step: int = 0
    propositions: set[str] = Field(default_factory=set)
    state: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utc_now)


class TemporalProperty(BaseModel):
    model_config = ConfigDict(frozen=True)

    property_id: str = Field(default_factory=_new_ulid)
    name: str
    operator: TemporalOp
    proposition: str
    secondary: str = ""
    description: str = ""


class PropertyCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    check_id: str = Field(default_factory=_new_ulid)
    property_id: str
    status: PropertyStatus = PropertyStatus.UNKNOWN
    violated_at_step: int | None = None
    witness: str = ""
    steps_checked: int = 0
    checked_at: datetime = Field(default_factory=_utc_now)


class Trace(BaseModel):
    model_config = ConfigDict(frozen=True)

    trace_id: str = Field(default_factory=_new_ulid)
    events: list[TraceEvent] = Field(default_factory=list)
    agent_id: str = ""
    run_id: str = ""


class TemporalLogicStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_properties: int = 0
    total_checks: int = 0
    satisfied: int = 0
    violated: int = 0
    pending: int = 0
    by_operator: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)
