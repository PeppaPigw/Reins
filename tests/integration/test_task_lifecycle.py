from __future__ import annotations

from tests.integration.helpers import (
    assert_event_types_in_order,
    assert_jsonl_valid,
    ensure_base_specs,
    load_json,
)


def test_task_lifecycle_integration(integration_harness) -> None:
    repo_root = integration_harness.repo_root

    assert integration_harness.invoke(["developer", "init", "peppa"]).exit_code == 0
    assert (
        integration_harness.invoke(
            ["spec", "init", "--package", "cli", "--layers", "commands,workflow"]
        ).exit_code
        == 0
    )
    ensure_base_specs(repo_root, package="cli", layers=("commands", "workflow"))

    create = integration_harness.invoke(
        [
            "task",
            "create",
            "Build integration lifecycle",
            "--type",
            "backend",
            "--priority",
            "P1",
            "--package",
            "cli",
            "--prd",
            "Validate the end-to-end task lifecycle via CLI commands.",
            "--acceptance",
            "Task emits lifecycle events",
            "--acceptance",
            "Context files are created",
        ]
    )
    assert create.exit_code == 0

    task_id = integration_harness.latest_task_id()
    task_dir = integration_harness.task_dir(task_id)
    task_json = load_json(task_dir / "task.json")
    assert task_json["title"] == "Build integration lifecycle"
    assert task_json["status"] == "pending"
    assert task_json["metadata"]["package"] == "cli"
    assert (task_dir / "prd.md").exists()

    assert integration_harness.current_task_id() is None
    assert (
        integration_harness.invoke(["task", "start", task_id, "--assignee", "peppa"]).exit_code
        == 0
    )
    assert integration_harness.current_task_id() == task_id

    assert integration_harness.invoke(["task", "init-context", task_id, "backend"]).exit_code == 0
    extra = repo_root / "notes.md"
    extra.write_text("# Notes\n\nRemember the archive reason.\n", encoding="utf-8")
    assert (
        integration_harness.invoke(
            [
                "task",
                "add-context",
                task_id,
                "check",
                str(extra),
                "--reason",
                "Lifecycle reminder",
            ]
        ).exit_code
        == 0
    )

    for file_name in ("implement.jsonl", "check.jsonl", "debug.jsonl"):
        assert (task_dir / file_name).exists()
        assert_jsonl_valid(task_dir / file_name)

    check_messages = assert_jsonl_valid(task_dir / "check.jsonl")
    assert any(message.metadata.get("kind") == "prd" for message in check_messages)
    assert any(message.metadata.get("reason") == "Lifecycle reminder" for message in check_messages)

    assert (
        integration_harness.invoke(
            ["task", "finish", task_id, "--note", "Lifecycle integration complete"]
        ).exit_code
        == 0
    )
    assert integration_harness.current_task_id() is None

    assert (
        integration_harness.invoke(
            ["task", "archive", task_id, "--reason", "Covered by integration tests"]
        ).exit_code
        == 0
    )

    final_task_json = load_json(task_dir / "task.json")
    assert final_task_json["status"] == "archived"
    assert final_task_json["assignee"] == "peppa"
    assert final_task_json["started_at"] is not None
    assert final_task_json["completed_at"] is not None

    events = integration_harness.load_events()
    assert_event_types_in_order(
        events,
        [
            "developer.initialized",
            "spec.initialized",
            "task.created",
            "task.started",
            "task.context_initialized",
            "task.context_added",
            "task.completed",
            "task.archived",
        ],
    )

    lifecycle_payloads = {
        event.type: event.payload
        for event in events
        if event.type in {"task.created", "task.started", "task.completed", "task.archived"}
    }
    assert lifecycle_payloads["task.created"]["task_id"] == task_id
    assert lifecycle_payloads["task.started"]["assignee"] == "peppa"
    assert lifecycle_payloads["task.completed"]["outcome"]["note"] == "Lifecycle integration complete"
    assert lifecycle_payloads["task.archived"]["reason"] == "Covered by integration tests"
