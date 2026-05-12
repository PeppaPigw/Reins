"""Linear integration hook — syncs task lifecycle to Linear Issues."""
from __future__ import annotations

import json
import os
from pathlib import Path

import reins.integrations.linear as _linear


def _read_task(task_json_path: str) -> dict:
    return json.loads(Path(task_json_path).read_text(encoding="utf-8"))


def _write_task(task_json_path: str, data: dict) -> None:
    Path(task_json_path).write_text(json.dumps(data, indent=2), encoding="utf-8")


def sync_create(task_json_path: str) -> None:
    task = _read_task(task_json_path)
    task_dir = Path(task_json_path).parent
    prd_path = task_dir / "prd.md"
    body = prd_path.read_text(encoding="utf-8") if prd_path.exists() else task["title"]
    team_id = os.environ["LINEAR_TEAM_ID"]
    result = _linear.request_json(
        method="POST",
        url="https://api.linear.app/graphql",
        json_body={
            "query": "mutation($input: IssueCreateInput!) { issueCreate(input: $input) { success issue { id identifier url } } }",
            "variables": {
                "input": {
                    "teamId": team_id,
                    "title": task["title"],
                    "description": body,
                }
            },
        },
    )
    issue = result["data"]["issueCreate"]["issue"]
    task.setdefault("metadata", {})["linear_issue_id"] = issue["id"]
    _write_task(task_json_path, task)


def sync_start(task_json_path: str) -> None:
    task = _read_task(task_json_path)
    issue_id = task["metadata"]["linear_issue_id"]
    state_id = os.environ["LINEAR_IN_PROGRESS_STATE_ID"]
    _linear.request_json(
        method="POST",
        url="https://api.linear.app/graphql",
        json_body={
            "query": "mutation($input: IssueUpdateInput!) { issueUpdate(id: $id, input: $input) { success issue { id } } }",
            "variables": {"id": issue_id, "input": {"stateId": state_id}},
        },
    )


def sync_archive(task_json_path: str) -> None:
    task = _read_task(task_json_path)
    issue_id = task["metadata"]["linear_issue_id"]
    state_id = os.environ["LINEAR_DONE_STATE_ID"]
    _linear.request_json(
        method="POST",
        url="https://api.linear.app/graphql",
        json_body={
            "query": "mutation($input: IssueUpdateInput!) { issueUpdate(id: $id, input: $input) { success issue { id } } }",
            "variables": {"id": issue_id, "input": {"stateId": state_id}},
        },
    )
