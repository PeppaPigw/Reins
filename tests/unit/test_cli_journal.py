from __future__ import annotations

from pathlib import Path

from tests.unit.cli_helpers import create_repo, invoke


def test_journal_and_status_commands(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path, git=True)

    assert invoke(repo, monkeypatch, ["developer", "init", "peppa"]).exit_code == 0
    create = invoke(
        repo,
        monkeypatch,
        ["task", "create", "Inspect journal", "--type", "backend", "--prd", "Track events"],
    )
    assert create.exit_code == 0
    task_id = next((repo / ".reins" / "tasks").iterdir()).name
    assert invoke(repo, monkeypatch, ["task", "start", task_id]).exit_code == 0

    show = invoke(repo, monkeypatch, ["journal", "show", "--limit", "5"])
    assert show.exit_code == 0
    assert "task.created" in show.output or "task.started" in show.output

    stats = invoke(repo, monkeypatch, ["journal", "stats"])
    assert stats.exit_code == 0
    assert "Total events" in stats.output

    replay = invoke(repo, monkeypatch, ["journal", "replay"])
    assert replay.exit_code == 0
    assert "Events replayed" in replay.output

    export_path = repo / "journal-export.json"
    export = invoke(repo, monkeypatch, ["journal", "export", str(export_path), "--format", "json"])
    assert export.exit_code == 0
    assert export_path.exists()

    status = invoke(repo, monkeypatch, ["status", "--verbose"])
    assert status.exit_code == 0
    assert "current_task" in status.output
