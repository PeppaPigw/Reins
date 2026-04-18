from __future__ import annotations

import json
from pathlib import Path

from tests.unit.cli_helpers import create_repo, invoke, load_events


def test_cli_workflow_end_to_end(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path, git=True)

    assert invoke(repo, monkeypatch, ["developer", "init", "peppa"]).exit_code == 0
    assert invoke(repo, monkeypatch, ["spec", "init", "--package", "cli", "--layers", "commands"]).exit_code == 0

    backend_dir = repo / ".reins" / "spec" / "backend"
    guides_dir = repo / ".reins" / "spec" / "guides"
    backend_dir.mkdir(parents=True)
    guides_dir.mkdir(parents=True)
    (backend_dir / "index.md").write_text("# Backend Rules\n", encoding="utf-8")
    (guides_dir / "index.md").write_text("# General Rules\n", encoding="utf-8")

    create = invoke(
        repo,
        monkeypatch,
        [
            "task",
            "create",
            "Build CLI workflow",
            "--type",
            "backend",
            "--priority",
            "P1",
            "--prd",
            "Implement end-to-end CLI workflow",
            "--acceptance",
            "Commands emit journal events",
            "--package",
            "cli",
        ],
    )
    assert create.exit_code == 0

    task_id = next((repo / ".reins" / "tasks").iterdir()).name
    assert invoke(repo, monkeypatch, ["task", "start", task_id, "--assignee", "peppa"]).exit_code == 0
    assert invoke(repo, monkeypatch, ["task", "init-context", task_id, "backend"]).exit_code == 0

    extra = repo / "extra.md"
    extra.write_text("# Extra Context\nRemember the pointer format.\n", encoding="utf-8")
    assert invoke(
        repo,
        monkeypatch,
        ["task", "add-context", task_id, "check", str(extra), "--reason", "Review reminder"],
    ).exit_code == 0

    journal_stats = invoke(repo, monkeypatch, ["journal", "stats"])
    assert journal_stats.exit_code == 0
    assert "task.context_initialized" in journal_stats.output

    status = invoke(repo, monkeypatch, ["status", "--verbose"])
    assert status.exit_code == 0
    assert task_id in status.output

    assert invoke(repo, monkeypatch, ["task", "finish", task_id, "--note", "Workflow complete"]).exit_code == 0
    assert invoke(repo, monkeypatch, ["task", "archive", task_id, "--reason", "Completed"]).exit_code == 0

    event_types = [event.type for event in load_events(repo)]
    assert "developer.initialized" in event_types
    assert "spec.initialized" in event_types
    assert "task.created" in event_types
    assert "task.started" in event_types
    assert "task.context_initialized" in event_types
    assert "task.context_added" in event_types
    assert "task.completed" in event_types
    assert "task.archived" in event_types

    check_context = (repo / ".reins" / "tasks" / task_id / "check.jsonl").read_text(encoding="utf-8").splitlines()
    assert any(json.loads(line)["metadata"].get("reason") == "Review reminder" for line in check_context if line.strip())
