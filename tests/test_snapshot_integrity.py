from __future__ import annotations

import json
from pathlib import Path

import pytest

from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.event.journal import EventJournal
from reins.kernel.reducer.reducer import REDUCER_VERSION
from reins.kernel.reducer.state import StateSnapshot
from reins.kernel.snapshot.integrity import compute_snapshot_hash, validate_snapshot_integrity
from reins.kernel.snapshot.store import SnapshotCorruptionError, SnapshotStore
from reins.kernel.types import Actor


def make_snapshot(run_id: str = "run-1", seq: int = 5) -> StateSnapshot:
    return StateSnapshot(
        snapshot_id="snap-001",
        run_id=run_id,
        event_seq=seq,
        reducer_version=REDUCER_VERSION,
        run_phase="executing",
    )


def make_event(run_id: str, event_type: str, index: int) -> EventEnvelope:
    return EventEnvelope(
        run_id=run_id,
        actor=Actor.runtime,
        type=event_type,
        payload={"index": index},
    )


class TestComputeSnapshotHash:
    def test_consistent_hash(self) -> None:
        snapshot = make_snapshot()
        hash1 = compute_snapshot_hash(snapshot)
        hash2 = compute_snapshot_hash(snapshot)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex digest

    def test_different_state_different_hash(self) -> None:
        snap1 = make_snapshot(seq=5)
        snap2 = make_snapshot(seq=10)
        assert compute_snapshot_hash(snap1) != compute_snapshot_hash(snap2)

    def test_reins_version_excluded(self) -> None:
        snap1 = StateSnapshot(
            snapshot_id="snap-001",
            run_id="run-1",
            event_seq=5,
            reducer_version=REDUCER_VERSION,
            run_phase="executing",
            reins_version="1.0.0",
        )
        snap2 = StateSnapshot(
            snapshot_id="snap-001",
            run_id="run-1",
            event_seq=5,
            reducer_version=REDUCER_VERSION,
            run_phase="executing",
            reins_version="2.0.0",
        )
        assert compute_snapshot_hash(snap1) == compute_snapshot_hash(snap2)


class TestValidateSnapshotIntegrity:
    def test_valid_hash(self) -> None:
        snapshot = make_snapshot()
        from reins.serde import to_primitive

        data = to_primitive(snapshot)
        expected_hash = compute_snapshot_hash(snapshot)
        assert validate_snapshot_integrity(data, expected_hash) is True

    def test_tampered_data(self) -> None:
        snapshot = make_snapshot()
        from reins.serde import to_primitive

        data = to_primitive(snapshot)
        expected_hash = compute_snapshot_hash(snapshot)
        data["event_seq"] = 999
        assert validate_snapshot_integrity(data, expected_hash) is False

    def test_none_hash(self) -> None:
        snapshot = make_snapshot()
        from reins.serde import to_primitive

        data = to_primitive(snapshot)
        assert validate_snapshot_integrity(data, None) is False


class TestSnapshotStoreIntegrity:
    @pytest.mark.asyncio
    async def test_save_and_load_with_integrity(self, tmp_path: Path) -> None:
        journal = EventJournal(tmp_path / "journal")
        store = SnapshotStore(tmp_path / "snapshots", journal=journal)
        snapshot = make_snapshot()
        await store.save(snapshot)
        loaded = await store.load("run-1", "snap-001")
        assert loaded.run_id == "run-1"
        assert loaded.event_seq == 5

    @pytest.mark.asyncio
    async def test_tampered_file_triggers_rebuild(self, tmp_path: Path) -> None:
        journal = EventJournal(tmp_path / "journal")
        # Append events so rebuild can work (with proper payloads for reducer)
        await journal.append(
            EventEnvelope(
                run_id="run-1",
                actor=Actor.runtime,
                type="run.started",
                payload={},
            )
        )
        await journal.append(
            EventEnvelope(
                run_id="run-1",
                actor=Actor.runtime,
                type="path.routed",
                payload={"path": "fast"},
            )
        )

        store = SnapshotStore(tmp_path / "snapshots", journal=journal)
        snapshot = make_snapshot()
        await store.save(snapshot)

        # Tamper with the file on disk
        snap_path = tmp_path / "snapshots" / "run-1" / "snap-001.json"
        data = json.loads(snap_path.read_text())
        data["event_seq"] = 999
        snap_path.write_text(json.dumps(data))

        # Load should detect corruption and rebuild
        loaded = await store.load("run-1", "snap-001")
        # Rebuilt snapshot should reflect replayed events
        assert loaded.run_phase == "executing"
        assert loaded.event_seq == 2  # Two events replayed

    @pytest.mark.asyncio
    async def test_tampered_file_no_journal_raises(self, tmp_path: Path) -> None:
        store = SnapshotStore(tmp_path / "snapshots", journal=None)
        snapshot = make_snapshot()
        await store.save(snapshot)

        # Tamper with the file on disk
        snap_path = tmp_path / "snapshots" / "run-1" / "snap-001.json"
        data = json.loads(snap_path.read_text())
        data["event_seq"] = 999
        snap_path.write_text(json.dumps(data))

        with pytest.raises(SnapshotCorruptionError) as exc_info:
            await store.load("run-1", "snap-001")
        assert exc_info.value.run_id == "run-1"
        assert exc_info.value.snapshot_id == "snap-001"

    @pytest.mark.asyncio
    async def test_reducer_version_mismatch_triggers_rebuild(self, tmp_path: Path) -> None:
        journal = EventJournal(tmp_path / "journal")
        await journal.append(
            EventEnvelope(
                run_id="run-1",
                actor=Actor.runtime,
                type="run.started",
                payload={},
            )
        )

        store = SnapshotStore(tmp_path / "snapshots", journal=journal)
        snapshot = StateSnapshot(
            snapshot_id="snap-old",
            run_id="run-1",
            event_seq=1,
            reducer_version="0.0.1",  # Old version
            run_phase="routing",
        )
        await store.save(snapshot)

        loaded = await store.load("run-1", "snap-old")
        # Should have rebuilt from journal
        assert loaded.reducer_version == REDUCER_VERSION
        assert loaded.run_phase == "routing"

    @pytest.mark.asyncio
    async def test_latest_with_integrity(self, tmp_path: Path) -> None:
        journal = EventJournal(tmp_path / "journal")
        await journal.append(
            EventEnvelope(
                run_id="run-1",
                actor=Actor.runtime,
                type="run.started",
                payload={},
            )
        )

        store = SnapshotStore(tmp_path / "snapshots", journal=journal)
        snapshot = make_snapshot()
        await store.save(snapshot)

        loaded = await store.latest("run-1")
        assert loaded is not None
        assert loaded.run_id == "run-1"

    @pytest.mark.asyncio
    async def test_latest_tampered_triggers_rebuild(self, tmp_path: Path) -> None:
        journal = EventJournal(tmp_path / "journal")
        await journal.append(
            EventEnvelope(
                run_id="run-1",
                actor=Actor.runtime,
                type="run.started",
                payload={},
            )
        )

        store = SnapshotStore(tmp_path / "snapshots", journal=journal)
        snapshot = make_snapshot()
        await store.save(snapshot)

        # Tamper
        snap_dir = tmp_path / "snapshots" / "run-1"
        files = list(snap_dir.glob("*.json"))
        data = json.loads(files[0].read_text())
        data["event_seq"] = 999
        files[0].write_text(json.dumps(data))

        loaded = await store.latest("run-1")
        assert loaded is not None
        assert loaded.run_phase == "routing"
