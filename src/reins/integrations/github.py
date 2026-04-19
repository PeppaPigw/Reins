"""GitHub issue integration for task lifecycle hooks."""

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


class GitHubClient:
    """GitHub API client for issue tracking."""

    def __init__(self, config: GitHubConfig):
        self.config = config
        self.headers = {
            "Authorization": f"Bearer {config.token}",
            "Accept": "application/vnd.github+json",
        }

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

    def _issues_url(self) -> str:
        return f"{self.config.base_url}/repos/{self.config.repo}/issues"

    def _issue_url(self, issue_number: int) -> str:
        return f"{self._issues_url()}/{issue_number}"


def _expect_issue_number(response: Any) -> int:
    if not isinstance(response, dict):
        raise RuntimeError("GitHub returned a non-object response")
    issue_number = response.get("number")
    if not isinstance(issue_number, int):
        raise RuntimeError("GitHub did not return an issue number")
    return issue_number
