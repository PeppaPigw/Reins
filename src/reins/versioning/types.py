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
    BREAKING = "breaking"
    FEATURE = "feature"
    FIX = "fix"
    DEPRECATION = "deprecation"
    INTERNAL = "internal"


class CompatibilityLevel(str, Enum):
    FULLY_COMPATIBLE = "fully_compatible"
    BACKWARD_COMPATIBLE = "backward_compatible"
    FORWARD_COMPATIBLE = "forward_compatible"
    INCOMPATIBLE = "incompatible"


class MigrationStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class SemanticVersion(BaseModel):
    model_config = ConfigDict(frozen=True)

    major: int = 0
    minor: int = 0
    patch: int = 0

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def bump_major(self) -> SemanticVersion:
        return SemanticVersion(major=self.major + 1, minor=0, patch=0)

    def bump_minor(self) -> SemanticVersion:
        return SemanticVersion(major=self.major, minor=self.minor + 1, patch=0)

    def bump_patch(self) -> SemanticVersion:
        return SemanticVersion(major=self.major, minor=self.minor, patch=self.patch + 1)

    def is_compatible_with(self, other: SemanticVersion) -> bool:
        return self.major == other.major


class BehaviorChange(BaseModel):
    model_config = ConfigDict(frozen=True)

    change_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    kind: ChangeKind
    description: str
    from_version: str = ""
    to_version: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    recorded_at: datetime = Field(default_factory=_utc_now)


class BehaviorVersion(BaseModel):
    model_config = ConfigDict(frozen=True)

    version_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    version: SemanticVersion = Field(default_factory=lambda: SemanticVersion())
    changes: tuple[str, ...] = ()
    released_at: datetime = Field(default_factory=_utc_now)


class Migration(BaseModel):
    model_config = ConfigDict(frozen=True)

    migration_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    from_version: str
    to_version: str
    status: MigrationStatus = MigrationStatus.PENDING
    steps: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=_utc_now)


class VersioningStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_agents: int = 0
    total_versions: int = 0
    total_changes: int = 0
    total_migrations: int = 0
    by_change_kind: dict[str, int] = Field(default_factory=dict)
    by_migration_status: dict[str, int] = Field(default_factory=dict)
