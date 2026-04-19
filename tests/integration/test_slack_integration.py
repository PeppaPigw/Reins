from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

from tests.unit.cli_helpers import create_repo, invoke


def _latest_task_id(repo: Path) -> str:
    task_dirs = sorted(path.name for path in (repo / ".reins" / "tasks").iterdir() if path.is_dir())
    assert task_dirs
    return task_dirs[-1]


def _load_hook_module() -> object:
    script_path = Path(__file__).resolve().parents[2] / ".reins" / "hooks" / "slack_notify.py"
    spec = importlib.util.spec_from_file_location("test_slack_notify_hook", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_slack_hook_sends_lifecycle_notifications(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path)
    hook = _load_hook_module()
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/services/abc")
    monkeypatch.setenv("SLACK_CHANNEL", "#engineering")
    monkeypatch.setenv("SLACK_USERNAME", "Reins Bot")

    create = invoke(
        repo,
        monkeypatch,
        [
            "task",
            "create",
            "Hooked Slack task",
            "--type",
            "backend",
            "--priority",
            "P1",
            "--prd",
            "Ship a Slack hook",
        ],
    )
    assert create.exit_code == 0
    task_id = _latest_task_id(repo)
    task_json_path = repo / ".reins" / "tasks" / task_id / "task.json"

    with patch("reins.integrations.slack.request_text") as mock_request:
        mock_request.return_value = "ok"

        hook.notify_create(str(task_json_path))
        start = invoke(repo, monkeypatch, ["task", "start", task_id, "--assignee", "peppa"])
        assert start.exit_code == 0
        hook.notify_start(str(task_json_path))
        archive = invoke(repo, monkeypatch, ["task", "archive", task_id])
        assert archive.exit_code == 0
        hook.notify_archive(str(task_json_path))

    assert mock_request.call_count == 3
    create_payload = mock_request.call_args_list[0].kwargs["json_body"]
    start_payload = mock_request.call_args_list[1].kwargs["json_body"]
    archive_payload = mock_request.call_args_list[2].kwargs["json_body"]
    assert create_payload["text"] == "New task created: Hooked Slack task"
    assert "*Developer:* cli" in create_payload["blocks"][0]["text"]["text"]
    assert start_payload["text"] == "Task started: Hooked Slack task"
    assert "*Developer:* peppa" in start_payload["blocks"][0]["text"]["text"]
    assert archive_payload["text"] == "Task completed: Hooked Slack task"
    assert archive_payload["channel"] == "#engineering"
