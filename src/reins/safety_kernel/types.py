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


class GateVerdict(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ESCALATE = "escalate"


class GateStage(str, Enum):
    IDENTITY = "identity"
    PROTOCOL = "protocol"
    COMPOSABILITY = "composability"
    INVARIANTS = "invariants"
    ENVELOPE = "envelope"


class GateResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    result_id: str = Field(default_factory=_new_ulid)
    stage: GateStage
    verdict: GateVerdict
    message: str = ""
    duration_ms: float = 0.0


class PipelineResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    pipeline_id: str = Field(default_factory=_new_ulid)
    final_verdict: GateVerdict = GateVerdict.DENY
    gates: list[GateResult] = Field(default_factory=list)
    total_duration_ms: float = 0.0
    denied_at: GateStage | None = None
    evaluated_at: datetime = Field(default_factory=_utc_now)


class SafetyKernelStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_evaluations: int = 0
    allowed: int = 0
    denied: int = 0
    escalated: int = 0
    avg_duration_ms: float = 0.0
    denial_by_stage: dict[str, int] = Field(default_factory=dict)
