"""Tests for EventJournal file and directory modes."""

import pytest
from pathlib import Path

from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.event.journal import EventJournal
from reins.kernel.types import Actor


@pytest.mark.asyncio
async def test_journal_file_mode(tmp_path):
    """Journal in file mode writes all runs to single file."""
    journal_file = tmp_path / "events.jsonl"
    journal = EventJournal(journal_file)

    # Write events for multiple runs
    event1 = EventEnvelope(
        run_id="run-1", actor=Actor.runtime, type="test", payload={"data": "a"}
    )
    event2 = EventEnvelope(
        run_id="run-2", actor=Actor.runtime, type="test", payload={"data": "b"}
    )

    await journal.append(event1)
    await journal.append(event2)

    # Both should be in the same file
    assert journal_file.exists()
    lines = journal_file.read_text().strip().split("\n")
    assert len(lines) == 2


@pytest.mark.asyncio
async def test_journal_directory_mode(tmp_path):
    """Journal in directory mode creates separate file per run."""
    journal_dir = tmp_path / "events"
    journal = EventJournal(journal_dir)

    # Write events for multiple runs
    event1 = EventEnvelope(
        run_id="run-1", actor=Actor.runtime, type="test", payload={"data": "a"}
    )
    event2 = EventEnvelope(
        run_id="run-2", actor=Actor.runtime, type="test", payload={"data": "b"}
    )
    event3 = EventEnvelope(
        run_id="run-1", actor=Actor.runtime, type="test", payload={"data": "c"}
    )

    await journal.append(event1)
    await journal.append(event2)
    await journal.append(event3)

    # Should create separate files
    assert (journal_dir / "run-1.jsonl").exists()
    assert (journal_dir / "run-2.jsonl").exists()

    # run-1 should have 2 events
    run1_lines = (journal_dir / "run-1.jsonl").read_text().strip().split("\n")
    assert len(run1_lines) == 2

    # run-2 should have 1 event
    run2_lines = (journal_dir / "run-2.jsonl").read_text().strip().split("\n")
    assert len(run2_lines) == 1


@pytest.mark.asyncio
async def test_journal_read_from_directory_mode(tmp_path):
    """Reading from directory mode journal works correctly."""
    journal_dir = tmp_path / "events"
    journal = EventJournal(journal_dir)

    # Write events
    event1 = EventEnvelope(
        run_id="run-1", actor=Actor.runtime, type="test.1", payload={"seq": 1}
    )
    event2 = EventEnvelope(
        run_id="run-1", actor=Actor.runtime, type="test.2", payload={"seq": 2}
    )
    event3 = EventEnvelope(
        run_id="run-2", actor=Actor.runtime, type="test.3", payload={"seq": 3}
    )

    await journal.append(event1)
    await journal.append(event2)
    await journal.append(event3)

    # Read run-1 events
    events = [e async for e in journal.read_from("run-1")]
    assert len(events) == 2
    assert events[0].type == "test.1"
    assert events[1].type == "test.2"

    # Read run-2 events
    events = [e async for e in journal.read_from("run-2")]
    assert len(events) == 1
    assert events[0].type == "test.3"


@pytest.mark.asyncio
async def test_journal_get_seq_directory_mode(tmp_path):
    """get_seq works correctly in directory mode."""
    journal_dir = tmp_path / "events"
    journal = EventJournal(journal_dir)

    # Initial seq should be 0
    seq = await journal.get_seq("run-1")
    assert seq == 0

    # Append events
    event1 = EventEnvelope(run_id="run-1", actor=Actor.runtime, type="test", payload={})
    event2 = EventEnvelope(run_id="run-1", actor=Actor.runtime, type="test", payload={})

    await journal.append(event1)
    await journal.append(event2)

    # Seq should be 2
    seq = await journal.get_seq("run-1")
    assert seq == 2


@pytest.mark.asyncio
async def test_journal_read_nonexistent_run(tmp_path):
    """Reading from nonexistent run returns empty."""
    journal_dir = tmp_path / "events"
    journal = EventJournal(journal_dir)

    # Read from nonexistent run
    events = [e async for e in journal.read_from("nonexistent")]
    assert len(events) == 0
