from __future__ import annotations

from pathlib import Path

import pytest

from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.event.journal import EventJournal
from reins.kernel.types import Actor


def make_event(run_id: str, event_type: str, index: int) -> EventEnvelope:
    return EventEnvelope(
        run_id=run_id,
        actor=Actor.runtime,
        type=event_type,
        payload={"index": index},
    )


@pytest.mark.asyncio
async def test_append_and_read(tmp_path: Path) -> None:
    journal = EventJournal(tmp_path / "events.jsonl")
    for index in range(3):
        await journal.append(make_event("run-1", "test.event", index))
    events = [event async for event in journal.read_from("run-1")]
    assert [event.payload["index"] for event in events] == [0, 1, 2]
    assert [event.seq for event in events] == [1, 2, 3]


@pytest.mark.asyncio
async def test_seq_monotonic(tmp_path: Path) -> None:
    journal = EventJournal(tmp_path / "events.jsonl")
    await journal.append(make_event("run-1", "test.event", 1))
    await journal.append(make_event("run-1", "test.event", 2))
    assert await journal.get_seq("run-1") == 2
    events = [event.seq async for event in journal.read_from("run-1")]
    assert events == sorted(events)


@pytest.mark.asyncio
async def test_journal_persistence(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    journal = EventJournal(path)
    await journal.append(make_event("run-1", "test.event", 1))
    reopened = EventJournal(path)
    events = [event async for event in reopened.read_from("run-1")]
    assert len(events) == 1
    assert events[0].payload["index"] == 1
