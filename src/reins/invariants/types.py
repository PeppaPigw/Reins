from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Callable

import ulid
from pydantic import BaseModel, ConfigDict, Field


def _new_ulid() -> str:
    return str(ulid.new())


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InvariantKind(str, Enum):
    SAFETY = "safety"
    LIVENESS = "liveness"
    FAIRNESS = "fairness"
    BOUNDEDNESS = "boundedness"
    MONOTONICITY = "monotonicity"
    IDEMPOTENCY = "idempotency"


class CheckResult(str, Enum):
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    UNKNOWN = "unknown"
    SKIPPED = "skipped"


class ViolationSeverity(str, Enum):
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
    FATAL = "fatal"


class InvariantSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    spec_id: str = Field(default_factory=_new_ulid)
    name: str
    kind: InvariantKind
    description: str = ""
    expression: str = ""
    severity: ViolationSeverity = ViolationSeverity.ERROR
    enabled: bool = True


class InvariantCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    check_id: str = Field(default_factory=_new_ulid)
    spec_id: str
    result: CheckResult = CheckResult.UNKNOWN
    context: dict[str, Any] = Field(default_factory=dict)
    message: str = ""
    checked_at: datetime = Field(default_factory=_utc_now)


class Violation(BaseModel):
    model_config = ConfigDict(frozen=True)

    violation_id: str = Field(default_factory=_new_ulid)
    spec_id: str
    severity: ViolationSeverity = ViolationSeverity.ERROR
    state_before: dict[str, Any] = Field(default_factory=dict)
    state_after: dict[str, Any] = Field(default_factory=dict)
    message: str = ""
    remediation: str = ""
    detected_at: datetime = Field(default_factory=_utc_now)


class SafetyProof(BaseModel):
    model_config = ConfigDict(frozen=True)

    proof_id: str = Field(default_factory=_new_ulid)
    spec_id: str
    holds: bool = False
    witness: str = ""
    steps_verified: int = 0
    verified_at: datetime = Field(default_factory=_utc_now)


class InvariantStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_specs: int = 0
    total_checks: int = 0
    total_violations: int = 0
    total_proofs: int = 0
    satisfaction_rate: float = 0.0
    by_kind: dict[str, int] = Field(default_factory=dict)
    by_result: dict[str, int] = Field(default_factory=dict)
