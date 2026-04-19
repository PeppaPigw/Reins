from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import ulid

from reins.kernel.types import Actor
from reins.serde import canonical_json, parse_dt, to_primitive


@dataclass(frozen=True)
class EventEnvelope:
    run_id: str
    actor: Actor
    type: str
    payload: dict[str, Any]
    developer: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    seq: int = 0
    command_id: str | None = None
    causation_id: str | None = None
    correlation_id: str | None = None
    trace_id: str = field(default_factory=lambda: str(ulid.new()))
    event_id: str = field(default_factory=lambda: str(ulid.new()))
    schema_version: int = 1
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))
    checksum: str = ""

    def __post_init__(self) -> None:
        if not self.checksum:
            object.__setattr__(self, "checksum", compute_checksum(self))


def compute_checksum(event: EventEnvelope) -> str:
    payload = canonical_json(event.payload).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def event_to_dict(event: EventEnvelope) -> dict[str, Any]:
    return to_primitive(event)


def event_from_dict(data: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope(
        event_id=data["event_id"],
        run_id=data["run_id"],
        seq=data["seq"],
        command_id=data.get("command_id"),
        actor=Actor(data["actor"]),
        type=data["type"],
        schema_version=data["schema_version"],
        payload=data["payload"],
        developer=data.get("developer"),
        session_id=data.get("session_id"),
        task_id=data.get("task_id"),
        causation_id=data.get("causation_id"),
        correlation_id=data.get("correlation_id"),
        trace_id=data["trace_id"],
        ts=parse_dt(data["ts"]),
        checksum=data["checksum"],
    )
