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


class CompositionKind(str, Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    CONDITIONAL = "conditional"
    LOOP = "loop"
    PIPELINE = "pipeline"


class SafetyRelation(str, Enum):
    PRESERVES = "preserves"
    WEAKENS = "weakens"
    VIOLATES = "violates"
    UNKNOWN = "unknown"


class InterferenceKind(str, Enum):
    NONE = "none"
    READ_WRITE = "read_write"
    WRITE_WRITE = "write_write"
    RESOURCE_CONTENTION = "resource_contention"
    DEADLOCK_RISK = "deadlock_risk"


class CompositionStatus(str, Enum):
    SAFE = "safe"
    CONDITIONAL = "conditional"
    UNSAFE = "unsafe"
    UNVERIFIED = "unverified"


class AgentContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    contract_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    requires: set[str] = Field(default_factory=set)
    provides: set[str] = Field(default_factory=set)
    modifies: set[str] = Field(default_factory=set)
    invariants: list[str] = Field(default_factory=list)


class Composition(BaseModel):
    model_config = ConfigDict(frozen=True)

    composition_id: str = Field(default_factory=_new_ulid)
    name: str
    kind: CompositionKind
    agents: list[str] = Field(default_factory=list)
    status: CompositionStatus = CompositionStatus.UNVERIFIED
    created_at: datetime = Field(default_factory=_utc_now)


class InterferenceReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    report_id: str = Field(default_factory=_new_ulid)
    agent_a: str
    agent_b: str
    kind: InterferenceKind = InterferenceKind.NONE
    shared_resources: list[str] = Field(default_factory=list)
    message: str = ""


class SafetyComposition(BaseModel):
    model_config = ConfigDict(frozen=True)

    proof_id: str = Field(default_factory=_new_ulid)
    composition_id: str
    relation: SafetyRelation = SafetyRelation.UNKNOWN
    preserved_invariants: list[str] = Field(default_factory=list)
    weakened_invariants: list[str] = Field(default_factory=list)
    violated_invariants: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    verified_at: datetime = Field(default_factory=_utc_now)


class ComposabilityStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_contracts: int = 0
    total_compositions: int = 0
    safe_compositions: int = 0
    unsafe_compositions: int = 0
    total_interferences: int = 0
    by_kind: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)
