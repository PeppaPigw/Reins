"""Webhook payload parsing and signature verification for external services."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class WebhookSource(str, Enum):
    """Supported webhook sources."""

    github = "github"
    linear = "linear"
    slack = "slack"


@dataclass(frozen=True)
class WebhookEvent:
    """Parsed webhook event from an external service."""

    source: WebhookSource
    event_type: str
    payload: dict[str, Any]
    received_at: str
    signature: str | None = None


class GitHubWebhookParser:
    """Parses and verifies GitHub webhook payloads."""

    def parse(self, headers: dict[str, str], body: bytes) -> WebhookEvent:
        """Parse a GitHub webhook request into a WebhookEvent."""
        event_header = headers.get("X-GitHub-Event", "")
        payload = json.loads(body.decode("utf-8"))
        action = payload.get("action", "")
        event_type = f"{event_header}.{action}" if action else event_header
        signature = headers.get("X-Hub-Signature-256")
        return WebhookEvent(
            source=WebhookSource.github,
            event_type=event_type,
            payload=payload,
            received_at=datetime.now(UTC).isoformat(),
            signature=signature,
        )

    def verify_signature(self, body: bytes, signature: str, secret: str) -> bool:
        """Verify a GitHub webhook HMAC-SHA256 signature."""
        expected = "sha256=" + hmac.new(
            secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def extract_issue_event(self, event: WebhookEvent) -> dict[str, Any]:
        """Extract issue details from a webhook event payload."""
        issue = event.payload.get("issue", {})
        return {
            "number": issue.get("number"),
            "action": event.payload.get("action"),
            "labels": [lbl.get("name") for lbl in issue.get("labels", [])],
            "assignee": (issue.get("assignee") or {}).get("login"),
            "title": issue.get("title"),
        }

    def extract_pr_event(self, event: WebhookEvent) -> dict[str, Any]:
        """Extract pull request details from a webhook event payload."""
        pr = event.payload.get("pull_request", {})
        return {
            "number": pr.get("number"),
            "action": event.payload.get("action"),
            "branch": (pr.get("head") or {}).get("ref"),
            "merged": pr.get("merged", False),
            "title": pr.get("title"),
        }


class LinearWebhookParser:
    """Parses Linear webhook payloads."""

    def parse(self, headers: dict[str, str], body: bytes) -> WebhookEvent:
        """Parse a Linear webhook request into a WebhookEvent."""
        payload = json.loads(body.decode("utf-8"))
        action = payload.get("action", "")
        entity_type = payload.get("type", "Issue")
        event_type = f"{entity_type.lower()}.{action}" if action else entity_type.lower()
        return WebhookEvent(
            source=WebhookSource.linear,
            event_type=event_type,
            payload=payload,
            received_at=datetime.now(UTC).isoformat(),
            signature=None,
        )

    def extract_issue_event(self, event: WebhookEvent) -> dict[str, Any]:
        """Extract issue details from a Linear webhook event."""
        data = event.payload.get("data", {})
        return {
            "id": data.get("id"),
            "action": event.payload.get("action"),
            "state": data.get("state", {}).get("name") if isinstance(
                data.get("state"), dict
            ) else data.get("state"),
            "title": data.get("title"),
        }
