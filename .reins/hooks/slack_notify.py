"""Slack integration hook — sends task lifecycle notifications."""
from __future__ import annotations

import json
import os
from pathlib import Path

import reins.integrations.slack as _slack


def _read_task(task_json_path: str) -> dict:
    return json.loads(Path(task_json_path).read_text(encoding="utf-8"))


def _channel() -> str:
    return os.environ.get("SLACK_CHANNEL", "#general")


def _webhook_url() -> str:
    return os.environ["SLACK_WEBHOOK_URL"]


def notify_create(task_json_path: str) -> None:
    task = _read_task(task_json_path)
    title = task["title"]
    developer = task.get("metadata", {}).get("assignee", "cli")
    _slack.request_text(
        method="POST",
        url=_webhook_url(),
        json_body={
            "channel": _channel(),
            "text": f"New task created: {title}",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Task:* {title}\n*Developer:* {developer}\n*Status:* created",
                    },
                }
            ],
        },
    )


def notify_start(task_json_path: str) -> None:
    task = _read_task(task_json_path)
    title = task["title"]
    developer = task.get("assignee") or task.get("metadata", {}).get("assignee", "unknown")
    _slack.request_text(
        method="POST",
        url=_webhook_url(),
        json_body={
            "channel": _channel(),
            "text": f"Task started: {title}",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Task:* {title}\n*Developer:* {developer}\n*Status:* in_progress",
                    },
                }
            ],
        },
    )


def notify_archive(task_json_path: str) -> None:
    task = _read_task(task_json_path)
    title = task["title"]
    _slack.request_text(
        method="POST",
        url=_webhook_url(),
        json_body={
            "channel": _channel(),
            "text": f"Task completed: {title}",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Task:* {title}\n*Status:* archived",
                    },
                }
            ],
        },
    )
