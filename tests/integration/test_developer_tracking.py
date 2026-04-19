from __future__ import annotations

import json
from pathlib import Path

from tests.unit.cli_helpers import create_repo, invoke, load_events


def test_workspace_cli_tracks_developer_and_reports_activity(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path, git=True)

    init_workspace = invoke(repo, monkeypatch, ["workspace", "init", "peppa"])
    assert init_workspace.exit_code == 0

    create_task = invoke(
        repo,
        monkeypatch,
        ["task", "create", "Track developer identity", "--type", "backend", "--prd", "Record metadata"],
    )
    assert create_task.exit_code == 0
    task_id = next((repo / ".reins" / "tasks").iterdir()).name

    start_task = invoke(repo, monkeypatch, ["task", "start", task_id])
    assert start_task.exit_code == 0
    finish_task = invoke(repo, monkeypatch, ["task", "finish", task_id, "--note", "Done"])
    assert finish_task.exit_code == 0

    stats_result = invoke(repo, monkeypatch, ["workspace", "stats", "peppa"])
    assert stats_result.exit_code == 0
    assert "My Tasks" in stats_result.output
    assert task_id in stats_result.output

    report_result = invoke(
        repo,
        monkeypatch,
        ["workspace", "report", "peppa", "--start-date", "2026-04-01", "--end-date", "2026-04-30"],
    )
    assert report_result.exit_code == 0
    assert "tasks_completed" in report_result.output

    events = load_events(repo)
    tracked = [event for event in events if event.type in {"task.created", "task.started", "task.completed"}]
    assert tracked
    assert all(event.developer == "peppa" for event in tracked)
    assert all(event.task_id == task_id for event in tracked)

    raw = json.loads((repo / ".reins" / "journal.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert raw["developer"] == "peppa"
