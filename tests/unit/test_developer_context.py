from __future__ import annotations

import asyncio
import json
from pathlib import Path

from reins.export.task_exporter import TaskExporter
from reins.kernel.event.builder import EventBuilder
from reins.kernel.event.journal import EventJournal
from reins.task.manager import TaskManager
from reins.task.projection import TaskContextProjection
from reins.workspace.context import DeveloperContext

from tests.unit.cli_helpers import create_repo


def test_event_journal_enriches_events_with_developer_context(tmp_path: Path) -> None:
    repo = create_repo(tmp_path)
    reins_root = repo / ".reins"
    context = DeveloperContext(reins_root)
    context.set_current_developer("peppa")

    workspace_dir = reins_root / "workspace" / "peppa"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    (workspace_dir / ".current-session").write_text("session-123\n", encoding="utf-8")

    journal = EventJournal(reins_root / "journal.jsonl")
    builder = EventBuilder(journal)
    event = asyncio.run(
        builder.commit(
            run_id="developer-run",
            event_type="task.started",
            payload={"task_id": "04-19-test-task"},
        )
    )

    assert event.developer == "peppa"
    assert event.session_id == "session-123"
    assert event.task_id == "04-19-test-task"

    raw = json.loads((reins_root / "journal.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert raw["developer"] == "peppa"
    assert raw["session_id"] == "session-123"
    assert raw["task_id"] == "04-19-test-task"


def test_assign_task_updates_export_and_emits_event(tmp_path: Path) -> None:
    repo = create_repo(tmp_path)
    reins_root = repo / ".reins"
    journal = EventJournal(reins_root / "journal.jsonl")
    projection = TaskContextProjection()
    manager = TaskManager(journal, projection, run_id="task-run")
    task_id = asyncio.run(
        manager.create_task(
            title="Demo Task",
            task_type="backend",
            prd_content="Demo",
            acceptance_criteria=[],
            created_by="cli",
            assignee="unassigned",
        )
    )
    TaskExporter(projection, reins_root / "tasks").export_task(task_id)

    context = DeveloperContext(reins_root, journal=journal, run_id="assign-run")
    context.set_current_developer("peppa")
    context.assign_task(task_id, "george")

    task_json = json.loads((reins_root / "tasks" / task_id / "task.json").read_text(encoding="utf-8"))
    assert task_json["assignee"] == "george"
    assert task_json["assigned_to"] == "george"

    lines = (reins_root / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    assert any(json.loads(line)["type"] == "workspace.task.assigned" for line in lines)
