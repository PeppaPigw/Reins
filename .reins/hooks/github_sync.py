"""GitHub integration hook — syncs task lifecycle to GitHub Issues."""
from __future__ import annotations

import json
import os
from pathlib import Path

import reins.integrations.github as _github


def _read_task(task_json_path: str) -> dict:
    return json.loads(Path(task_json_path).read_text(encoding="utf-8"))


def _write_task(task_json_path: str, data: dict) -> None:
    Path(task_json_path).write_text(json.dumps(data, indent=2), encoding="utf-8")


def _repo() -> str:
    return os.environ["GITHUB_REPO"]


def _token() -> str:
    return os.environ["GITHUB_TOKEN"]


def sync_create(task_json_path: str) -> None:
    task = _read_task(task_json_path)
    task_dir = Path(task_json_path).parent
    prd_path = task_dir / "prd.md"
    body = prd_path.read_text(encoding="utf-8") if prd_path.exists() else task["title"]
    result = _github.request_json(
        method="POST",
        url=f"https://api.github.com/repos/{_repo()}/issues",
        headers={"Authorization": f"Bearer {_token()}"},
        json_body={
            "title": task["title"],
            "body": body,
            "labels": ["reins-task"],
        },
    )
    task.setdefault("metadata", {})["github_issue_number"] = result["number"]
    _write_task(task_json_path, task)


def sync_start(task_json_path: str) -> None:
    task = _read_task(task_json_path)
    issue_number = task["metadata"]["github_issue_number"]
    _github.request_json(
        method="PATCH",
        url=f"https://api.github.com/repos/{_repo()}/issues/{issue_number}",
        headers={"Authorization": f"Bearer {_token()}"},
        json_body={"labels": ["reins-task", "in-progress"]},
    )


def sync_archive(task_json_path: str) -> None:
    task = _read_task(task_json_path)
    issue_number = task["metadata"]["github_issue_number"]
    _github.request_json(
        method="PATCH",
        url=f"https://api.github.com/repos/{_repo()}/issues/{issue_number}",
        headers={"Authorization": f"Bearer {_token()}"},
        json_body={"state": "closed"},
    )
