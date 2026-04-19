from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

from tests.unit.cli_helpers import create_repo, invoke


def _latest_task_id(repo: Path) -> str:
    task_dirs = sorted(path.name for path in (repo / ".reins" / "tasks").iterdir() if path.is_dir())
    assert task_dirs
    return task_dirs[-1]


def _load_hook_module() -> object:
    script_path = Path(__file__).resolve().parents[2] / ".reins" / "hooks" / "github_sync.py"
    spec = importlib.util.spec_from_file_location("test_github_sync_hook", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_github_hook_syncs_issue_number_and_lifecycle(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path)
    hook = _load_hook_module()
    monkeypatch.setenv("GITHUB_TOKEN", "github-token")
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")

    create = invoke(
        repo,
        monkeypatch,
        [
            "task",
            "create",
            "Hooked GitHub task",
            "--type",
            "backend",
            "--priority",
            "P1",
            "--prd",
            "Ship a GitHub hook",
        ],
    )
    assert create.exit_code == 0
    task_id = _latest_task_id(repo)
    task_json_path = repo / ".reins" / "tasks" / task_id / "task.json"

    with patch("reins.integrations.github.request_json") as mock_request:
        mock_request.side_effect = [
            {"number": 42},
            {"number": 42, "labels": ["reins-task", "in-progress"]},
            {"number": 42, "state": "closed"},
        ]

        hook.sync_create(str(task_json_path))
        task_json = json.loads(task_json_path.read_text(encoding="utf-8"))
        assert task_json["metadata"]["github_issue_number"] == 42

        start = invoke(repo, monkeypatch, ["task", "start", task_id, "--assignee", "peppa"])
        assert start.exit_code == 0
        hook.sync_start(str(task_json_path))

        archive = invoke(repo, monkeypatch, ["task", "archive", task_id])
        assert archive.exit_code == 0
        hook.sync_archive(str(task_json_path))

    task_json = json.loads(task_json_path.read_text(encoding="utf-8"))
    assert task_json["metadata"]["github_issue_number"] == 42
    assert mock_request.call_count == 3
    create_payload = mock_request.call_args_list[0].kwargs["json_body"]
    start_payload = mock_request.call_args_list[1].kwargs["json_body"]
    archive_payload = mock_request.call_args_list[2].kwargs["json_body"]
    assert create_payload["title"] == "Hooked GitHub task"
    assert "Ship a GitHub hook" in create_payload["body"]
    assert create_payload["labels"] == ["reins-task"]
    assert start_payload == {"labels": ["reins-task", "in-progress"]}
    assert archive_payload == {"state": "closed"}
