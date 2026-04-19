from __future__ import annotations

from unittest.mock import patch

from reins.integrations.jira import JiraClient, JiraConfig


def test_create_issue_posts_expected_adf_payload() -> None:
    client = JiraClient(
        JiraConfig(
            base_url="https://example.atlassian.net",
            email="user@example.com",
            api_token="token",
            project_key="ENG",
        )
    )

    with patch("reins.integrations.jira.request_json") as mock_request:
        mock_request.return_value = {"key": "ENG-42"}

        issue_key = client.create_issue("Implement auth", "Body text")

    assert issue_key == "ENG-42"
    payload = mock_request.call_args.kwargs["json_body"]
    assert payload["fields"]["project"] == {"key": "ENG"}
    assert payload["fields"]["summary"] == "Implement auth"
    assert payload["fields"]["issuetype"] == {"name": "Task"}
    paragraph = payload["fields"]["description"]["content"][0]["content"][0]["text"]
    assert paragraph == "Body text"


def test_transition_issue_fetches_transitions_and_posts_selected_transition() -> None:
    client = JiraClient(
        JiraConfig(
            base_url="https://example.atlassian.net",
            email="user@example.com",
            api_token="token",
            project_key="ENG",
        )
    )

    with patch("reins.integrations.jira.request_json") as mock_request:
        mock_request.side_effect = [
            {"transitions": [{"id": "11", "name": "In Progress"}, {"id": "21", "name": "Done"}]},
            {"ok": True},
        ]

        client.transition_issue("ENG-42", "Done")

    assert mock_request.call_count == 2
    assert mock_request.call_args_list[0].kwargs["method"] == "GET"
    assert mock_request.call_args_list[1].kwargs["method"] == "POST"
    assert mock_request.call_args_list[1].kwargs["json_body"] == {"transition": {"id": "21"}}


def test_transition_issue_noops_when_transition_missing(capsys) -> None:
    client = JiraClient(
        JiraConfig(
            base_url="https://example.atlassian.net",
            email="user@example.com",
            api_token="token",
            project_key="ENG",
        )
    )

    with patch("reins.integrations.jira.request_json") as mock_request:
        mock_request.return_value = {"transitions": [{"id": "11", "name": "In Progress"}]}

        client.transition_issue("ENG-42", "Done")

    assert mock_request.call_count == 1
    assert "Transition 'Done' not found" in capsys.readouterr().out
