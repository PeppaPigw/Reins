"""Tests for GitHub PR creation, status checks, and review requests."""

from __future__ import annotations

from unittest.mock import patch

from reins.integrations.github import (
    GitHubClient,
    GitHubConfig,
    PullRequest,
    StatusCheck,
)

_CONFIG = GitHubConfig(token="ghp_test123", repo="owner/repo")


def _make_pr_response(
    number: int = 42,
    title: str = "feat: add feature",
    state: str = "open",
    head_ref: str = "feature-branch",
    base_ref: str = "main",
) -> dict:
    return {
        "number": number,
        "title": title,
        "html_url": f"https://github.com/owner/repo/pull/{number}",
        "state": state,
        "head": {"ref": head_ref},
        "base": {"ref": base_ref},
    }


class TestPullRequestDataclass:
    def test_pull_request_dataclass_fields(self):
        pr = PullRequest(
            number=1,
            title="Test PR",
            url="https://github.com/owner/repo/pull/1",
            head_branch="feature",
            base_branch="main",
            state="open",
        )
        assert pr.number == 1
        assert pr.title == "Test PR"
        assert pr.url == "https://github.com/owner/repo/pull/1"
        assert pr.head_branch == "feature"
        assert pr.base_branch == "main"
        assert pr.state == "open"

    def test_status_check_dataclass_fields(self):
        sc = StatusCheck(
            context="ci/build",
            state="success",
            description="Build passed",
            target_url="https://ci.example.com/build/1",
        )
        assert sc.context == "ci/build"
        assert sc.state == "success"
        assert sc.description == "Build passed"
        assert sc.target_url == "https://ci.example.com/build/1"

    def test_status_check_default_target_url(self):
        sc = StatusCheck(context="ci/lint", state="pending", description="Running")
        assert sc.target_url is None


class TestCreatePullRequest:
    @patch("reins.integrations.github.request_json")
    def test_create_pull_request_builds_correct_payload(self, mock_req):
        mock_req.return_value = _make_pr_response()
        client = GitHubClient(_CONFIG)
        client.create_pull_request(
            title="feat: add feature",
            body="Description here",
            head="feature-branch",
            base="main",
        )
        call_args = mock_req.call_args_list[0]
        assert call_args[0][0] == "https://api.github.com/repos/owner/repo/pulls"
        payload = call_args[1]["json_body"]
        assert payload["title"] == "feat: add feature"
        assert payload["body"] == "Description here"
        assert payload["head"] == "feature-branch"
        assert payload["base"] == "main"
        assert payload["draft"] is False

    @patch("reins.integrations.github.request_json")
    def test_create_pull_request_returns_pr_dataclass(self, mock_req):
        mock_req.return_value = _make_pr_response(number=99, title="My PR")
        client = GitHubClient(_CONFIG)
        pr = client.create_pull_request(
            title="My PR", body="body", head="branch"
        )
        assert isinstance(pr, PullRequest)
        assert pr.number == 99
        assert pr.title == "My PR"
        assert pr.head_branch == "feature-branch"
        assert pr.state == "open"

    @patch("reins.integrations.github.request_json")
    def test_create_pull_request_with_labels_and_draft(self, mock_req):
        mock_req.return_value = _make_pr_response(number=10)
        client = GitHubClient(_CONFIG)
        pr = client.create_pull_request(
            title="Draft PR",
            body="WIP",
            head="wip-branch",
            labels=["enhancement", "wip"],
            draft=True,
        )
        # First call creates the PR
        create_call = mock_req.call_args_list[0]
        assert create_call[1]["json_body"]["draft"] is True
        # Second call adds labels
        label_call = mock_req.call_args_list[1]
        assert "/issues/10/labels" in label_call[0][0]
        assert label_call[1]["json_body"]["labels"] == ["enhancement", "wip"]
        assert pr.number == 10


class TestMergePullRequest:
    @patch("reins.integrations.github.request_json")
    def test_merge_pull_request_uses_squash_default(self, mock_req):
        mock_req.return_value = {"merged": True}
        client = GitHubClient(_CONFIG)
        result = client.merge_pull_request(42)
        call_args = mock_req.call_args
        assert "/pulls/42/merge" in call_args[0][0]
        assert call_args[1]["json_body"]["merge_method"] == "squash"
        assert result is True


class TestCreateStatus:
    @patch("reins.integrations.github.request_json")
    def test_create_status_sends_correct_state(self, mock_req):
        mock_req.return_value = {}
        client = GitHubClient(_CONFIG)
        client.create_status(
            sha="abc123",
            state="success",
            context="ci/tests",
            description="All tests passed",
            target_url="https://ci.example.com/1",
        )
        call_args = mock_req.call_args
        assert "/statuses/abc123" in call_args[0][0]
        payload = call_args[1]["json_body"]
        assert payload["state"] == "success"
        assert payload["context"] == "ci/tests"
        assert payload["description"] == "All tests passed"
        assert payload["target_url"] == "https://ci.example.com/1"


class TestGetPullRequest:
    @patch("reins.integrations.github.request_json")
    def test_get_pull_request_parses_response(self, mock_req):
        mock_req.return_value = _make_pr_response(
            number=7, title="Fix bug", state="closed", head_ref="fix/bug"
        )
        client = GitHubClient(_CONFIG)
        pr = client.get_pull_request(7)
        assert pr.number == 7
        assert pr.title == "Fix bug"
        assert pr.state == "closed"
        assert pr.head_branch == "fix/bug"


class TestListPullRequests:
    @patch("reins.integrations.github.request_json")
    def test_list_pull_requests_with_filters(self, mock_req):
        mock_req.return_value = [
            _make_pr_response(number=1, head_ref="feat-a"),
            _make_pr_response(number=2, head_ref="feat-b"),
        ]
        client = GitHubClient(_CONFIG)
        prs = client.list_pull_requests(state="open", head="feat-a")
        call_url = mock_req.call_args[0][0]
        assert "state=open" in call_url
        assert "head=owner:feat-a" in call_url
        assert len(prs) == 2
        assert prs[0].number == 1


class TestRequestReview:
    @patch("reins.integrations.github.request_json")
    def test_request_review_sends_reviewers(self, mock_req):
        mock_req.return_value = {}
        client = GitHubClient(_CONFIG)
        client.request_review(42, reviewers=["alice", "bob"])
        call_args = mock_req.call_args
        assert "/pulls/42/requested_reviewers" in call_args[0][0]
        assert call_args[1]["json_body"]["reviewers"] == ["alice", "bob"]
