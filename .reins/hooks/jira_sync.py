"""Jira integration hook — syncs task lifecycle to Jira Issues."""
from __future__ import annotations

import json
import os
from pathlib import Path

import reins.integrations.jira as _jira


def _read_task(task_json_path: str) -> dict:
    return json.loads(Path(task_json_path).read_text(encoding="utf-8"))


def _write_task(task_json_path: str, data: dict) -> None:
    Path(task_json_path).write_text(json.dumps(data, indent=2), encoding="utf-8")


def _base_url() -> str:
    return os.environ["JIRA_BASE_URL"]


def sync_create(task_json_path: str) -> None:
    task = _read_task(task_json_path)
    task_dir = Path(task_json_path).parent
    prd_path = task_dir / "prd.md"
    body = prd_path.read_text(encoding="utf-8") if prd_path.exists() else task["title"]
    project_key = os.environ["JIRA_PROJECT_KEY"]
    result = _jira.request_json(
        method="POST",
        url=f"{_base_url()}/rest/api/3/issue",
        json_body={
            "fields": {
                "project": {"key": project_key},
                "summary": task["title"],
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": body}]}],
                },
                "issuetype": {"name": "Task"},
            }
        },
    )
    task.setdefault("metadata", {})["jira_issue_key"] = result["key"]
    _write_task(task_json_path, task)


def sync_start(task_json_path: str) -> None:
    task = _read_task(task_json_path)
    issue_key = task["metadata"]["jira_issue_key"]
    transitions = _jira.request_json(
        method="GET",
        url=f"{_base_url()}/rest/api/3/issue/{issue_key}/transitions",
        json_body={},
    )
    in_progress_id = next(
        t["id"] for t in transitions["transitions"] if t["name"] == "In Progress"
    )
    _jira.request_json(
        method="POST",
        url=f"{_base_url()}/rest/api/3/issue/{issue_key}/transitions",
        json_body={"transition": {"id": in_progress_id}},
    )


def sync_archive(task_json_path: str) -> None:
    task = _read_task(task_json_path)
    issue_key = task["metadata"]["jira_issue_key"]
    transitions = _jira.request_json(
        method="GET",
        url=f"{_base_url()}/rest/api/3/issue/{issue_key}/transitions",
        json_body={},
    )
    done_id = next(t["id"] for t in transitions["transitions"] if t["name"] == "Done")
    _jira.request_json(
        method="POST",
        url=f"{_base_url()}/rest/api/3/issue/{issue_key}/transitions",
        json_body={"transition": {"id": done_id}},
    )
