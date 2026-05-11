"""Tests for webhook parsing and trigger mechanism."""

from __future__ import annotations

import hashlib
import hmac
import json

from reins.integrations.triggers import (
    TriggerAction,
    TriggerCondition,
    TriggerEngine,
    TriggerRule,
)
from reins.integrations.webhooks import (
    GitHubWebhookParser,
    LinearWebhookParser,
    WebhookEvent,
    WebhookSource,
)


def _github_issue_payload(action: str = "opened", number: int = 5) -> bytes:
    return json.dumps({
        "action": action,
        "issue": {
            "number": number,
            "title": "Test issue",
            "labels": [{"name": "bug"}, {"name": "agent-task"}],
            "assignee": {"login": "dev1"},
        },
    }).encode("utf-8")


def _github_pr_payload(action: str = "closed", number: int = 12) -> bytes:
    return json.dumps({
        "action": action,
        "pull_request": {
            "number": number,
            "title": "Fix bug",
            "head": {"ref": "fix/bug-123"},
            "merged": True,
        },
    }).encode("utf-8")


class TestGitHubWebhookParser:
    def test_github_webhook_parser_parses_issue_event(self):
        parser = GitHubWebhookParser()
        headers = {"X-GitHub-Event": "issues"}
        body = _github_issue_payload("labeled")
        event = parser.parse(headers, body)
        assert event.source == WebhookSource.github
        assert event.event_type == "issues.labeled"
        assert event.payload["action"] == "labeled"
        assert event.payload["issue"]["number"] == 5

        extracted = parser.extract_issue_event(event)
        assert extracted["number"] == 5
        assert extracted["action"] == "labeled"
        assert "agent-task" in extracted["labels"]
        assert extracted["assignee"] == "dev1"

    def test_github_webhook_parser_parses_pr_event(self):
        parser = GitHubWebhookParser()
        headers = {"X-GitHub-Event": "pull_request"}
        body = _github_pr_payload("closed", number=12)
        event = parser.parse(headers, body)
        assert event.source == WebhookSource.github
        assert event.event_type == "pull_request.closed"

        extracted = parser.extract_pr_event(event)
        assert extracted["number"] == 12
        assert extracted["action"] == "closed"
        assert extracted["branch"] == "fix/bug-123"
        assert extracted["merged"] is True

    def test_github_webhook_verify_signature_valid(self):
        parser = GitHubWebhookParser()
        secret = "my-webhook-secret"
        body = b'{"action":"opened"}'
        sig = "sha256=" + hmac.new(
            secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        assert parser.verify_signature(body, sig, secret) is True

    def test_github_webhook_verify_signature_invalid(self):
        parser = GitHubWebhookParser()
        body = b'{"action":"opened"}'
        assert parser.verify_signature(body, "sha256=invalid", "secret") is False


class TestLinearWebhookParser:
    def test_linear_webhook_parser_parses_event(self):
        parser = LinearWebhookParser()
        payload = {
            "action": "update",
            "type": "Issue",
            "data": {
                "id": "LIN-123",
                "title": "Fix login",
                "state": {"name": "In Progress"},
            },
        }
        body = json.dumps(payload).encode("utf-8")
        event = parser.parse({}, body)
        assert event.source == WebhookSource.linear
        assert event.event_type == "issue.update"

        extracted = parser.extract_issue_event(event)
        assert extracted["id"] == "LIN-123"
        assert extracted["action"] == "update"
        assert extracted["state"] == "In Progress"


class TestTriggerCondition:
    def test_trigger_condition_matches_source_and_type(self):
        engine = TriggerEngine()
        condition = TriggerCondition(
            source=WebhookSource.github, event_type="issues.labeled"
        )
        event = WebhookEvent(
            source=WebhookSource.github,
            event_type="issues.labeled",
            payload={"action": "labeled"},
            received_at="2024-01-01T00:00:00Z",
        )
        assert engine._matches_condition(event, condition) is True

    def test_trigger_condition_matches_filter(self):
        engine = TriggerEngine()
        condition = TriggerCondition(
            source=WebhookSource.github,
            event_type="issues.labeled",
            filter={"action": "labeled"},
        )
        event = WebhookEvent(
            source=WebhookSource.github,
            event_type="issues.labeled",
            payload={"action": "labeled"},
            received_at="2024-01-01T00:00:00Z",
        )
        assert engine._matches_condition(event, condition) is True

    def test_trigger_condition_no_match_wrong_source(self):
        engine = TriggerEngine()
        condition = TriggerCondition(
            source=WebhookSource.linear, event_type="issues.labeled"
        )
        event = WebhookEvent(
            source=WebhookSource.github,
            event_type="issues.labeled",
            payload={},
            received_at="2024-01-01T00:00:00Z",
        )
        assert engine._matches_condition(event, condition) is False


class TestTriggerEngine:
    def test_trigger_engine_evaluate_returns_matching_rules(self):
        rule = TriggerRule(
            name="spawn-on-label",
            condition=TriggerCondition(
                source=WebhookSource.github,
                event_type="issues.labeled",
                filter={"action": "labeled"},
            ),
            action=TriggerAction.spawn_run,
            action_config={"task_type": "backend"},
        )
        engine = TriggerEngine(rules=[rule])
        event = WebhookEvent(
            source=WebhookSource.github,
            event_type="issues.labeled",
            payload={"action": "labeled"},
            received_at="2024-01-01T00:00:00Z",
        )
        matches = engine.evaluate(event)
        assert len(matches) == 1
        assert matches[0].name == "spawn-on-label"

    def test_trigger_engine_skips_disabled_rules(self):
        rule = TriggerRule(
            name="disabled-rule",
            condition=TriggerCondition(
                source=WebhookSource.github, event_type="issues.opened"
            ),
            action=TriggerAction.notify,
            enabled=False,
        )
        engine = TriggerEngine(rules=[rule])
        event = WebhookEvent(
            source=WebhookSource.github,
            event_type="issues.opened",
            payload={"action": "opened"},
            received_at="2024-01-01T00:00:00Z",
        )
        matches = engine.evaluate(event)
        assert len(matches) == 0

    def test_trigger_engine_add_and_remove_rules(self):
        engine = TriggerEngine()
        assert len(engine.get_rules()) == 0

        rule = TriggerRule(
            name="test-rule",
            condition=TriggerCondition(
                source=WebhookSource.github, event_type="issues.opened"
            ),
            action=TriggerAction.create_task,
        )
        engine.add_rule(rule)
        assert len(engine.get_rules()) == 1
        assert engine.get_enabled_rules()[0].name == "test-rule"

        engine.remove_rule("test-rule")
        assert len(engine.get_rules()) == 0

    def test_trigger_rule_dataclass_fields(self):
        condition = TriggerCondition(
            source=WebhookSource.github,
            event_type="pull_request.closed",
            filter={"action": "closed"},
        )
        rule = TriggerRule(
            name="merge-notify",
            condition=condition,
            action=TriggerAction.notify,
            action_config={"channel": "#deploys"},
            enabled=True,
        )
        assert rule.name == "merge-notify"
        assert rule.condition.source == WebhookSource.github
        assert rule.action == TriggerAction.notify
        assert rule.action_config == {"channel": "#deploys"}
        assert rule.enabled is True