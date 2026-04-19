from __future__ import annotations

from unittest.mock import patch

from reins.integrations.github import GitHubClient, GitHubConfig


def test_create_issue_posts_expected_payload() -> None:
    client = GitHubClient(GitHubConfig(token="token", repo="owner/repo"))

    with patch("reins.integrations.github.request_json") as mock_request:
        mock_request.return_value = {"number": 42}

        issue_number = client.create_issue("Implement auth", "Body", labels=["reins-task"])

    assert issue_number == 42
    assert mock_request.call_args.kwargs["method"] == "POST"
    assert mock_request.call_args.kwargs["json_body"] == {
        "title": "Implement auth",
        "body": "Body",
        "labels": ["reins-task"],
    }
    assert mock_request.call_args.kwargs["headers"]["Authorization"] == "Bearer token"


def test_update_issue_labels_patches_issue() -> None:
    client = GitHubClient(GitHubConfig(token="token", repo="owner/repo"))

    with patch("reins.integrations.github.request_json") as mock_request:
        mock_request.return_value = {"number": 42}

        client.update_issue_labels(42, ["reins-task", "in-progress"])

    assert mock_request.call_args.kwargs["method"] == "PATCH"
    assert mock_request.call_args.kwargs["json_body"] == {
        "labels": ["reins-task", "in-progress"],
    }


def test_close_issue_patches_closed_state() -> None:
    client = GitHubClient(GitHubConfig(token="token", repo="owner/repo"))

    with patch("reins.integrations.github.request_json") as mock_request:
        mock_request.return_value = {"number": 42}

        client.close_issue(42)

    assert mock_request.call_args.kwargs["method"] == "PATCH"
    assert mock_request.call_args.kwargs["json_body"] == {"state": "closed"}
