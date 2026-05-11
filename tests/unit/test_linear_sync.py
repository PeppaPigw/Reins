"""Unit tests for Linear bidirectional sync and SyncEngine."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from reins.integrations.linear import LinearClient, LinearConfig
from reins.integrations.sync import (
    DEFAULT_MAPPINGS,
    StateMapping,
    SyncDirection,
    SyncEngine,
    SyncEvent,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def linear_config() -> LinearConfig:
    return LinearConfig(
        api_key="lin_test_key",
        team_id="team-123",
        project_id="proj-456",
    )


@pytest.fixture
def linear_client(linear_config: LinearConfig) -> LinearClient:
    return LinearClient(linear_config)


@pytest.fixture
def sync_engine() -> SyncEngine:
    return SyncEngine()


# ---------------------------------------------------------------------------
# LinearClient sync tests
# ---------------------------------------------------------------------------


class TestLinearClientSync:
    """Tests for LinearClient sync methods."""

    def test_get_issue_state_returns_state(self, linear_client: LinearClient) -> None:
        mock_response = {
            "data": {
                "issue": {
                    "id": "issue-1",
                    "identifier": "ENG-42",
                    "title": "Test issue",
                    "description": "",
                    "url": "https://linear.app/team/ENG-42",
                    "state": {"id": "state-1", "name": "In Progress", "type": "started"},
                    "labels": {"nodes": []},
                }
            }
        }
        with patch(
            "reins.integrations.linear.request_json", return_value=mock_response
        ):
            state = linear_client.get_issue_state("issue-1")
        assert state == "In Progress"

    def test_sync_state_from_reins_maps_correctly(
        self, linear_client: LinearClient
    ) -> None:
        """sync_state_from_reins should call update_issue_status with mapped state."""
        with patch.object(linear_client, "update_issue_status") as mock_update:
            linear_client.sync_state_from_reins("issue-1", "in_progress")
            mock_update.assert_called_once_with("issue-1", "in_progress")

    def test_sync_state_from_reins_maps_pending_to_todo(
        self, linear_client: LinearClient
    ) -> None:
        with patch.object(linear_client, "update_issue_status") as mock_update:
            linear_client.sync_state_from_reins("issue-1", "pending")
            mock_update.assert_called_once_with("issue-1", "todo")

    def test_sync_state_from_reins_maps_completed_to_done(
        self, linear_client: LinearClient
    ) -> None:
        with patch.object(linear_client, "update_issue_status") as mock_update:
            linear_client.sync_state_from_reins("issue-1", "completed")
            mock_update.assert_called_once_with("issue-1", "done")

    def test_get_issues_by_label(self, linear_client: LinearClient) -> None:
        mock_response = {
            "data": {
                "issues": {
                    "nodes": [
                        {
                            "id": "issue-1",
                            "identifier": "ENG-10",
                            "title": "Agent task",
                            "url": "https://linear.app/team/ENG-10",
                            "state": {"id": "s1", "name": "Todo", "type": "unstarted"},
                        }
                    ]
                }
            }
        }
        with patch(
            "reins.integrations.linear.request_json", return_value=mock_response
        ):
            issues = linear_client.get_issues_by_label("agent-managed")
        assert len(issues) == 1
        assert issues[0]["identifier"] == "ENG-10"


# ---------------------------------------------------------------------------
# SyncEngine tests
# ---------------------------------------------------------------------------


class TestSyncEngine:
    """Tests for the bidirectional SyncEngine."""

    def test_link_entities(self, sync_engine: SyncEngine) -> None:
        sync_engine.link("linear-123", "task-abc")
        assert sync_engine.get_task_for_entity("linear-123") == "task-abc"

    def test_unlink(self, sync_engine: SyncEngine) -> None:
        sync_engine.link("linear-123", "task-abc")
        sync_engine.unlink("linear-123")
        assert sync_engine.get_task_for_entity("linear-123") is None

    def test_get_task_for_entity_unknown(self, sync_engine: SyncEngine) -> None:
        assert sync_engine.get_task_for_entity("nonexistent") is None

    def test_get_entity_for_task(self, sync_engine: SyncEngine) -> None:
        sync_engine.link("linear-123", "task-abc")
        assert sync_engine.get_entity_for_task("task-abc") == "linear-123"

    def test_get_entity_for_task_unknown(self, sync_engine: SyncEngine) -> None:
        assert sync_engine.get_entity_for_task("nonexistent") is None

    def test_map_state_inbound(self, sync_engine: SyncEngine) -> None:
        assert sync_engine.map_state_inbound("In Progress") == "in_progress"
        assert sync_engine.map_state_inbound("Todo") == "pending"
        assert sync_engine.map_state_inbound("Done") == "completed"
        assert sync_engine.map_state_inbound("Blocked") == "blocked"

    def test_map_state_outbound(self, sync_engine: SyncEngine) -> None:
        assert sync_engine.map_state_outbound("in_progress") == "In Progress"
        assert sync_engine.map_state_outbound("pending") == "Todo"
        assert sync_engine.map_state_outbound("completed") == "Done"
        assert sync_engine.map_state_outbound("blocked") == "Blocked"

    def test_map_state_inbound_unknown(self, sync_engine: SyncEngine) -> None:
        assert sync_engine.map_state_inbound("NonexistentState") is None

    def test_map_state_outbound_unknown(self, sync_engine: SyncEngine) -> None:
        assert sync_engine.map_state_outbound("nonexistent_status") is None

    def test_record_sync_event(self, sync_engine: SyncEngine) -> None:
        event = SyncEvent(
            source="linear",
            entity_id="issue-1",
            task_id="task-1",
            old_state="Todo",
            new_state="In Progress",
            direction=SyncDirection.inbound,
            timestamp="2024-01-01T00:00:00Z",
        )
        sync_engine.record_sync(event)
        log = sync_engine.get_sync_log()
        assert len(log) == 1
        assert log[0].source == "linear"
        assert log[0].new_state == "In Progress"

    def test_should_sync_respects_direction(self) -> None:
        engine = SyncEngine(
            state_mappings=[
                StateMapping("Open", "pending", SyncDirection.inbound),
            ]
        )
        # Inbound should sync
        assert engine.should_sync(SyncDirection.inbound, "Open") is True
        # Outbound should not sync (mapping is inbound-only)
        assert engine.should_sync(SyncDirection.outbound, "Open") is False

    def test_should_sync_bidirectional_allows_both(self, sync_engine: SyncEngine) -> None:
        assert sync_engine.should_sync(SyncDirection.inbound, "In Progress") is True
        assert sync_engine.should_sync(SyncDirection.outbound, "In Progress") is True

    def test_default_mappings_cover_all_states(self) -> None:
        """DEFAULT_MAPPINGS should cover the core Linear states."""
        external_states = {m.external_state for m in DEFAULT_MAPPINGS}
        assert "Todo" in external_states
        assert "In Progress" in external_states
        assert "Done" in external_states
        assert "Blocked" in external_states

    def test_bidirectional_sync_flow(self, sync_engine: SyncEngine) -> None:
        """Full bidirectional flow: link, map inbound, map outbound, record."""
        # Link entities
        sync_engine.link("linear-issue-42", "reins-task-7")

        # Inbound: Linear "In Progress" -> Reins "in_progress"
        inbound_status = sync_engine.map_state_inbound("In Progress")
        assert inbound_status == "in_progress"

        # Outbound: Reins "completed" -> Linear "Done"
        outbound_state = sync_engine.map_state_outbound("completed")
        assert outbound_state == "Done"

        # Record the sync event
        event = sync_engine.create_sync_event(
            source="linear",
            entity_id="linear-issue-42",
            old_state="In Progress",
            new_state="Done",
            direction=SyncDirection.outbound,
        )
        assert event.task_id == "reins-task-7"
        assert event.applied is False

        log = sync_engine.get_sync_log()
        assert len(log) == 1

    def test_custom_state_mappings(self) -> None:
        """SyncEngine should accept custom state mappings."""
        custom = [
            StateMapping("Open", "pending", SyncDirection.bidirectional),
            StateMapping("Closed", "completed", SyncDirection.bidirectional),
        ]
        engine = SyncEngine(state_mappings=custom)
        assert engine.map_state_inbound("Open") == "pending"
        assert engine.map_state_outbound("completed") == "Closed"
        # Default mappings should not be present
        assert engine.map_state_inbound("In Progress") is None
