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


class TimePoint(str, Enum):
    SEQUENCE = "sequence"
    TIMESTAMP = "timestamp"
    EVENT_TYPE = "event_type"
    CHECKPOINT = "checkpoint"


class DiffKind(str, Enum):
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"


class DiffEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    kind: DiffKind
    old_value: Any = None
    new_value: Any = None


class FieldChange(BaseModel):
    model_config = ConfigDict(frozen=True)

    sequence: int
    event_type: str
    old_value: Any = None
    new_value: Any = None
    timestamp: datetime = Field(default_factory=_utc_now)


class StateFrame(BaseModel):
    model_config = ConfigDict(frozen=True)

    frame_id: str = Field(default_factory=_new_ulid)
    sequence: int
    state: dict[str, Any] = Field(default_factory=dict)
    event_type: str = ""
    timestamp: datetime = Field(default_factory=_utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StateDiff(BaseModel):
    model_config = ConfigDict(frozen=True)

    diff_id: str = Field(default_factory=_new_ulid)
    from_sequence: int
    to_sequence: int
    changes: tuple[DiffEntry, ...] = ()
    summary: str = ""


class Checkpoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    checkpoint_id: str = Field(default_factory=_new_ulid)
    name: str
    sequence: int
    state: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)


class BisectResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    result_id: str = Field(default_factory=_new_ulid)
    found_at_sequence: int
    event_type: str
    total_steps: int
    predicate_description: str = ""
    state_before: dict[str, Any] = Field(default_factory=dict)
    state_after: dict[str, Any] = Field(default_factory=dict)


class TimelineQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    field_path: str
    from_sequence: int = 0
    to_sequence: int | None = None
    include_unchanged: bool = False


class FieldHistory(BaseModel):
    model_config = ConfigDict(frozen=True)

    field_path: str
    changes: tuple[FieldChange, ...] = ()
