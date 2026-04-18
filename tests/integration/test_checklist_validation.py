from __future__ import annotations

import json


def test_spec_checklist_validate_and_mark_read(integration_harness) -> None:
    repo_root = integration_harness.repo_root
    (repo_root / ".reins" / "spec" / "backend").mkdir(parents=True, exist_ok=True)
    (repo_root / ".reins" / "spec" / "guides").mkdir(parents=True, exist_ok=True)
    (repo_root / ".reins" / "spec" / "backend" / "error-handling.md").write_text(
        "# Error Handling\n",
        encoding="utf-8",
    )
    (repo_root / ".reins" / "spec" / "backend" / "index.md").write_text(
        "# Backend Specifications\n\n"
        "## Pre-Development Checklist\n\n"
        "- [ ] [Error Handling](error-handling.md) - Read the backend rules\n",
        encoding="utf-8",
    )
    (repo_root / ".reins" / "spec" / "guides" / "index.md").write_text(
        "# Guides\n",
        encoding="utf-8",
    )

    assert integration_harness.invoke(["developer", "init", "peppa"]).exit_code == 0
    create = integration_harness.invoke(
        [
            "task",
            "create",
            "Validate checklist",
            "--type",
            "backend",
            "--priority",
            "P1",
            "--prd",
            "Validate checklist management.",
            "--acceptance",
            "Checklist validates",
        ]
    )
    assert create.exit_code == 0
    task_id = integration_harness.latest_task_id()
    assert integration_harness.invoke(["task", "start", task_id, "--assignee", "peppa"]).exit_code == 0

    invalid = integration_harness.invoke(["spec", "checklist", "--validate"])
    assert invalid.exit_code == 1

    marked = integration_harness.invoke(
        ["spec", "checklist", "--mark-read", "backend/error-handling.md"]
    )
    assert marked.exit_code == 0

    valid = integration_harness.invoke(["spec", "checklist", "--validate"])
    assert valid.exit_code == 0

    task_json = json.loads((integration_harness.task_dir(task_id) / "task.json").read_text(encoding="utf-8"))
    assert task_json["metadata"]["checklist"]["read_specs"] == ["backend/error-handling.md"]
