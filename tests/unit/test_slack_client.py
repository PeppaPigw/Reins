from __future__ import annotations

from unittest.mock import patch

from reins.integrations.slack import SlackClient, SlackConfig


def test_send_message_posts_webhook_payload() -> None:
    client = SlackClient(
        SlackConfig(
            webhook_url="https://hooks.slack.test/services/abc",
            channel="#alerts",
            username="Reins Bot",
        )
    )

    with patch("reins.integrations.slack.request_text") as mock_request:
        mock_request.return_value = "ok"

        client.send_message(
            "Task started: Implement auth",
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "*Task Started*"}}],
        )

    payload = mock_request.call_args.kwargs["json_body"]
    assert payload["text"] == "Task started: Implement auth"
    assert payload["channel"] == "#alerts"
    assert payload["username"] == "Reins Bot"
    assert payload["blocks"][0]["type"] == "section"


def test_notify_task_created_formats_blocks() -> None:
    client = SlackClient(SlackConfig(webhook_url="https://hooks.slack.test/services/abc"))

    with patch.object(client, "send_message") as mock_send:
        client.notify_task_created("Implement auth", "peppa")

    assert mock_send.call_count == 1
    kwargs = mock_send.call_args.kwargs
    assert kwargs["text"] == "New task created: Implement auth"
    assert "*New Task Created*" in kwargs["blocks"][0]["text"]["text"]
    assert "*Developer:* peppa" in kwargs["blocks"][0]["text"]["text"]
