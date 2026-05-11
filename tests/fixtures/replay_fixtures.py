"""Replay fixture generation and validation for backward compatibility testing."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reins.kernel.event.envelope import EventEnvelope, event_to_dict
from reins.kernel.types import Actor


@dataclass
class FixtureEvent:
    """A single event in a replay fixture with optional expected state."""

    event_type: str
    payload: dict[str, Any]
    schema_version: int = 1
    expected_state_after: dict[str, Any] | None = None


@dataclass
class ReplayFixture:
    """A complete replay fixture representing a run lifecycle."""

    name: str
    version: str
    events: list[FixtureEvent]
    expected_final_state: dict[str, Any]
    description: str


FIXTURE_DIR = Path(__file__).parent / "events"


def generate_v0_1_0_fixture() -> ReplayFixture:
    """Create a fixture representing a complete run lifecycle for v0.1.0."""
    events = [
        FixtureEvent(
            event_type="run.started",
            payload={},
            expected_state_after={"status": "routing"},
        ),
        FixtureEvent(
            event_type="path.routed",
            payload={"path": "fast"},
            expected_state_after={"status": "executing"},
        ),
        FixtureEvent(
            event_type="policy.grant_issued",
            payload={
                "grant_id": "grant-001",
                "capability": "fs.read",
                "scope": "/workspace",
                "issued_to": "agent-1",
                "ttl_seconds": 300,
                "approval_hash": None,
                "issued_at": 1700000000.0,
                "inherited": False,
            },
            expected_state_after={"active_grants_count": 1},
        ),
        FixtureEvent(
            event_type="eval.completed",
            payload={"passed": True},
            expected_state_after={"status": "executing"},
        ),
        FixtureEvent(
            event_type="policy.grant_revoked",
            payload={"grant_id": "grant-001"},
            expected_state_after={"active_grants_count": 0},
        ),
        FixtureEvent(
            event_type="run.completed",
            payload={},
            expected_state_after={"status": "completed"},
        ),
    ]

    return ReplayFixture(
        name="v0_1_0_complete_lifecycle",
        version="0.1.0",
        events=events,
        expected_final_state={
            "status": "completed",
            "active_grants_count": 0,
            "open_handles_count": 0,
            "pending_approvals_count": 0,
        },
        description=(
            "Complete run lifecycle: started -> routed -> grant issued -> "
            "eval passed -> grant revoked -> completed"
        ),
    )


def fixture_event_to_envelope(
    fixture_event: FixtureEvent,
    run_id: str = "fixture-run-001",
    seq: int = 0,
    trace_id: str = "trace-fixture-001",
) -> EventEnvelope:
    """Convert a FixtureEvent to a full EventEnvelope."""
    return EventEnvelope(
        run_id=run_id,
        actor=Actor.runtime,
        type=fixture_event.event_type,
        payload=fixture_event.payload,
        schema_version=fixture_event.schema_version,
        seq=seq,
        trace_id=trace_id,
    )


def write_fixture_jsonl(fixture: ReplayFixture, output_path: Path) -> None:
    """Write fixture events as a JSONL file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for i, fixture_event in enumerate(fixture.events):
            envelope = fixture_event_to_envelope(
                fixture_event,
                run_id="fixture-run-001",
                seq=i + 1,
                trace_id="trace-fixture-001",
            )
            line = json.dumps(event_to_dict(envelope), sort_keys=True)
            f.write(line + "\n")


def load_fixture_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL fixture file and return list of event dicts."""
    events: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def validate_replay(fixture: ReplayFixture, final_state: dict[str, Any]) -> bool:
    """Compare replayed state against expected final state."""
    expected = fixture.expected_final_state
    for key, expected_value in expected.items():
        if key not in final_state:
            return False
        if final_state[key] != expected_value:
            return False
    return True


def get_all_fixtures() -> list[Path]:
    """Return all .jsonl fixture files in the events directory."""
    if not FIXTURE_DIR.exists():
        return []
    return sorted(FIXTURE_DIR.glob("*.jsonl"))
