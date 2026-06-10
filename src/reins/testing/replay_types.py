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


class RecordingMode(str, Enum):
    FULL = "full"
    EVENTS_ONLY = "events_only"
    TOOL_CALLS_ONLY = "tool_calls_only"
    DECISIONS_ONLY = "decisions_only"


class ReplayMode(str, Enum):
    STRICT = "strict"
    RELAXED = "relaxed"
    MUTATION = "mutation"


class AssertionKind(str, Enum):
    OUTPUT_EXACT = "output_exact"
    OUTPUT_CONTAINS = "output_contains"
    OUTPUT_SCHEMA = "output_schema"
    EVENT_SEQUENCE = "event_sequence"
    TOOL_CALL_MATCH = "tool_call_match"
    STATE_SNAPSHOT = "state_snapshot"
    TIMING_BOUND = "timing_bound"
    NO_REGRESSION = "no_regression"


class MutationKind(str, Enum):
    INJECT_FAILURE = "inject_failure"
    DELAY_RESPONSE = "delay_response"
    CORRUPT_OUTPUT = "corrupt_output"
    DROP_EVENT = "drop_event"
    REORDER_EVENTS = "reorder_events"
    TIMEOUT = "timeout"


class RecordedEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=_new_ulid)
    sequence: int
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utc_now)
    agent_id: str | None = None
    duration_ms: float | None = None


class RecordedToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    call_id: str = Field(default_factory=_new_ulid)
    sequence: int
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    timestamp: datetime = Field(default_factory=_utc_now)


class RecordedDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_id: str = Field(default_factory=_new_ulid)
    sequence: int
    decision_type: str
    input_context: dict[str, Any] = Field(default_factory=dict)
    output: Any = None
    rationale: str = ""
    timestamp: datetime = Field(default_factory=_utc_now)


class SessionRecording(BaseModel):
    model_config = ConfigDict(frozen=True)

    recording_id: str = Field(default_factory=_new_ulid)
    session_id: str
    agent_id: str
    mode: RecordingMode = RecordingMode.FULL
    events: tuple[RecordedEvent, ...] = ()
    tool_calls: tuple[RecordedToolCall, ...] = ()
    decisions: tuple[RecordedDecision, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=_utc_now)
    ended_at: datetime | None = None
    tags: tuple[str, ...] = ()


class ReplayAssertion(BaseModel):
    model_config = ConfigDict(frozen=True)

    assertion_id: str = Field(default_factory=_new_ulid)
    kind: AssertionKind
    target: str = ""
    expected: Any = None
    tolerance: float = 0.0
    description: str = ""


class Mutation(BaseModel):
    model_config = ConfigDict(frozen=True)

    mutation_id: str = Field(default_factory=_new_ulid)
    kind: MutationKind
    target_sequence: int | None = None
    target_tool: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class ReplayConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: ReplayMode = ReplayMode.STRICT
    assertions: tuple[ReplayAssertion, ...] = ()
    mutations: tuple[Mutation, ...] = ()
    speed_multiplier: float = 1.0
    stop_on_first_failure: bool = True
    capture_diffs: bool = True


class ReplayResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    result_id: str = Field(default_factory=_new_ulid)
    recording_id: str
    passed: bool
    total_assertions: int = 0
    passed_assertions: int = 0
    failed_assertions: tuple[str, ...] = ()
    diffs: tuple[dict[str, Any], ...] = ()
    duration_ms: float = 0.0
    replayed_at: datetime = Field(default_factory=_utc_now)


class GoldenSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: str = Field(default_factory=_new_ulid)
    recording_id: str
    name: str
    content: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)
    version: int = 1
