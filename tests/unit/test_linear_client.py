from __future__ import annotations

from unittest.mock import patch

import pytest

from reins.integrations.linear import LinearClient, LinearConfig


def test_create_issue_posts_issue_create_mutation() -> None:
    client = LinearClient(LinearConfig(api_key="token", team_id="team-1", project_id="proj-1"))

    with patch("reins.integrations.linear.request_json") as mock_request:
        mock_request.return_value = {
            "data": {
                "issueCreate": {
                    "success": True,
                    "issue": {"id": "lin_123", "identifier": "LIN-123", "url": "https://linear.app"},
                }
            }
        }

        issue_id = client.create_issue("Fix login", "Detailed body")

    assert issue_id == "lin_123"
    assert mock_request.call_count == 1
    payload = mock_request.call_args.kwargs["json_body"]
    assert "issueCreate" in payload["query"]
    assert payload["variables"]["input"] == {
        "title": "Fix login",
        "description": "Detailed body",
        "teamId": "team-1",
        "projectId": "proj-1",
    }


def test_update_issue_status_uses_explicit_state_ids_when_configured() -> None:
    client = LinearClient(
        LinearConfig(
            api_key="token",
            team_id="team-1",
            todo_state_id="todo-id",
            in_progress_state_id="started-id",
            done_state_id="done-id",
        )
    )

    with patch("reins.integrations.linear.request_json") as mock_request:
        mock_request.return_value = {"data": {"issueUpdate": {"success": True, "issue": {"id": "lin_123"}}}}

        client.update_issue_status("lin_123", "in_progress")

    payload = mock_request.call_args.kwargs["json_body"]
    assert "issueUpdate" in payload["query"]
    assert payload["variables"] == {
        "id": "lin_123",
        "input": {"stateId": "started-id"},
    }


def test_update_issue_status_queries_team_states_when_not_configured() -> None:
    client = LinearClient(LinearConfig(api_key="token", team_id="team-1"))

    with patch("reins.integrations.linear.request_json") as mock_request:
        mock_request.side_effect = [
            {
                "data": {
                    "team": {
                        "states": {
                            "nodes": [
                                {"id": "todo-id", "name": "Todo", "type": "unstarted"},
                                {"id": "started-id", "name": "In Progress", "type": "started"},
                                {"id": "done-id", "name": "Done", "type": "completed"},
                            ]
                        }
                    }
                }
            },
            {"data": {"issueUpdate": {"success": True, "issue": {"id": "lin_123"}}}},
        ]

        client.update_issue_status("lin_123", "done")

    assert mock_request.call_count == 2
    state_query = mock_request.call_args_list[0].kwargs["json_body"]
    update_query = mock_request.call_args_list[1].kwargs["json_body"]
    assert "TeamStates" in state_query["query"]
    assert update_query["variables"]["input"]["stateId"] == "done-id"


def test_graphql_raises_on_errors() -> None:
    client = LinearClient(LinearConfig(api_key="token", team_id="team-1"))

    with patch("reins.integrations.linear.request_json") as mock_request:
        mock_request.return_value = {
            "errors": [{"message": "Bad request"}],
            "data": None,
        }

        with pytest.raises(RuntimeError, match="Linear GraphQL error: Bad request"):
            client.create_issue("Fix login", "Detailed body")
