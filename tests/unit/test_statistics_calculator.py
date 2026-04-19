from __future__ import annotations

import asyncio
import subprocess
from datetime import datetime
from pathlib import Path

from reins.kernel.event.journal import EventJournal
from reins.task.manager import TaskManager
from reins.task.projection import TaskContextProjection
from reins.workspace.journal import DeveloperJournal
from reins.workspace.manager import WorkspaceManager
from reins.workspace.stats import StatisticsCalculator
from reins.workspace.types import JournalEntry
from tests.unit.cli_helpers import create_repo


def make_entry(*, timestamp: datetime, commit: str) -> JournalEntry:
    return JournalEntry(
        timestamp=timestamp,
        session_id="session-1",
        title="Implement stats",
        commits=[commit],
        summary="Added workspace statistics support",
        tasks_completed=["Task #1: Build stats"],
        files_changed=["tracked.txt"],
        details="Detailed statistics test entry",
    )


def test_calculate_stats_includes_git_and_task_metrics(tmp_path: Path) -> None:
    repo = create_repo(tmp_path, git=True)
    reins_root = repo / ".reins"
    workspace_dir = WorkspaceManager(reins_root).initialize_workspace("peppa")

    tracked_file = repo / "tracked.txt"
    tracked_file.write_text("one\ntwo\nthree\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "Add tracked file"], cwd=repo, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    timestamp = datetime(2026, 4, 19, 11, 0, 0)
    DeveloperJournal(reins_root / "workspace", "peppa").add_session(
        make_entry(timestamp=timestamp, commit=commit)
    )

    event_journal = EventJournal(reins_root / "journal.jsonl")
    projection = TaskContextProjection()
    task_manager = TaskManager(event_journal, projection, run_id="workspace-stats-test")
    active_task_id = asyncio.run(
        task_manager.create_task(
            title="Active task",
            task_type="backend",
            prd_content="Keep this task pending",
            acceptance_criteria=["Pending task appears in active counts"],
            created_by="peppa",
            assignee="peppa",
        )
    )
    completed_task_id = asyncio.run(
        task_manager.create_task(
            title="Completed task",
            task_type="backend",
            prd_content="Complete this task",
            acceptance_criteria=["Completed task appears in completed counts"],
            created_by="peppa",
            assignee="peppa",
        )
    )
    asyncio.run(task_manager.start_task(completed_task_id, "peppa"))
    asyncio.run(task_manager.complete_task(completed_task_id, {}, completed_by="peppa"))

    stats = StatisticsCalculator().calculate_stats(workspace_dir)

    assert stats.developer == "peppa"
    assert stats.total_sessions == 1
    assert stats.total_commits == 1
    assert stats.first_session == timestamp
    assert stats.last_active == timestamp
    assert stats.journal_files == 1
    assert stats.archived_journal_files == 0
    assert stats.current_session_id == "session-1"
    assert stats.active_task_count == 1
    assert stats.completed_tasks == 1
    assert stats.active_tasks == [f"{active_task_id}: Active task"]
    assert stats.files_changed == 1
    assert stats.lines_added == 3
    assert stats.lines_removed == 0
