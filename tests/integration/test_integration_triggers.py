"""Integration tests for webhook -> trigger -> sync end-to-end flows.

Validates that GitHub and Linear webhooks are correctly parsed, matched
against trigger rules, and routed through the sync engine and approval manager.
"""

from __future__ import annotations

import json

import pytest

from reins.integrations.approval import ApprovalManager
from reins.integrations.sync import SyncDirection, SyncEngine
from reins.integrations.triggers import (
    TriggerAction,
    TriggerCondition,
    TriggerEngine,
    TriggerRule,
)
from reins.integrations.webhooks import (
    GitHubWebhookParser,
    LinearWebhookParser,
    WebhookSource,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _github_issue_labeled_payload(label: str = "agent-task") -> bytes:
    """Create a mock GitHub issues.labeled webhook payload."""
    return json.dumps({
        "action": "labeled",
        "label": {"name": label},
        "issue": {
            "number": 42,
            "title": "Implement feature X",
            "labels": [{"name": label}],
            "assignee": {"login": "bot-agent"},
        },
    }).encode("utf-8")


def _github_pr_closed_merged_payload() -> bytes:
    """Create a mock GitHub pull_request.closed (merged) webhook payload."""
    return json.dumps({
        "action": "closed",
        "pull_request": {
            "number": 99,
            "title": "feat: add sync engine",
            "head": {"ref": "feat/sync-engine"},
            "merged": True,
        },
    }).encode("utf-8")


def _github_issue_opened_payload() -> bytes:
    """Create a mock GitHub issues.opened webhook payload (no special label)."""
    return json.dumps({
        "action": "opened",
        "issue": {
            "number": 50,
            "title": "Bug report",
            "labels": [],
            "assignee": None,
        },
    }).encode("utf-8")


def _linear_state_change_payload(
    issue_id: str = "lin-issue-1",
    new_state: str = "In Progress",
) -> bytes:
    """Create a mock Linear issue.updated webhook payload."""
    return json.dumps({
        "action": "updated",
        "type": "Issue",
        "data": {
            "id": issue_id,
            "title": "Implement sync",
            "state": {"id": "state-2", "name": new_state},
        },
    }).encode("utf-8")


# ---------------------------------------------------------------------------
# GitHub trigger flow tests
# ---------------------------------------------------------------------------


class TestGitHubTriggerFlow:
    """Tests for GitHub webhook -> trigger evaluation flow."""

    def test_issue_labeled_triggers_run_spawn(self) -> None:
        """An issues.labeled event with the right label should trigger spawn_run."""
        engine = TriggerEngine(rules=[
            TriggerRule(
                name="agent-task-spawn",
                condition=TriggerCondition(
                    source=WebhookSource.github,
                    event_type="issues.labeled",
                    filter={"label.name": "agent-task"},
                ),
                action=TriggerAction.spawn_run,
            )
        ])

        parser = GitHubWebhookParser()
        event = parser.parse(
            {"X-GitHub-Event": "issues"},
            _github_issue_labeled_payload("agent-task"),
        )

        matches = engine.evaluate(event)
        assert len(matches) == 1
        assert matches[0].action == TriggerAction.spawn_run
        assert matches[0].name == "agent-task-spawn"

    def test_pr_merged_triggers_notification(self) -> None:
        """A pull_request.closed event with merged=True should trigger notify."""
        engine = TriggerEngine(rules=[
            TriggerRule(
                name="pr-merged-notify",
                condition=TriggerCondition(
                    source=WebhookSource.github,
                    event_type="pull_request.closed",
                    filter={"pull_request.merged": "True"},
                ),
                action=TriggerAction.notify,
            )
        ])

        parser = GitHubWebhookParser()
        event = parser.parse(
            {"X-GitHub-Event": "pull_request"},
            _github_pr_closed_merged_payload(),
        )

        matches = engine.evaluate(event)
        assert len(matches) == 1
        assert matches[0].action == TriggerAction.notify

    def test_issue_opened_no_match_without_label(self) -> None:
        """An issues.opened event should not match a rule requiring a label."""
        engine = TriggerEngine(rules=[
            TriggerRule(
                name="agent-task-spawn",
                condition=TriggerCondition(
                    source=WebhookSource.github,
                    event_type="issues.labeled",
                    filter={"label.name": "agent-task"},
                ),
                action=TriggerAction.spawn_run,
            )
        ])

        parser = GitHubWebhookParser()
        event = parser.parse(
            {"X-GitHub-Event": "issues"},
            _github_issue_opened_payload(),
        )

        matches = engine.evaluate(event)
        assert len(matches) == 0


# ---------------------------------------------------------------------------
# Linear trigger flow tests
# ---------------------------------------------------------------------------


class TestLinearTriggerFlow:
    """Tests for Linear webhook -> trigger -> sync flow."""

    def test_linear_state_change_triggers_task_update(self) -> None:
        """A Linear issue.updated event should match a create_task rule."""
        engine = TriggerEngine(rules=[
            TriggerRule(
                name="linear-state-sync",
                condition=TriggerCondition(
                    source=WebhookSource.linear,
                    event_type="issue.updated",
                ),
                action=TriggerAction.create_task,
            )
        ])

        parser = LinearWebhookParser()
        event = parser.parse({}, _linear_state_change_payload())

        matches = engine.evaluate(event)
        assert len(matches) == 1
        assert matches[0].action == TriggerAction.create_task

    def test_linear_sync_maps_state_correctly(self) -> None:
        """SyncEngine should map Linear states to Reins statuses bidirectionally."""
        engine = SyncEngine()
        engine.link("lin-issue-1", "task-42")

        # Inbound: Linear "In Progress" -> Reins "in_progress"
        assert engine.map_state_inbound("In Progress") == "in_progress"
        # Outbound: Reins "in_progress" -> Linear "In Progress"
        assert engine.map_state_outbound("in_progress") == "In Progress"

    def test_linear_webhook_extracts_state(self) -> None:
        """LinearWebhookParser should extract state from payload."""
        parser = LinearWebhookParser()
        event = parser.parse({}, _linear_state_change_payload("lin-1", "Done"))
        issue_data = parser.extract_issue_event(event)
        assert issue_data["state"] == "Done"
        assert issue_data["id"] == "lin-1"


# ---------------------------------------------------------------------------
# Approval trigger flow tests
# ---------------------------------------------------------------------------


class TestApprovalTriggerFlow:
    """Tests for approval request/response lifecycle."""

    def test_approval_request_creates_pending(self) -> None:
        """Creating an approval request should add it to the pending list."""
        manager = ApprovalManager(slack_client=None)
        req = manager.create_request(
            title="Deploy to prod",
            description="Deploying v2.0",
            requester="agent-1",
            risk_level="high",
        )
        pending = manager.get_pending()
        assert len(pending) == 1
        assert pending[0].request_id == req.request_id

    def test_approval_response_resolves_request(self) -> None:
        """Handling an approved response should remove from pending."""
        manager = ApprovalManager(slack_client=None)
        req = manager.create_request(
            title="Run migration",
            description="DB migration v3",
            requester="agent-2",
        )
        manager.handle_response(
            request_id=req.request_id,
            approved=True,
            responder="admin",
        )
        assert manager.get_pending() == []
        assert manager.is_approved(req.request_id) is True

    def test_approval_denial_blocks_action(self) -> None:
        """A denied response should mark the request as not approved."""
        manager = ApprovalManager(slack_client=None)
        req = manager.create_request(
            title="Delete data",
            description="Purge old records",
            requester="agent-3",
            risk_level="critical",
        )
        manager.handle_response(
            request_id=req.request_id,
            approved=False,
            responder="admin",
        )
        assert manager.is_approved(req.request_id) is False


# ---------------------------------------------------------------------------
# Full integration flow tests
# ---------------------------------------------------------------------------


class TestFullIntegrationFlow:
    """End-to-end tests combining webhooks, triggers, sync, and approval."""

    def test_webhook_to_trigger_to_sync(self) -> None:
        """Full flow: parse webhook -> evaluate trigger -> sync state."""
        # 1. Parse GitHub webhook
        parser = GitHubWebhookParser()
        event = parser.parse(
            {"X-GitHub-Event": "issues"},
            _github_issue_labeled_payload("agent-task"),
        )

        # 2. Evaluate trigger
        engine = TriggerEngine(rules=[
            TriggerRule(
                name="spawn-on-label",
                condition=TriggerCondition(
                    source=WebhookSource.github,
                    event_type="issues.labeled",
                    filter={"label.name": "agent-task"},
                ),
                action=TriggerAction.spawn_run,
            )
        ])
        matches = engine.evaluate(event)
        assert len(matches) == 1
        assert matches[0].action == TriggerAction.spawn_run

        # 3. Create sync link and map state
        sync = SyncEngine()
        sync.link("gh-issue-42", "reins-task-1")
        reins_status = sync.map_state_inbound("Todo")
        assert reins_status == "pending"

        # 4. Record sync event
        sync_event = sync.create_sync_event(
            source="github",
            entity_id="gh-issue-42",
            old_state="",
            new_state="Todo",
            direction=SyncDirection.inbound,
        )
        assert sync_event.task_id == "reins-task-1"
        assert len(sync.get_sync_log()) == 1

    def test_multiple_triggers_from_single_event(self) -> None:
        """Multiple rules matching the same event should all be returned."""
        engine = TriggerEngine(rules=[
            TriggerRule(
                name="rule-1-spawn",
                condition=TriggerCondition(
                    source=WebhookSource.github,
                    event_type="issues.labeled",
                ),
                action=TriggerAction.spawn_run,
            ),
            TriggerRule(
                name="rule-2-notify",
                condition=TriggerCondition(
                    source=WebhookSource.github,
                    event_type="issues.labeled",
                ),
                action=TriggerAction.notify,
            ),
        ])

        parser = GitHubWebhookParser()
        event = parser.parse(
            {"X-GitHub-Event": "issues"},
            _github_issue_labeled_payload("agent-task"),
        )

        matches = engine.evaluate(event)
        assert len(matches) == 2
        actions = {m.action for m in matches}
        assert TriggerAction.spawn_run in actions
        assert TriggerAction.notify in actions

    def test_disabled_trigger_not_evaluated(self) -> None:
        """A disabled rule should not appear in evaluation results."""
        engine = TriggerEngine(rules=[
            TriggerRule(
                name="disabled-rule",
                condition=TriggerCondition(
                    source=WebhookSource.github,
                    event_type="issues.labeled",
                ),
                action=TriggerAction.spawn_run,
                enabled=False,
            ),
            TriggerRule(
                name="enabled-rule",
                condition=TriggerCondition(
                    source=WebhookSource.github,
                    event_type="issues.labeled",
                ),
                action=TriggerAction.notify,
                enabled=True,
            ),
        ])

        parser = GitHubWebhookParser()
        event = parser.parse(
            {"X-GitHub-Event": "issues"},
            _github_issue_labeled_payload("agent-task"),
        )

        matches = engine.evaluate(event)
        assert len(matches) == 1
        assert matches[0].name == "enabled-rule"
        assert all(m.name != "disabled-rule" for m in matches)
