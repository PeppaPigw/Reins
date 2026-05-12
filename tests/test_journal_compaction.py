from __future__ import annotations

from pathlib import Path

import pytest

from reins.kernel.event.compaction import RetentionPolicy, compact_journal, should_compact
from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.event.journal import EventJournal
from reins.kernel.reducer.reducer import REDUCER_VERSION
from reins.kernel.reducer.state import StateSnapshot
from reins.kernel.snapshot.store import SnapshotStore
from reins.kernel.types import Actor


def make_event(
    run_id: str, event_type: str, index: int, causation_id: str | None = None
) -> EventEnvelope:
    return EventEnvelope(
        run_id=run_id,
        actor=Actor.runtime,
        type=event_type,
        payload={"index": index},
        causation_id=causation_id,
    )


class TestShouldCompact:
    @pytest.mark.asyncio
    async def test_below_threshold(self, tmp_path: Path) -> None:
        journal = EventJournal(tmp_path / "journal")
        for i in range(5):
            await journal.append(make_event("run-1", "test.event", i))
        policy = RetentionPolicy(max_events=10)
        assert await should_compact(journal, "run-1", policy) is False

    @pytest.mark.asyncio
    async def test_above_threshold(self, tmp_path: Path) -> None:
        journal = EventJournal(tmp_path / "journal")
        for i in range(15):
            await journal.append(make_event("run-1", "test.event", i))
        policy = RetentionPolicy(max_events=10)
        assert await should_compact(journal, "run-1", policy) is True


class TestCompactJournal:
    @pytest.mark.asyncio
    async def test_compact_keep_last_n(self, tmp_path: Path) -> None:
        journal = EventJournal(tmp_path / "journal")
        for i in range(20):
            await journal.append(make_event("run-1", "test.event", i))

        policy = RetentionPolicy(
            max_events=10,
            keep_last_n=5,
            keep_after_snapshot=False,
            preserve_causation=False,
        )
        removed = await compact_journal(journal, "run-1", policy)
        assert removed == 15

        # Verify only last 5 events remain
        events = [e async for e in journal.read_from("run-1")]
        assert len(events) == 5
        assert [e.payload["index"] for e in events] == [15, 16, 17, 18, 19]

    @pytest.mark.asyncio
    async def test_compact_with_snapshot_boundary(self, tmp_path: Path) -> None:
        journal = EventJournal(tmp_path / "journal")
        for i in range(20):
            await journal.append(make_event("run-1", "test.event", i))

        # Create a snapshot at seq 10
        snap_store = SnapshotStore(tmp_path / "snapshots")
        snapshot = StateSnapshot(
            snapshot_id="snap-1",
            run_id="run-1",
            event_seq=10,
            reducer_version=REDUCER_VERSION,
            run_phase="executing",
        )
        await snap_store.save(snapshot)

        policy = RetentionPolicy(
            max_events=10,
            keep_last_n=3,
            keep_after_snapshot=True,
            preserve_causation=False,
        )
        removed = await compact_journal(journal, "run-1", policy, snapshot_store=snap_store)

        # Events at seq >= 10 should be kept (seq 10-20 = 11 events)
        # Plus last 3 are already in that set
        events = [e async for e in journal.read_from("run-1")]
        assert all(e.seq >= 10 for e in events)
        assert removed > 0

    @pytest.mark.asyncio
    async def test_causation_chain_preservation(self, tmp_path: Path) -> None:
        journal = EventJournal(tmp_path / "journal")

        # Create a chain: event 0 causes event 15
        first = await journal.append(make_event("run-1", "test.event", 0))
        for i in range(1, 15):
            await journal.append(make_event("run-1", "test.event", i))
        # Event 15 references event 0 via causation_id
        await journal.append(
            make_event("run-1", "test.event", 15, causation_id=first.event_id)
        )
        for i in range(16, 20):
            await journal.append(make_event("run-1", "test.event", i))

        policy = RetentionPolicy(
            max_events=10,
            keep_last_n=6,  # keeps events 14-19 (indices 14-19)
            keep_after_snapshot=False,
            preserve_causation=True,
        )
        removed = await compact_journal(journal, "run-1", policy)

        events = [e async for e in journal.read_from("run-1")]
        event_ids = {e.event_id for e in events}
        # The first event should be preserved because event 15 references it
        assert first.event_id in event_ids

    @pytest.mark.asyncio
    async def test_no_op_below_keep_last_n(self, tmp_path: Path) -> None:
        journal = EventJournal(tmp_path / "journal")
        for i in range(5):
            await journal.append(make_event("run-1", "test.event", i))

        policy = RetentionPolicy(keep_last_n=10)
        removed = await compact_journal(journal, "run-1", policy)
        assert removed == 0

        events = [e async for e in journal.read_from("run-1")]
        assert len(events) == 5

    @pytest.mark.asyncio
    async def test_read_from_after_compaction(self, tmp_path: Path) -> None:
        journal = EventJournal(tmp_path / "journal")
        for i in range(20):
            await journal.append(make_event("run-1", "test.event", i))

        policy = RetentionPolicy(
            max_events=10,
            keep_last_n=5,
            keep_after_snapshot=False,
            preserve_causation=False,
        )
        await compact_journal(journal, "run-1", policy)

        # read_from should only return retained events
        events = [e async for e in journal.read_from("run-1")]
        assert len(events) == 5
        # Seq numbers should still be valid (original seq preserved)
        for event in events:
            assert event.seq > 0
