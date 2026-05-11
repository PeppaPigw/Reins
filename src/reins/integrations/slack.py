"""Slack webhook integration for task lifecycle notifications.

Provides Block Kit message building, interactive approval requests,
configurable notification routing, and rich status messages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from reins.integrations._http import request_text


# ---------------------------------------------------------------------------
# Block Kit helpers
# ---------------------------------------------------------------------------


def header_block(text: str) -> dict[str, Any]:
    """Create a Block Kit header block."""
    return {"type": "header", "text": {"type": "plain_text", "text": text}}


def section_block(text: str) -> dict[str, Any]:
    """Create a Block Kit section block with mrkdwn text."""
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def divider_block() -> dict[str, Any]:
    """Create a Block Kit divider block."""
    return {"type": "divider"}


def actions_block(elements: list[dict[str, Any]]) -> dict[str, Any]:
    """Create a Block Kit actions block containing interactive elements."""
    return {"type": "actions", "elements": elements}


def button_element(
    text: str,
    action_id: str,
    value: str,
    style: str | None = None,
) -> dict[str, Any]:
    """Create a Block Kit button element.

    Parameters
    ----------
    text:
        Button label.
    action_id:
        Unique identifier for the action callback.
    value:
        Payload value sent when the button is clicked.
    style:
        Optional ``"primary"`` (green) or ``"danger"`` (red).
    """
    btn: dict[str, Any] = {
        "type": "button",
        "text": {"type": "plain_text", "text": text},
        "action_id": action_id,
        "value": value,
    }
    if style is not None:
        btn["style"] = style
    return btn


def context_block(elements: list[str]) -> dict[str, Any]:
    """Create a Block Kit context block with mrkdwn elements."""
    return {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": el} for el in elements],
    }


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SlackConfig:
    """Configuration for Slack incoming webhooks."""

    webhook_url: str
    channel: str = "#general"
    username: str = "Reins Bot"


# ---------------------------------------------------------------------------
# Notification templates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NotificationTemplate:
    """Configurable notification template for a specific event type."""

    event_type: str
    template: str
    channel_override: str | None = None
    include_blocks: bool = True


# ---------------------------------------------------------------------------
# Slack client
# ---------------------------------------------------------------------------


class SlackClient:
    """Slack webhook client for notifications and interactive messages."""

    def __init__(self, config: SlackConfig):
        self.config = config

    # -- Core messaging -------------------------------------------------------

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

    def send_rich_message(self, blocks: list[dict[str, Any]], text: str = "") -> None:
        """Send a Block Kit formatted message.

        Parameters
        ----------
        blocks:
            List of Block Kit block dicts.
        text:
            Fallback plain-text for notifications/accessibility.
        """
        self.send_message(text=text, blocks=blocks)

    # -- Interactive approval -------------------------------------------------

    def send_approval_request(
        self,
        request_id: str,
        title: str,
        description: str,
        requester: str,
        risk_level: str = "medium",
    ) -> None:
        """Send an interactive approval request with Approve/Deny buttons."""
        risk_emoji = {"low": "white_check_mark", "medium": "warning", "high": "rotating_light"}
        emoji = risk_emoji.get(risk_level, "warning")

        blocks: list[dict[str, Any]] = [
            header_block(f"Approval Required: {title}"),
            section_block(description),
            context_block([
                f"*Requester:* {requester}",
                f"*Risk:* :{emoji}: {risk_level}",
                f"*ID:* {request_id}",
            ]),
            divider_block(),
            actions_block([
                button_element("Approve", "approve_request", request_id, style="primary"),
                button_element("Deny", "deny_request", request_id, style="danger"),
            ]),
        ]

        self.send_message(
            text=f"Approval required: {title} (from {requester})",
            blocks=blocks,
        )

    # -- Status notifications -------------------------------------------------

    def send_run_status(self, run_id: str, status: str, summary: str) -> None:
        """Send a formatted run status notification."""
        status_emoji = {
            "running": "runner",
            "completed": "white_check_mark",
            "failed": "x",
            "paused": "pause_button",
        }
        emoji = status_emoji.get(status, "information_source")

        blocks: list[dict[str, Any]] = [
            header_block(f"Run Status: {status.title()}"),
            section_block(f":{emoji}: *{run_id}*\n\n{summary}"),
        ]

        self.send_message(text=f"Run {run_id}: {status}", blocks=blocks)

    def send_error_alert(
        self, error: str, context: str, severity: str = "warning"
    ) -> None:
        """Send an error notification with severity indicator."""
        severity_emoji = {"info": "information_source", "warning": "warning", "error": "x"}
        emoji = severity_emoji.get(severity, "warning")

        blocks: list[dict[str, Any]] = [
            header_block(f"Alert: {severity.title()}"),
            section_block(f":{emoji}: *Error:* {error}"),
            context_block([f"*Context:* {context}"]),
        ]

        self.send_message(text=f"[{severity}] {error}", blocks=blocks)

    # -- Legacy convenience methods -------------------------------------------

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


# ---------------------------------------------------------------------------
# Notification router
# ---------------------------------------------------------------------------


class NotificationRouter:
    """Routes events to Slack using configurable templates."""

    def __init__(
        self,
        client: SlackClient,
        templates: list[NotificationTemplate] | None = None,
    ):
        self._client = client
        self._templates: dict[str, NotificationTemplate] = {}
        for tpl in templates or []:
            self._templates[tpl.event_type] = tpl

    def add_template(self, template: NotificationTemplate) -> None:
        """Register a notification template for an event type."""
        self._templates[template.event_type] = template

    def route(self, event_type: str, context: dict[str, str]) -> None:
        """Find matching template, render variables, and send via client.

        If no template matches the event_type, the call is a no-op.
        """
        tpl = self._templates.get(event_type)
        if tpl is None:
            return

        rendered = tpl.template.format(**context)

        if tpl.include_blocks:
            blocks = [section_block(rendered)]
            self._client.send_rich_message(blocks=blocks, text=rendered)
        else:
            self._client.send_message(text=rendered)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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
