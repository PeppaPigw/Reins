"""Historical replay tests proving backward compatibility.

These tests verify that events from v0.1.0 replay correctly through the
current reducer, ensuring backward compatibility as the schema evolves.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reins.kernel.event.envelope import EventEnvelope, event_from_dict
from reins.kernel.reducer.reducer import reduce
from reins.kernel.reducer.state import RunState
from reins.kernel.types import RunStatus
from tests.fixtures.replay_fixtures import (
    FIXTURE_DIR,
    ReplayFixture,
    fixture_event_to_envelope,
    generate_v0_1_0_fixture,
    get_all_fixtures,
    load_fixture_jsonl,
    validate_replay,
    write_fixture_jsonl,
)


def _replay_fixture(fixture: ReplayFixture) -> RunState:
    """Replay all events in a fixture through the reducer."""
    state = RunState(run_id="fixture-run-001")
    for i, fixture_event in enumerate(fixture.events):
        envelope = fixture_event_to_envelope(
            fixture_event, run_id="fixture-run-001", seq=i + 1
        )
        state = reduce(state, envelope)
    return state


def _state_to_validation_dict(state: RunState) -> dict:
    """Convert RunState to a dict suitable for validation."""
    return {
        "status": state.status.value,
        "active_grants_count": len(state.active_grants),
        "open_handles_count": len(state.open_handles),
        "pending_approvals_count": len(state.pending_approvals),
    }


class TestV010FixtureReplay:
    """Tests for v0.1.0 historical event replay."""

    def test_v0_1_0_fixture_replays_successfully(self):
        """Events from v0.1.0 replay without errors through current reducer."""
        fixture = generate_v0_1_0_fixture()
        state = _replay_fixture(fixture)
        assert state is not None
        assert state.run_id == "fixture-run-001"

    def test_fixture_events_are_valid_envelopes(self):
        """Each fixture event converts to a valid EventEnvelope."""
        fixture = generate_v0_1_0_fixture()
        for i, fixture_event in enumerate(fixture.events):
            envelope = fixture_event_to_envelope(fixture_event, seq=i + 1)
            assert isinstance(envelope, EventEnvelope)
            assert envelope.type == fixture_event.event_type
            assert envelope.payload == fixture_event.payload
            assert envelope.schema_version == fixture_event.schema_version
            assert envelope.checksum  # checksum is computed

    def test_replay_produces_expected_final_state(self):
        """Replaying v0.1.0 events produces the expected final state."""
        fixture = generate_v0_1_0_fixture()
        state = _replay_fixture(fixture)
        validation_dict = _state_to_validation_dict(state)
        assert validation_dict["status"] == "completed"
        assert validation_dict["active_grants_count"] == 0
        assert validation_dict["open_handles_count"] == 0
        assert validation_dict["pending_approvals_count"] == 0

    def test_replay_handles_all_event_types(self):
        """The fixture covers multiple event types that all replay correctly."""
        fixture = generate_v0_1_0_fixture()
        event_types = [e.event_type for e in fixture.events]
        assert "run.started" in event_types
        assert "path.routed" in event_types
        assert "policy.grant_issued" in event_types
        assert "eval.completed" in event_types
        assert "run.completed" in event_types
        # All replay without error
        state = _replay_fixture(fixture)
        assert state.status == RunStatus.completed

    def test_fixture_schema_version_is_correct(self):
        """All fixture events have schema_version=1 for v0.1.0."""
        fixture = generate_v0_1_0_fixture()
        for fixture_event in fixture.events:
            assert fixture_event.schema_version == 1

    def test_generate_fixture_creates_valid_events(self):
        """generate_v0_1_0_fixture produces a well-formed ReplayFixture."""
        fixture = generate_v0_1_0_fixture()
        assert isinstance(fixture, ReplayFixture)
        assert fixture.name == "v0_1_0_complete_lifecycle"
        assert fixture.version == "0.1.0"
        assert len(fixture.events) == 6
        assert fixture.description
        assert fixture.expected_final_state


class TestFixtureIO:
    """Tests for fixture file I/O operations."""

    def test_write_and_load_fixture_roundtrip(self, tmp_path: Path):
        """Writing and loading a fixture produces the same events."""
        fixture = generate_v0_1_0_fixture()
        output_path = tmp_path / "test_fixture.jsonl"
        write_fixture_jsonl(fixture, output_path)

        loaded = load_fixture_jsonl(output_path)
        assert len(loaded) == len(fixture.events)
        for i, event_dict in enumerate(loaded):
            assert event_dict["type"] == fixture.events[i].event_type
            assert event_dict["payload"] == fixture.events[i].payload
            assert event_dict["schema_version"] == fixture.events[i].schema_version

    def test_validate_replay_passes_for_correct_state(self):
        """validate_replay returns True when state matches expected."""
        fixture = generate_v0_1_0_fixture()
        state = _replay_fixture(fixture)
        validation_dict = _state_to_validation_dict(state)
        assert validate_replay(fixture, validation_dict) is True

    def test_validate_replay_fails_for_wrong_state(self):
        """validate_replay returns False when state does not match."""
        fixture = generate_v0_1_0_fixture()
        wrong_state = {
            "status": "executing",
            "active_grants_count": 5,
            "open_handles_count": 0,
            "pending_approvals_count": 0,
        }
        assert validate_replay(fixture, wrong_state) is False

    def test_get_all_fixtures_finds_files(self):
        """get_all_fixtures returns the pre-generated fixture files."""
        fixtures = get_all_fixtures()
        assert len(fixtures) >= 1
        assert any("v0_1_0" in f.name for f in fixtures)


class TestFixtureFromDisk:
    """Tests that load and replay the on-disk JSONL fixture."""

    def test_on_disk_fixture_loads(self):
        """The on-disk v0_1_0.jsonl file loads correctly."""
        fixture_path = FIXTURE_DIR / "v0_1_0.jsonl"
        assert fixture_path.exists(), f"Fixture not found at {fixture_path}"
        events = load_fixture_jsonl(fixture_path)
        assert len(events) == 6

    def test_on_disk_fixture_replays_through_reducer(self):
        """Events from the on-disk fixture replay through the reducer."""
        fixture_path = FIXTURE_DIR / "v0_1_0.jsonl"
        events = load_fixture_jsonl(fixture_path)
        state = RunState(run_id="fixture-run-001")
        for event_dict in events:
            envelope = event_from_dict(event_dict)
            state = reduce(state, envelope)
        assert state.status == RunStatus.completed
