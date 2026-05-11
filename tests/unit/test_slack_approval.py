"""Tests for Slack Block Kit helpers, interactive approval messages, and routing."""

from __future__ import annotations

import time
from unittest.mock import patch

from reins.integrations.approval import (
    ApprovalManager,
    ApprovalStatus,
)
from reins.integrations.slack import (
    NotificationRouter,
    NotificationTemplate,
    SlackClient,
    SlackConfig,
    actions_block,
    button_element,
    context_block,
    divider_block,
    header_block,
    section_block,
)


# ---------------------------------------------------------------------------
# Block Kit helper tests
# ---------------------------------------------------------------------------


def test_header_block_format():
    result = header_block("Hello World")
    assert result == {
        "type": "header",
        "text": {"type": "plain_text", "text": "Hello World"},
    }


def test_section_block_format():
    result = section_block("*bold* text")
    assert result == {
        "type": "section",
        "text": {"type": "mrkdwn", "text": "*bold* text"},
    }


def test_button_element_format():
    result = button_element("Click Me", "btn_action", "val1")
    assert result == {
        "type": "button",
        "text": {"type": "plain_text", "text": "Click Me"},
        "action_id": "btn_action",
        "value": "val1",
    }


def test_button_element_with_style():
    result = button_element("Danger", "danger_action", "val2", style="danger")
    assert result["style"] == "danger"


def test_actions_block_format():
    btn = button_element("Go", "go_action", "go_val")
    result = actions_block([btn])
    assert result == {"type": "actions", "elements": [btn]}


def test_context_block_format():
    result = context_block(["*Author:* Alice", "*Time:* now"])
    assert result["type"] == "context"
    assert len(result["elements"]) == 2
    assert result["elements"][0] == {"type": "mrkdwn", "text": "*Author:* Alice"}


def test_divider_block_format():
    result = divider_block()
    assert result == {"type": "divider"}


# ---------------------------------------------------------------------------
# SlackClient rich messaging tests
# ---------------------------------------------------------------------------


@patch("reins.integrations.slack.request_text")
def test_send_rich_message(mock_request):
    config = SlackConfig(webhook_url="https://hooks.slack.com/test")
    client = SlackClient(config)

    blocks = [header_block("Title"), section_block("Body")]
    client.send_rich_message(blocks=blocks, text="fallback")

    mock_request.assert_called_once()
    call_kwargs = mock_request.call_args
    payload = call_kwargs.kwargs["json_body"] if "json_body" in call_kwargs.kwargs else call_kwargs[1]["json_body"]
    assert payload["blocks"] == blocks
    assert payload["text"] == "fallback"


@patch("reins.integrations.slack.request_text")
def test_send_approval_request_builds_blocks(mock_request):
    config = SlackConfig(webhook_url="https://hooks.slack.com/test")
    client = SlackClient(config)

    client.send_approval_request(
        request_id="apr-0001",
        title="Deploy to prod",
        description="Deploying v2.0",
        requester="alice",
        risk_level="high",
    )

    mock_request.assert_called_once()
    call_kwargs = mock_request.call_args
    payload = call_kwargs.kwargs.get("json_body") or call_kwargs[1].get("json_body")
    blocks = payload["blocks"]

    # Verify structure: header, section, context, divider, actions
    assert blocks[0]["type"] == "header"
    assert "Deploy to prod" in blocks[0]["text"]["text"]
    assert blocks[1]["type"] == "section"
    assert blocks[2]["type"] == "context"
    assert blocks[3]["type"] == "divider"
    assert blocks[4]["type"] == "actions"

    # Verify buttons
    elements = blocks[4]["elements"]
    assert len(elements) == 2
    assert elements[0]["text"]["text"] == "Approve"
    assert elements[0]["action_id"] == "approve_request"
    assert elements[0]["value"] == "apr-0001"
    assert elements[0]["style"] == "primary"
    assert elements[1]["text"]["text"] == "Deny"
    assert elements[1]["style"] == "danger"


# ---------------------------------------------------------------------------
# NotificationRouter tests
# ---------------------------------------------------------------------------


@patch("reins.integrations.slack.request_text")
def test_notification_router_finds_template(mock_request):
    config = SlackConfig(webhook_url="https://hooks.slack.com/test")
    client = SlackClient(config)
    tpl = NotificationTemplate(event_type="deploy", template="Deployed {version}")
    router = NotificationRouter(client, templates=[tpl])

    router.route("deploy", {"version": "1.2.3"})
    mock_request.assert_called_once()


@patch("reins.integrations.slack.request_text")
def test_notification_router_renders_variables(mock_request):
    config = SlackConfig(webhook_url="https://hooks.slack.com/test")
    client = SlackClient(config)
    tpl = NotificationTemplate(
        event_type="build",
        template="Build {status} for {project}",
    )
    router = NotificationRouter(client, templates=[tpl])

    router.route("build", {"status": "passed", "project": "reins"})

    call_kwargs = mock_request.call_args
    payload = call_kwargs.kwargs.get("json_body") or call_kwargs[1].get("json_body")
    assert "Build passed for reins" in payload["text"]


@patch("reins.integrations.slack.request_text")
def test_notification_router_no_match_is_noop(mock_request):
    config = SlackConfig(webhook_url="https://hooks.slack.com/test")
    client = SlackClient(config)
    router = NotificationRouter(client, templates=[])

    router.route("unknown_event", {"key": "val"})
    mock_request.assert_not_called()


# ---------------------------------------------------------------------------
# ApprovalManager tests
# ---------------------------------------------------------------------------


def test_approval_manager_create_request():
    manager = ApprovalManager()
    req = manager.create_request(
        title="Access DB",
        description="Need read access",
        requester="bob",
        risk_level="low",
    )

    assert req.request_id == "apr-0001"
    assert req.title == "Access DB"
    assert req.status == ApprovalStatus.pending
    assert req.requester == "bob"
    assert req.created_at  # non-empty ISO string


def test_approval_manager_handle_response_approve():
    manager = ApprovalManager()
    req = manager.create_request("T", "D", "alice")

    resp = manager.handle_response(req.request_id, approved=True, responder="carol")

    assert resp.approved is True
    assert resp.responder == "carol"
    assert req.status == ApprovalStatus.approved
    assert req.responded_at is not None


def test_approval_manager_handle_response_deny():
    manager = ApprovalManager()
    req = manager.create_request("T", "D", "alice")

    resp = manager.handle_response(
        req.request_id, approved=False, responder="dave", comment="Too risky"
    )

    assert resp.approved is False
    assert resp.comment == "Too risky"
    assert req.status == ApprovalStatus.denied


def test_approval_manager_get_pending():
    manager = ApprovalManager()
    manager.create_request("A", "desc", "u1")
    manager.create_request("B", "desc", "u2")
    req3 = manager.create_request("C", "desc", "u3")

    manager.handle_response(req3.request_id, approved=True, responder="admin")

    pending = manager.get_pending()
    assert len(pending) == 2
    assert all(r.status == ApprovalStatus.pending for r in pending)


def test_approval_manager_get_request():
    manager = ApprovalManager()
    req = manager.create_request("X", "desc", "user")

    found = manager.get_request(req.request_id)
    assert found is req

    assert manager.get_request("nonexistent") is None


def test_approval_manager_is_approved():
    manager = ApprovalManager()
    req = manager.create_request("T", "D", "u")

    assert manager.is_approved(req.request_id) is False
    manager.handle_response(req.request_id, approved=True, responder="admin")
    assert manager.is_approved(req.request_id) is True
    assert manager.is_approved("unknown") is False


def test_approval_manager_expire_old_requests():
    manager = ApprovalManager()
    req = manager.create_request("Old", "desc", "user")

    # Backdate the created_at to 2 hours ago
    old_time = time.gmtime(time.time() - 7200)
    req.created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", old_time)

    expired = manager.expire_old_requests(max_age_seconds=3600.0)

    assert req.request_id in expired
    assert req.status == ApprovalStatus.expired


def test_approval_status_transitions():
    """Verify that ApprovalStatus enum values are correct strings."""
    assert ApprovalStatus.pending == "pending"
    assert ApprovalStatus.approved == "approved"
    assert ApprovalStatus.denied == "denied"
    assert ApprovalStatus.expired == "expired"


@patch("reins.integrations.slack.request_text")
def test_approval_manager_sends_slack_notification(mock_request):
    config = SlackConfig(webhook_url="https://hooks.slack.com/test")
    client = SlackClient(config)
    manager = ApprovalManager(slack_client=client)

    manager.create_request("Deploy", "Deploy v3", "alice", risk_level="high")

    mock_request.assert_called_once()
    call_kwargs = mock_request.call_args
    payload = call_kwargs.kwargs.get("json_body") or call_kwargs[1].get("json_body")
    assert "Approval Required" in payload["blocks"][0]["text"]["text"]
