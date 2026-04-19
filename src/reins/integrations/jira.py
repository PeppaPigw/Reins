"""Jira issue integration template for task lifecycle hooks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from reins.integrations._http import basic_auth_header, request_json


@dataclass(frozen=True)
class JiraConfig:
    """Configuration for Jira Cloud issue synchronization."""

    base_url: str
    email: str
    api_token: str
    project_key: str


class JiraClient:
    """Jira API client for issue tracking."""

    def __init__(self, config: JiraConfig):
        self.config = config
        self.headers = {
            "Authorization": basic_auth_header(config.email, config.api_token),
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def create_issue(self, summary: str, description: str, issue_type: str = "Task") -> str:
        """Create a Jira issue and return its key."""
        response = request_json(
            f"{self.config.base_url}/rest/api/3/issue",
            method="POST",
            headers=self.headers,
            json_body={
                "fields": {
                    "project": {"key": self.config.project_key},
                    "summary": summary,
                    "description": _adf_paragraph(description),
                    "issuetype": {"name": issue_type},
                }
            },
        )
        issue_key = _expect_issue_key(response)
        return issue_key

    def transition_issue(self, issue_key: str, transition_name: str) -> None:
        """Transition a Jira issue if the named workflow transition exists."""
        url = f"{self.config.base_url}/rest/api/3/issue/{issue_key}/transitions"
        response = request_json(
            url,
            method="GET",
            headers=self.headers,
        )
        transitions = response.get("transitions") if isinstance(response, dict) else None
        if not isinstance(transitions, list):
            raise RuntimeError("Jira did not return a transitions list")

        transition_id: str | None = None
        for transition in transitions:
            if not isinstance(transition, dict):
                continue
            name = transition.get("name")
            if isinstance(name, str) and name.lower() == transition_name.lower():
                candidate = transition.get("id")
                if isinstance(candidate, str) and candidate:
                    transition_id = candidate
                    break

        if transition_id is None:
            print(f"Transition '{transition_name}' not found")
            return

        request_json(
            url,
            method="POST",
            headers=self.headers,
            json_body={"transition": {"id": transition_id}},
        )


def _adf_paragraph(text: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


def _expect_issue_key(response: Any) -> str:
    if not isinstance(response, dict):
        raise RuntimeError("Jira returned a non-object response")
    issue_key = response.get("key")
    if not isinstance(issue_key, str) or not issue_key:
        raise RuntimeError("Jira did not return an issue key")
    return issue_key
