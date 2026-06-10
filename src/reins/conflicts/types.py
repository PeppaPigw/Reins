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
    FUNCTION_MODIFIED = "function_modified"
    FUNCTION_ADDED = "function_added"
    FUNCTION_REMOVED = "function_removed"
    IMPORT_ADDED = "import_added"
    IMPORT_REMOVED = "import_removed"
    CLASS_MODIFIED = "class_modified"
    API_SIGNATURE_CHANGED = "api_signature_changed"
    DEPENDENCY_ADDED = "dependency_added"
    DEPENDENCY_REMOVED = "dependency_removed"
    DEPENDENCY_VERSION_CHANGED = "dependency_version_changed"
    CONFIG_MODIFIED = "config_modified"
    FILE_CREATED = "file_created"
    FILE_DELETED = "file_deleted"


class ConflictType(str, Enum):
    OVERLAPPING_MODIFICATION = "overlapping_modification"
    CONTRADICTORY_API_CHANGE = "contradictory_api_change"
    INCOMPATIBLE_DEPENDENCY = "incompatible_dependency"
    SHARED_STATE_RACE = "shared_state_race"
    SEMANTIC_DIVERGENCE = "semantic_divergence"
    DELETED_DEPENDENCY = "deleted_dependency"


class ConflictSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ResolutionStrategy(str, Enum):
    MERGE = "merge"
    PREFER_FIRST = "prefer_first"
    PREFER_SECOND = "prefer_second"
    MANUAL = "manual"
    REBASE = "rebase"


class Change(BaseModel):
    model_config = ConfigDict(frozen=True)

    change_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    file_path: str
    kind: ChangeKind
    symbol: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    line_range: tuple[int, int] | None = None
    timestamp: datetime = Field(default_factory=_utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Conflict(BaseModel):
    model_config = ConfigDict(frozen=True)

    conflict_id: str = Field(default_factory=_new_ulid)
    conflict_type: ConflictType
    severity: ConflictSeverity
    change_a: Change
    change_b: Change
    description: str
    affected_symbols: tuple[str, ...] = ()
    suggested_resolution: ResolutionStrategy = ResolutionStrategy.MANUAL


class Resolution(BaseModel):
    model_config = ConfigDict(frozen=True)

    resolution_id: str = Field(default_factory=_new_ulid)
    conflict_id: str
    strategy: ResolutionStrategy
    resolved_by: str
    resolved_at: datetime = Field(default_factory=_utc_now)
    notes: str = ""


class ConflictReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    report_id: str = Field(default_factory=_new_ulid)
    conflicts: tuple[Conflict, ...] = ()
    total_changes_analyzed: int = 0
    agents_involved: tuple[str, ...] = ()
    has_critical: bool = False
    generated_at: datetime = Field(default_factory=_utc_now)
