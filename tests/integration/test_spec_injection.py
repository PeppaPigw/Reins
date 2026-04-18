from __future__ import annotations

from reins.task.context_jsonl import ContextJSONL
from tests.integration.helpers import (
    assert_jsonl_valid,
    ensure_base_specs,
)


def test_spec_injection_integration(integration_harness) -> None:
    repo_root = integration_harness.repo_root

    assert integration_harness.invoke(["developer", "init", "peppa"]).exit_code == 0
    assert (
        integration_harness.invoke(
            ["spec", "init", "--package", "auth", "--layers", "commands,workflow"]
        ).exit_code
        == 0
    )
    ensure_base_specs(repo_root, package="auth", layers=("commands", "workflow"))

    package_rule = repo_root / ".reins" / "spec" / "auth" / "commands" / "custom-rule.md"
    package_rule.parent.mkdir(parents=True, exist_ok=True)
    package_rule.write_text(
        "# Auth Command Rule\n\nUse explicit command names for auth flows.\n",
        encoding="utf-8",
    )

    create = integration_harness.invoke(
        [
            "task",
            "create",
            "Inject auth specs",
            "--type",
            "backend",
            "--priority",
            "P1",
            "--package",
            "auth",
            "--prd",
            "Load the default auth spec files into task context JSONL.",
            "--acceptance",
            "Task context contains auth specs",
        ]
    )
    assert create.exit_code == 0
    task_id = integration_harness.latest_task_id()
    task_dir = integration_harness.task_dir(task_id)

    assert integration_harness.invoke(["task", "init-context", task_id, "backend"]).exit_code == 0
    assert (
        integration_harness.invoke(
            [
                "task",
                "add-context",
                task_id,
                "implement",
                str(package_rule),
                "--reason",
                "Auth package command rules",
            ]
        ).exit_code
        == 0
    )

    implement_messages = assert_jsonl_valid(task_dir / "implement.jsonl")
    check_messages = assert_jsonl_valid(task_dir / "check.jsonl")
    debug_messages = assert_jsonl_valid(task_dir / "debug.jsonl")
    assert implement_messages
    assert check_messages
    assert debug_messages

    combined = "\n".join(message.content for message in implement_messages)
    assert "Pre-Development Checklist" in combined
    assert "Auth Specifications" in combined
    assert "Backend Rules" in combined
    assert "Guides" in combined
    assert "Use explicit command names for auth flows." in combined

    extra_entries = [
        message
        for message in implement_messages
        if message.metadata.get("reason") == "Auth package command rules"
    ]
    assert len(extra_entries) == 1
    assert extra_entries[0].metadata["source"].endswith("custom-rule.md")

    for path in (
        task_dir / "implement.jsonl",
        task_dir / "check.jsonl",
        task_dir / "debug.jsonl",
    ):
        valid, errors = ContextJSONL.validate_jsonl(path)
        assert valid, errors

    hook_output = "\n".join(message.content for message in ContextJSONL.read_messages(task_dir / "implement.jsonl"))
    assert "Auth Command Rule" in hook_output
    assert "Pre-Development Checklist" in hook_output

    events = integration_harness.load_events()
    event_types = [event.type for event in events]
    assert "spec.initialized" in event_types
    assert "task.context_initialized" in event_types
    assert "task.context_added" in event_types
