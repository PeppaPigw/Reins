from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiofiles

from reins.testing.replay_types import (
    RecordedDecision,
    RecordedEvent,
    RecordedToolCall,
    RecordingMode,
    SessionRecording,
    _utc_now,
)


class SessionRecorder:
    """Records agent sessions for deterministic replay testing.

    Captures events, tool calls, and decisions as they happen during
    a live agent session, producing a SessionRecording that can be
    persisted and replayed later.
    """

    def __init__(
        self,
        session_id: str,
        agent_id: str,
        mode: RecordingMode = RecordingMode.FULL,
        tags: tuple[str, ...] = (),
    ) -> None:
        self._session_id = session_id
        self._agent_id = agent_id
        self._mode = mode
        self._tags = tags
        self._events: list[RecordedEvent] = []
        self._tool_calls: list[RecordedToolCall] = []
        self._decisions: list[RecordedDecision] = []
        self._sequence = 0
        self._started_at = _utc_now()
        self._ended_at = None
        self._metadata: dict[str, Any] = {}

    @property
    def is_recording(self) -> bool:
        return self._ended_at is None

    def _next_seq(self) -> int:
        self._sequence += 1
        return self._sequence

    def record_event(self, event_type: str, payload: dict[str, Any] | None = None, **kwargs) -> RecordedEvent:
        if not self.is_recording:
            raise RuntimeError("Recording has ended")
        if self._mode in (RecordingMode.TOOL_CALLS_ONLY, RecordingMode.DECISIONS_ONLY):
            raise ValueError(f"Cannot record events in {self._mode.value} mode")

        event = RecordedEvent(
            sequence=self._next_seq(),
            event_type=event_type,
            payload=payload or {},
            agent_id=kwargs.get("agent_id", self._agent_id),
            duration_ms=kwargs.get("duration_ms"),
        )
        self._events.append(event)
        return event

    def record_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        result: Any = None,
        error: str | None = None,
        duration_ms: float = 0.0,
    ) -> RecordedToolCall:
        if not self.is_recording:
            raise RuntimeError("Recording has ended")
        if self._mode == RecordingMode.EVENTS_ONLY:
            raise ValueError("Cannot record tool calls in events_only mode")
        if self._mode == RecordingMode.DECISIONS_ONLY:
            raise ValueError("Cannot record tool calls in decisions_only mode")

        call = RecordedToolCall(
            sequence=self._next_seq(),
            tool_name=tool_name,
            arguments=arguments or {},
            result=result,
            error=error,
            duration_ms=duration_ms,
        )
        self._tool_calls.append(call)
        return call

    def record_decision(
        self,
        decision_type: str,
        input_context: dict[str, Any] | None = None,
        output: Any = None,
        rationale: str = "",
    ) -> RecordedDecision:
        if not self.is_recording:
            raise RuntimeError("Recording has ended")
        if self._mode in (RecordingMode.EVENTS_ONLY, RecordingMode.TOOL_CALLS_ONLY):
            raise ValueError(f"Cannot record decisions in {self._mode.value} mode")

        decision = RecordedDecision(
            sequence=self._next_seq(),
            decision_type=decision_type,
            input_context=input_context or {},
            output=output,
            rationale=rationale,
        )
        self._decisions.append(decision)
        return decision

    def set_metadata(self, key: str, value: Any) -> None:
        self._metadata[key] = value

    def finish(self) -> SessionRecording:
        if not self.is_recording:
            raise RuntimeError("Recording already ended")
        self._ended_at = _utc_now()

        return SessionRecording(
            session_id=self._session_id,
            agent_id=self._agent_id,
            mode=self._mode,
            events=tuple(self._events),
            tool_calls=tuple(self._tool_calls),
            decisions=tuple(self._decisions),
            metadata=self._metadata,
            started_at=self._started_at,
            ended_at=self._ended_at,
            tags=self._tags,
        )

    async def save(self, path: Path) -> SessionRecording:
        recording = self.finish()
        data = recording.model_dump(mode="json")
        async with aiofiles.open(path, "w") as f:
            await f.write(json.dumps(data, indent=2, default=str))
        return recording

    @staticmethod
    async def load(path: Path) -> SessionRecording:
        async with aiofiles.open(path, "r") as f:
            data = json.loads(await f.read())
        return SessionRecording.model_validate(data)
