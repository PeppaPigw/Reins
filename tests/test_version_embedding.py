from __future__ import annotations

from reins import __version__
from reins.kernel.event.envelope import EventEnvelope, event_from_dict, event_to_dict
from reins.kernel.reducer.state import StateSnapshot
from reins.kernel.types import Actor


def make_event(event_type: str = "test.event", payload: dict | None = None) -> EventEnvelope:
    return EventEnvelope(
        run_id="run-1", actor=Actor.runtime, type=event_type, payload=payload or {}
    )


def test_event_envelope_has_reins_version():
    event = make_event()
    assert event.reins_version == __version__


def test_event_to_dict_contains_reins_version():
    event = make_event()
    data = event_to_dict(event)
    assert "reins_version" in data
    assert data["reins_version"] == __version__


def test_event_from_dict_missing_reins_version():
    event = make_event()
    data = event_to_dict(event)
    del data["reins_version"]
    restored = event_from_dict(data)
    assert restored.reins_version == "unknown"


def test_event_from_dict_preserves_reins_version():
    event = make_event()
    data = event_to_dict(event)
    data["reins_version"] = "0.0.1"
    restored = event_from_dict(data)
    assert restored.reins_version == "0.0.1"


def test_state_snapshot_has_reins_version():
    snapshot = StateSnapshot(
        snapshot_id="snap-1",
        run_id="run-1",
        event_seq=5,
        reducer_version="1.0",
        run_phase="executing",
    )
    assert snapshot.reins_version == __version__
