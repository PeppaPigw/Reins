from __future__ import annotations

import json
from pathlib import Path

from tests.unit.cli_helpers import create_repo, invoke, load_events


def test_task_help(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path)
    result = invoke(repo, monkeypatch, ["task", "--help"])
    assert result.exit_code == 0
    assert "Task lifecycle and context commands" in result.output


def test_task_lifecycle_and_context_commands(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path)
    (repo / ".reins" / "spec" / "backend").mkdir(parents=True)
    (repo / ".reins" / "spec" / "guides").mkdir(parents=True)
    (repo / ".reins" / "spec" / "backend" / "index.md").write_text("# Backend Spec\n", encoding="utf-8")
    (repo / ".reins" / "spec" / "guides" / "index.md").write_text("# Guide Spec\n", encoding="utf-8")
    context_file = repo / "notes.md"
    context_file.write_text("Important context\n", encoding="utf-8")

    create = invoke(
        repo,
        monkeypatch,
        [
            "task",
            "create",
            "Implement JWT auth",
            "--type",
            "backend",
            "--priority",
            "P0",
            "--prd",
            "Use RS256",
            "--acceptance",
            "JWT tokens generated",
            "--package",
            "cli",
        ],
    )
    assert create.exit_code == 0

    task_dirs = list((repo / ".reins" / "tasks").iterdir())
    assert len(task_dirs) == 1
    task_dir = task_dirs[0]
    task_id = task_dir.name
    task_json = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    assert task_json["title"] == "Implement JWT auth"
    assert task_json["priority"] == "P0"
    assert task_json["metadata"]["package"] == "cli"

    list_result = invoke(repo, monkeypatch, ["task", "list"])
    assert list_result.exit_code == 0
    assert task_id in list_result.output

    show_result = invoke(repo, monkeypatch, ["task", "show", task_id])
    assert show_result.exit_code == 0
    assert "Implement JWT auth" in show_result.output
    assert "Use RS256" in show_result.output

    start = invoke(repo, monkeypatch, ["task", "start", task_id, "--assignee", "peppa"])
    assert start.exit_code == 0
    assert (repo / ".reins" / ".current-task").read_text(encoding="utf-8").strip() == f"tasks/{task_id}"

    init_context = invoke(repo, monkeypatch, ["task", "init-context", task_id, "backend"])
    assert init_context.exit_code == 0
    for name in ("implement", "check", "debug"):
        assert (task_dir / f"{name}.jsonl").exists()

    add_context = invoke(
        repo,
        monkeypatch,
        ["task", "add-context", task_id, "implement", str(context_file), "--reason", "Extra notes"],
    )
    assert add_context.exit_code == 0
    lines = (task_dir / "implement.jsonl").read_text(encoding="utf-8").splitlines()
    added = json.loads(lines[-1])
    assert added["metadata"]["reason"] == "Extra notes"
    assert "Important context" in added["content"]

    finish = invoke(repo, monkeypatch, ["task", "finish", task_id, "--note", "Done"])
    assert finish.exit_code == 0
    assert not (repo / ".reins" / ".current-task").exists()

    archive = invoke(repo, monkeypatch, ["task", "archive", task_id, "--reason", "Merged"])
    assert archive.exit_code == 0

    event_types = [event.type for event in load_events(repo)]
    assert "task.created" in event_types
    assert "task.started" in event_types
    assert "task.completed" in event_types
    assert "task.archived" in event_types
    assert "task.context_initialized" in event_types
    assert "task.context_added" in event_types
