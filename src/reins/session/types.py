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


class SessionStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    MIGRATING = "migrating"
    RESUMED = "resumed"
    TERMINATED = "terminated"


class SuspendReason(str, Enum):
    USER_REQUEST = "user_request"
    IDLE_TIMEOUT = "idle_timeout"
    RESOURCE_PRESSURE = "resource_pressure"
    MIGRATION = "migration"
    CHECKPOINT = "checkpoint"
    ERROR_RECOVERY = "error_recovery"


class MigrationStrategy(str, Enum):
    FULL_TRANSFER = "full_transfer"
    INCREMENTAL = "incremental"
    LAZY_LOAD = "lazy_load"


class SessionContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    working_directory: str = ""
    environment_vars: dict[str, str] = Field(default_factory=dict)
    active_files: tuple[str, ...] = ()
    git_branch: str = ""
    git_commit: str = ""
    tool_states: dict[str, Any] = Field(default_factory=dict)


class ConversationTurn(BaseModel):
    model_config = ConfigDict(frozen=True)

    turn_id: str = Field(default_factory=_new_ulid)
    role: str
    content: str = ""
    tool_calls: tuple[dict[str, Any], ...] = ()
    timestamp: datetime = Field(default_factory=_utc_now)


class SessionState(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    status: SessionStatus = SessionStatus.ACTIVE
    context: SessionContext = Field(default_factory=SessionContext)
    conversation: tuple[ConversationTurn, ...] = ()
    task_stack: tuple[str, ...] = ()
    memory_refs: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    suspended_at: datetime | None = None
    version: int = 1


class SuspendedSession(BaseModel):
    model_config = ConfigDict(frozen=True)

    suspension_id: str = Field(default_factory=_new_ulid)
    session_state: SessionState
    reason: SuspendReason
    resume_hint: str = ""
    ttl_hours: int = 72
    compressed: bool = False
    checksum: str = ""
    suspended_at: datetime = Field(default_factory=_utc_now)


class MigrationManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    manifest_id: str = Field(default_factory=_new_ulid)
    source_host: str
    target_host: str
    session_id: str
    strategy: MigrationStrategy = MigrationStrategy.FULL_TRANSFER
    state_size_bytes: int = 0
    chunks_total: int = 1
    chunks_transferred: int = 0
    started_at: datetime = Field(default_factory=_utc_now)
    completed_at: datetime | None = None


class ResumeResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    result_id: str = Field(default_factory=_new_ulid)
    session_id: str
    success: bool
    restored_turns: int = 0
    restored_context: bool = False
    warnings: tuple[str, ...] = ()
    resumed_at: datetime = Field(default_factory=_utc_now)
