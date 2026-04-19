"""Slack webhook integration for task lifecycle notifications."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from reins.integrations._http import request_text


@dataclass(frozen=True)
class SlackConfig:
    """Configuration for Slack incoming webhooks."""

    webhook_url: str
    channel: str = "#general"
    username: str = "Reins Bot"


class SlackClient:
    """Slack webhook client for notifications."""

    def __init__(self, config: SlackConfig):
        self.config = config

    def send_message(self, text: str, blocks: list[dict[str, Any]] | None = None) -> None:
        """Send a message to Slack.

        Slack app incoming webhooks typically decide the destination channel and
        sender identity at install time, but channel and username are still sent
        for compatibility with legacy webhook configurations.
        """
        payload: dict[str, Any] = {
            "text": text,
            "channel": self.config.channel,
            "username": self.config.username,
        }
        if blocks:
            payload["blocks"] = blocks

        request_text(
            self.config.webhook_url,
            method="POST",
            json_body=payload,
        )

    def notify_task_created(self, task_title: str, developer: str) -> None:
        """Notify Slack when a task is created."""
        self.send_message(
            text=f"New task created: {task_title}",
            blocks=_message_blocks("New Task Created", task_title, developer),
        )

    def notify_task_started(self, task_title: str, developer: str) -> None:
        """Notify Slack when a task starts."""
        self.send_message(
            text=f"Task started: {task_title}",
            blocks=_message_blocks("Task Started", task_title, developer),
        )

    def notify_task_completed(self, task_title: str, developer: str) -> None:
        """Notify Slack when a task is completed."""
        self.send_message(
            text=f"Task completed: {task_title}",
            blocks=_message_blocks("Task Completed", task_title, developer),
        )


def _message_blocks(header: str, task_title: str, developer: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{header}*\n\n*Title:* {task_title}\n*Developer:* {developer}",
            },
        }
    ]
