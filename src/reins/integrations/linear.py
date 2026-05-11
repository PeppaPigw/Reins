"""Linear API integration for task lifecycle hooks."""

from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent
from typing import Any

from reins.integrations._http import request_json


@dataclass(frozen=True)
class LinearConfig:
    """Configuration required to talk to the Linear GraphQL API."""

    api_key: str
    team_id: str
    project_id: str | None = None
    base_url: str = "https://api.linear.app/graphql"
    todo_state_id: str | None = None
    in_progress_state_id: str | None = None
    done_state_id: str | None = None


class LinearClient:
    """Linear API client for issue tracking."""

    def __init__(self, config: LinearConfig):
        self.config = config
        self.base_url = config.base_url
        self.headers = {
            "Authorization": config.api_key,
            "Content-Type": "application/json",
        }
        self._state_cache: dict[str, str] | None = None

    def create_issue(self, title: str, description: str) -> str:
        """Create a Linear issue and return its canonical id."""
        input_payload: dict[str, Any] = {
            "title": title,
            "description": description,
            "teamId": self.config.team_id,
        }
        if self.config.project_id:
            input_payload["projectId"] = self.config.project_id

        data = self._graphql(
            """
            mutation IssueCreate($input: IssueCreateInput!) {
              issueCreate(input: $input) {
                success
                issue {
                  id
                  identifier
                  url
                }
              }
            }
            """,
            {"input": input_payload},
        )
        issue = data["issueCreate"]["issue"]
        issue_id = issue.get("id")
        if not isinstance(issue_id, str) or not issue_id:
            raise RuntimeError("Linear did not return an issue id")
        return issue_id

    def update_issue_status(self, issue_id: str, status: str) -> None:
        """Move an issue into the requested Linear workflow state."""
        data = self._graphql(
            """
            mutation IssueUpdate($id: String!, $input: IssueUpdateInput!) {
              issueUpdate(id: $id, input: $input) {
                success
                issue {
                  id
                }
              }
            }
            """,
            {
                "id": issue_id,
                "input": {"stateId": self._get_state_id(status)},
            },
        )
        if data["issueUpdate"].get("success") is not True:
            raise RuntimeError(f"Linear failed to update issue {issue_id}")

    def get_issue(self, issue_id: str) -> dict[str, Any]:
        """Query a Linear issue by ID and return its full data."""
        data = self._graphql(
            """
            query Issue($id: String!) {
              issue(id: $id) {
                id
                identifier
                title
                description
                url
                state {
                  id
                  name
                  type
                }
                labels {
                  nodes {
                    id
                    name
                  }
                }
              }
            }
            """,
            {"id": issue_id},
        )
        issue = data.get("issue")
        if not isinstance(issue, dict):
            raise RuntimeError(f"Linear issue '{issue_id}' not found")
        return issue

    def get_issue_state(self, issue_id: str) -> str:
        """Return the current workflow state name for an issue."""
        issue = self.get_issue(issue_id)
        state = issue.get("state")
        if isinstance(state, dict):
            return str(state.get("name", ""))
        return ""

    def list_team_states(self) -> list[dict[str, str]]:
        """Return all workflow states for the configured team."""
        data = self._graphql(
            """
            query TeamStates($id: String!) {
              team(id: $id) {
                states {
                  nodes {
                    id
                    name
                    type
                  }
                }
              }
            }
            """,
            {"id": self.config.team_id},
        )
        team = data.get("team")
        if not isinstance(team, dict):
            raise RuntimeError(f"Linear team '{self.config.team_id}' was not found")
        nodes = team.get("states", {}).get("nodes", [])
        return [
            {"id": n["id"], "name": n["name"], "type": n["type"]}
            for n in nodes
            if isinstance(n, dict)
        ]

    def sync_state_from_reins(self, issue_id: str, reins_status: str) -> None:
        """Map a Reins task status to a Linear state and update the issue.

        Mapping:
          planning/pending -> Todo
          in_progress     -> In Progress
          completed       -> Done
          blocked         -> Blocked
        """
        status_to_state: dict[str, str] = {
            "planning": "todo",
            "pending": "todo",
            "in_progress": "in_progress",
            "completed": "done",
            "blocked": "blocked",
        }
        normalized = _normalize_status(reins_status)
        linear_status = status_to_state.get(normalized, normalized)
        self.update_issue_status(issue_id, linear_status)

    def get_issues_by_label(self, label: str) -> list[dict[str, Any]]:
        """Query issues with a specific label (for finding agent-managed issues)."""
        data = self._graphql(
            """
            query IssuesByLabel($filter: IssueFilter) {
              issues(filter: $filter) {
                nodes {
                  id
                  identifier
                  title
                  url
                  state {
                    id
                    name
                    type
                  }
                }
              }
            }
            """,
            {"filter": {"labels": {"name": {"eq": label}}}},
        )
        issues = data.get("issues", {})
        nodes = issues.get("nodes", []) if isinstance(issues, dict) else []
        return [n for n in nodes if isinstance(n, dict)]

    def _get_state_id(self, status: str) -> str:
        """Resolve a friendly status name into a Linear workflow state id."""
        explicit_ids = {
            "todo": self.config.todo_state_id,
            "in_progress": self.config.in_progress_state_id,
            "done": self.config.done_state_id,
        }
        normalized = _normalize_status(status)
        if explicit_ids.get(normalized):
            return str(explicit_ids[normalized])

        if self._state_cache is None:
            self._state_cache = self._load_team_states()

        aliases = {
            "todo": ("todo", "backlog", "triage", "unstarted"),
            "in_progress": ("in_progress", "in progress", "started"),
            "done": ("done", "completed", "canceled", "cancelled"),
        }
        for alias in aliases.get(normalized, (normalized,)):
            state_id = self._state_cache.get(_normalize_status(alias))
            if state_id:
                return state_id

        raise RuntimeError(
            f"Could not resolve Linear state for status '{status}'. "
            "Set LINEAR_TODO_STATE_ID, LINEAR_IN_PROGRESS_STATE_ID, or "
            "LINEAR_DONE_STATE_ID to override state lookup."
        )

    def _load_team_states(self) -> dict[str, str]:
        data = self._graphql(
            """
            query TeamStates($id: String!) {
              team(id: $id) {
                states {
                  nodes {
                    id
                    name
                    type
                  }
                }
              }
            }
            """,
            {"id": self.config.team_id},
        )
        team = data.get("team")
        if not isinstance(team, dict):
            raise RuntimeError(f"Linear team '{self.config.team_id}' was not found")

        raw_states = team.get("states", {})
        nodes = raw_states.get("nodes", raw_states) if isinstance(raw_states, dict) else raw_states
        if not isinstance(nodes, list):
            raise RuntimeError("Linear returned an unexpected workflow state payload")

        state_cache: dict[str, str] = {}
        for node in nodes:
            if not isinstance(node, dict):
                continue
            state_id = node.get("id")
            if not isinstance(state_id, str) or not state_id:
                continue
            for field in ("name", "type"):
                value = node.get(field)
                if isinstance(value, str) and value.strip():
                    state_cache.setdefault(_normalize_status(value), state_id)
        return state_cache

    def _graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        response = request_json(
            self.base_url,
            method="POST",
            headers=self.headers,
            json_body={
                "query": dedent(query).strip(),
                "variables": variables or {},
            },
        )
        if not isinstance(response, dict):
            raise RuntimeError("Linear returned a non-object GraphQL response")

        errors = response.get("errors")
        if isinstance(errors, list) and errors:
            messages = []
            for error in errors:
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    messages.append(error["message"])
                else:
                    messages.append(str(error))
            raise RuntimeError("Linear GraphQL error: " + "; ".join(messages))

        data = response.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("Linear GraphQL response did not contain data")
        return data


def _normalize_status(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")
