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


class AuditAction(str, Enum):
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    TOOL_INVOKED = "tool.invoked"
    POLICY_EVALUATED = "policy.evaluated"
    DATA_ACCESSED = "data.accessed"
    DATA_MODIFIED = "data.modified"
    PERMISSION_GRANTED = "permission.granted"
    PERMISSION_DENIED = "permission.denied"
    ESCALATION_TRIGGERED = "escalation.triggered"
    SAFETY_VIOLATION = "safety.violation"


class AuditSeverity(str, Enum):
    INFO = "info"
    NOTICE = "notice"
    WARNING = "warning"
    ALERT = "alert"
    CRITICAL = "critical"


class IntegrityStatus(str, Enum):
    VALID = "valid"
    TAMPERED = "tampered"
    BROKEN_CHAIN = "broken_chain"
    UNVERIFIED = "unverified"


class AuditEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    entry_id: str = Field(default_factory=_new_ulid)
    sequence: int = 0
    action: AuditAction
    severity: AuditSeverity = AuditSeverity.INFO
    agent_id: str = ""
    subject: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    previous_hash: str = ""
    entry_hash: str = ""
    recorded_at: datetime = Field(default_factory=_utc_now)


class AuditQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str | None = None
    action: AuditAction | None = None
    severity: AuditSeverity | None = None
    from_sequence: int | None = None
    to_sequence: int | None = None
    limit: int = 100


class ChainVerification(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: IntegrityStatus = IntegrityStatus.UNVERIFIED
    entries_checked: int = 0
    first_invalid: int | None = None
    message: str = ""


class AuditChainStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_entries: int = 0
    integrity_status: IntegrityStatus = IntegrityStatus.UNVERIFIED
    by_action: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_agent: dict[str, int] = Field(default_factory=dict)
