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


class ChangeKind(str, Enum):
    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"


class DriftStatus(str, Enum):
    STABLE = "stable"
    DRIFTING = "drifting"
    DIVERGED = "diverged"


class BehaviorSignature(BaseModel):
    model_config = ConfigDict(frozen=True)

    signature_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    version: str = "0.1.0"
    action_profile: dict[str, int] = Field(default_factory=dict)
    success_rate: float = 1.0
    avg_latency_ms: float = 0.0
    resource_profile: dict[str, float] = Field(default_factory=dict)
    captured_at: datetime = Field(default_factory=_utc_now)


class BehaviorDiff(BaseModel):
    model_config = ConfigDict(frozen=True)

    diff_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    from_version: str
    to_version: str
    change_kind: ChangeKind = ChangeKind.PATCH
    added_actions: list[str] = Field(default_factory=list)
    removed_actions: list[str] = Field(default_factory=list)
    success_rate_delta: float = 0.0
    latency_delta_ms: float = 0.0


class BehaviorBaseline(BaseModel):
    model_config = ConfigDict(frozen=True)

    baseline_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    version: str
    signature: BehaviorSignature
    is_golden: bool = False
    created_at: datetime = Field(default_factory=_utc_now)


class BehaviorVersioningStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_agents: int = 0
    total_versions: int = 0
    total_diffs: int = 0
    agents_drifting: int = 0
    by_change_kind: dict[str, int] = Field(default_factory=dict)
    by_drift_status: dict[str, int] = Field(default_factory=dict)
