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


class ContractKind(str, Enum):
    PRECONDITION = "precondition"
    POSTCONDITION = "postcondition"
    INVARIANT = "invariant"
    TRANSITION = "transition"


class ViolationSeverity(str, Enum):
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class EnforcementMode(str, Enum):
    MONITOR = "monitor"
    WARN = "warn"
    ENFORCE = "enforce"
    ABORT = "abort"


class ContractClause(BaseModel):
    model_config = ConfigDict(frozen=True)

    clause_id: str = Field(default_factory=_new_ulid)
    name: str
    kind: ContractKind
    description: str = ""
    severity: ViolationSeverity = ViolationSeverity.ERROR
    tags: tuple[str, ...] = ()


class ContractViolation(BaseModel):
    model_config = ConfigDict(frozen=True)

    violation_id: str = Field(default_factory=_new_ulid)
    clause_id: str
    clause_name: str
    kind: ContractKind
    severity: ViolationSeverity
    message: str
    context: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utc_now)


class ContractDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    contract_id: str = Field(default_factory=_new_ulid)
    name: str
    description: str = ""
    clauses: tuple[ContractClause, ...] = ()
    enforcement: EnforcementMode = EnforcementMode.ENFORCE
    created_at: datetime = Field(default_factory=_utc_now)


class ContractCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    contract_id: str
    contract_name: str
    passed: bool
    violations: tuple[ContractViolation, ...] = ()
    clauses_checked: int = 0
    clauses_passed: int = 0
    duration_ms: float = 0.0
    checked_at: datetime = Field(default_factory=_utc_now)


class ContractStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_contracts: int = 0
    total_checks: int = 0
    total_violations: int = 0
    pass_rate: float = 0.0
    violations_by_kind: dict[str, int] = Field(default_factory=dict)
    violations_by_severity: dict[str, int] = Field(default_factory=dict)
