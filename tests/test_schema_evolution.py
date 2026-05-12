from __future__ import annotations

import json

import pytest

from reins.kernel.event.envelope import EventEnvelope, event_to_dict
from reins.kernel.event.journal import EventJournal
from reins.kernel.event.schema.registry import UpcasterRegistry
from reins.kernel.types import Actor


@pytest.fixture
def registry():
    r = UpcasterRegistry()
    r.set_current_version("task.created", 2)
    r.register("task.created", 1, lambda p: {**p, "priority": "medium"})
    return r


@pytest.mark.asyncio
async def test_journal_upcasts_on_read(tmp_path, registry):
    journal = EventJournal(tmp_path / "journal", registry=registry)

    event = EventEnvelope(
        run_id="run-1",
        actor=Actor.runtime,
        type="task.created",
        payload={"title": "test task"},
        schema_version=1,
    )
    await journal.append(event)

    events = []
    async for e in journal.read_from("run-1"):
        events.append(e)

    assert len(events) == 1
    assert events[0].payload == {"title": "test task", "priority": "medium"}
    assert events[0].schema_version == 2


@pytest.mark.asyncio
async def test_events_on_disk_not_mutated(tmp_path, registry):
    journal = EventJournal(tmp_path / "journal", registry=registry)

    event = EventEnvelope(
        run_id="run-1",
        actor=Actor.runtime,
        type="task.created",
        payload={"title": "test task"},
        schema_version=1,
    )
    await journal.append(event)

    run_file = tmp_path / "journal" / "run-1.jsonl"
    raw_line = run_file.read_text().strip()
    raw_data = json.loads(raw_line)

    assert raw_data["schema_version"] == 1
    assert "priority" not in raw_data["payload"]


@pytest.mark.asyncio
async def test_no_upcast_when_current_version(tmp_path):
    registry = UpcasterRegistry()
    registry.set_current_version("task.created", 1)
    journal = EventJournal(tmp_path / "journal", registry=registry)

    event = EventEnvelope(
        run_id="run-1",
        actor=Actor.runtime,
        type="task.created",
        payload={"title": "test task"},
        schema_version=1,
    )
    await journal.append(event)

    events = []
    async for e in journal.read_from("run-1"):
        events.append(e)

    assert events[0].payload == {"title": "test task"}
    assert events[0].schema_version == 1
