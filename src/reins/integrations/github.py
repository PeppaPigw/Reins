"""GitHub issue and pull request integration for task lifecycle hooks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from reins.integrations._http import request_json


@dataclass(frozen=True)
class GitHubConfig:
    """Configuration for GitHub issue synchronization."""

    token: str
    repo: str
    base_url: str = "https://api.github.com"


@dataclass(frozen=True)
class PullRequest:
    """Represents a GitHub pull request."""

    number: int
    title: str
    url: str
    head_branch: str
    base_branch: str
    state: str


@dataclass(frozen=True)
class StatusCheck:
    """Represents a commit status check."""

    context: str
    state: str  # pending, success, failure, error
    description: str
    target_url: str | None = None


class GitHubClient:
    """GitHub API client for issue tracking and pull requests."""

    def __init__(self, config: GitHubConfig):
        self.config = config
        self.headers = {
            "Authorization": f"Bearer {config.token}",
            "Accept": "application/vnd.github+json",
        }

    # --- Issue methods ---

    def create_issue(self, title: str, body: str, labels: list[str] | None = None) -> int:
        """Create a GitHub issue and return its number."""
        response = request_json(
            self._issues_url(),
            method="POST",
            headers=self.headers,
            json_body={
                "title": title,
                "body": body,
                "labels": labels or [],
            },
        )
        issue_number = _expect_issue_number(response)
        return issue_number

    def update_issue_labels(self, issue_number: int, labels: list[str]) -> None:
        """Replace the labels on an existing GitHub issue."""
        request_json(
            self._issue_url(issue_number),
            method="PATCH",
            headers=self.headers,
            json_body={"labels": labels},
        )

    def close_issue(self, issue_number: int) -> None:
        """Close an existing GitHub issue."""
        request_json(
            self._issue_url(issue_number),
            method="PATCH",
            headers=self.headers,
            json_body={"state": "closed"},
        )

    # --- Pull Request methods ---

    def create_pull_request(
        self,
        title: str,
        body: str,
        head: str,
        base: str = "main",
        labels: list[str] | None = None,
        draft: bool = False,
    ) -> PullRequest:
        """Create a pull request and return a PullRequest dataclass."""
        payload: dict[str, Any] = {
            "title": title,
            "body": body,
            "head": head,
            "base": base,
            "draft": draft,
        }
        response = request_json(
            self._pulls_url(),
            method="POST",
            headers=self.headers,
            json_body=payload,
        )
        pr = _parse_pull_request(response)
        if labels:
            request_json(
                f"{self.config.base_url}/repos/{self.config.repo}"
                f"/issues/{pr.number}/labels",
                method="POST",
                headers=self.headers,
                json_body={"labels": labels},
            )
        return pr

    def get_pull_request(self, pr_number: int) -> PullRequest:
        """Fetch a single pull request by number."""
        response = request_json(
            f"{self._pulls_url()}/{pr_number}",
            method="GET",
            headers=self.headers,
        )
        return _parse_pull_request(response)

    def list_pull_requests(
        self, state: str = "open", head: str | None = None
    ) -> list[PullRequest]:
        """List pull requests with optional filters."""
        url = f"{self._pulls_url()}?state={state}"
        if head:
            url += f"&head={self.config.repo.split('/')[0]}:{head}"
        response = request_json(url, method="GET", headers=self.headers)
        if not isinstance(response, list):
            return []
        return [_parse_pull_request(item) for item in response]

    def merge_pull_request(self, pr_number: int, merge_method: str = "squash") -> bool:
        """Merge a pull request. Returns True on success."""
        response = request_json(
            f"{self._pulls_url()}/{pr_number}/merge",
            method="PUT",
            headers=self.headers,
            json_body={"merge_method": merge_method},
        )
        return isinstance(response, dict) and response.get("merged", False)

    def request_review(self, pr_number: int, reviewers: list[str]) -> None:
        """Request reviews on a pull request."""
        request_json(
            f"{self._pulls_url()}/{pr_number}/requested_reviewers",
            method="POST",
            headers=self.headers,
            json_body={"reviewers": reviewers},
        )

    # --- Status Check methods ---

    def create_status(
        self,
        sha: str,
        state: str,
        context: str,
        description: str = "",
        target_url: str | None = None,
    ) -> None:
        """Create a commit status check."""
        payload: dict[str, Any] = {
            "state": state,
            "context": context,
            "description": description,
        }
        if target_url:
            payload["target_url"] = target_url
        request_json(
            f"{self.config.base_url}/repos/{self.config.repo}/statuses/{sha}",
            method="POST",
            headers=self.headers,
            json_body=payload,
        )

    # --- URL helpers ---

    def _issues_url(self) -> str:
        return f"{self.config.base_url}/repos/{self.config.repo}/issues"

    def _issue_url(self, issue_number: int) -> str:
        return f"{self._issues_url()}/{issue_number}"

    def _pulls_url(self) -> str:
        return f"{self.config.base_url}/repos/{self.config.repo}/pulls"


def _expect_issue_number(response: Any) -> int:
    if not isinstance(response, dict):
        raise RuntimeError("GitHub returned a non-object response")
    issue_number = response.get("number")
    if not isinstance(issue_number, int):
        raise RuntimeError("GitHub did not return an issue number")
    return issue_number


def _parse_pull_request(response: Any) -> PullRequest:
    """Parse a GitHub API pull request response into a PullRequest dataclass."""
    if not isinstance(response, dict):
        raise RuntimeError("GitHub returned a non-object response for pull request")
    return PullRequest(
        number=response["number"],
        title=response["title"],
        url=response.get("html_url", response.get("url", "")),
        head_branch=response.get("head", {}).get("ref", ""),
        base_branch=response.get("base", {}).get("ref", ""),
        state=response.get("state", "open"),
    )
