"""Tests for the event builder — CQRS enforcement gate."""

import pytest

from reins.kernel.event.builder import EventBuilder
from reins.kernel.event.journal import EventJournal
from reins.kernel.types import Actor


@pytest.mark.asyncio
async def test_commit_creates_event(tmp_path):
    journal = EventJournal(tmp_path / "journal.jsonl")
    builder = EventBuilder(journal)

    event = await builder.commit(
        run_id="run-1",
        event_type="run.started",
        payload={"objective": "test"},
        actor=Actor.runtime,
    )
    assert event.run_id == "run-1"
    assert event.type == "run.started"
    assert event.actor == Actor.runtime
    assert event.checksum  # non-empty


@pytest.mark.asyncio
async def test_events_persisted_to_journal(tmp_path):
    journal = EventJournal(tmp_path / "journal.jsonl")
    builder = EventBuilder(journal)

    await builder.emit_run_started("run-2", "fix bug")
    await builder.emit_path_routed("run-2", "fast")

    events = []
    async for e in journal.read_from("run-2"):
        events.append(e)
    assert len(events) == 2
    assert events[0].type == "run.started"
    assert events[1].type == "path.routed"


@pytest.mark.asyncio
async def test_grant_lifecycle(tmp_path):
    journal = EventJournal(tmp_path / "journal.jsonl")
    builder = EventBuilder(journal)

    await builder.emit_grant_issued(
        "run-3", "g1", "fs.read", "workspace", "model", 600,
    )
    await builder.emit_grant_revoked("run-3", "g1")

    events = []
    async for e in journal.read_from("run-3"):
        events.append(e)
    assert events[0].type == "policy.grant_issued"
    assert events[1].type == "policy.grant_revoked"
    assert events[1].payload["grant_id"] == "g1"


@pytest.mark.asyncio
async def test_causation_and_trace_ids(tmp_path):
    journal = EventJournal(tmp_path / "journal.jsonl")
    builder = EventBuilder(journal)

    event = await builder.commit(
        run_id="run-4", event_type="test.event",
        payload={"x": 1},
        causation_id="cause-1",
        correlation_id="corr-1",
        trace_id="trace-1",
    )
    assert event.causation_id == "cause-1"
    assert event.correlation_id == "corr-1"
    assert event.trace_id == "trace-1"
