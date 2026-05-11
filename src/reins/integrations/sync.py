"""Bidirectional sync engine for external issue trackers.

Maps state between external services (Linear, GitHub) and Reins task statuses,
tracks entity links, and logs sync events for auditability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class SyncDirection(str, Enum):
    """Direction of a state synchronization."""

    inbound = "inbound"
    outbound = "outbound"
    bidirectional = "bidirectional"


@dataclass(frozen=True)
class StateMapping:
    """Maps an external state name to a Reins task status."""

    external_state: str
    reins_status: str
    direction: SyncDirection


@dataclass
class SyncEvent:
    """Record of a single synchronization action."""

    source: str
    entity_id: str
    task_id: str | None
    old_state: str
    new_state: str
    direction: SyncDirection
    timestamp: str
    applied: bool = False


# ---------------------------------------------------------------------------
# Default state mappings (Linear <-> Reins)
# ---------------------------------------------------------------------------

DEFAULT_MAPPINGS: list[StateMapping] = [
    StateMapping("Todo", "pending", SyncDirection.bidirectional),
    StateMapping("In Progress", "in_progress", SyncDirection.bidirectional),
    StateMapping("Done", "completed", SyncDirection.bidirectional),
    StateMapping("Blocked", "blocked", SyncDirection.bidirectional),
    StateMapping("Backlog", "pending", SyncDirection.inbound),
    StateMapping("Cancelled", "archived", SyncDirection.inbound),
]


# ---------------------------------------------------------------------------
# Sync engine
# ---------------------------------------------------------------------------


class SyncEngine:
    """Bidirectional sync engine for external issue trackers.

    Manages entity links between external services and Reins tasks,
    maps states in both directions, and maintains an audit log of sync events.
    """

    def __init__(self, state_mappings: list[StateMapping] | None = None):
        self._mappings: list[StateMapping] = state_mappings or list(DEFAULT_MAPPINGS)
        self._sync_log: list[SyncEvent] = []
        self._linked_entities: dict[str, str] = {}  # external_id -> task_id

    def link(self, external_id: str, task_id: str) -> None:
        """Create a bidirectional link between an external entity and a Reins task."""
        self._linked_entities[external_id] = task_id

    def unlink(self, external_id: str) -> None:
        """Remove the link for an external entity."""
        self._linked_entities.pop(external_id, None)

    def get_task_for_entity(self, external_id: str) -> str | None:
        """Return the Reins task_id linked to an external entity, or None."""
        return self._linked_entities.get(external_id)

    def get_entity_for_task(self, task_id: str) -> str | None:
        """Return the external entity_id linked to a Reins task, or None."""
        for ext_id, tid in self._linked_entities.items():
            if tid == task_id:
                return ext_id
        return None

    def map_state_inbound(self, external_state: str) -> str | None:
        """Map an external state to a Reins task status.

        Only considers mappings with direction inbound or bidirectional.
        """
        for mapping in self._mappings:
            if mapping.external_state == external_state and mapping.direction in (
                SyncDirection.inbound,
                SyncDirection.bidirectional,
            ):
                return mapping.reins_status
        return None

    def map_state_outbound(self, reins_status: str) -> str | None:
        """Map a Reins task status to an external state.

        Only considers mappings with direction outbound or bidirectional.
        """
        for mapping in self._mappings:
            if mapping.reins_status == reins_status and mapping.direction in (
                SyncDirection.outbound,
                SyncDirection.bidirectional,
            ):
                return mapping.external_state
        return None

    def record_sync(self, event: SyncEvent) -> None:
        """Log a sync event to the audit trail."""
        self._sync_log.append(event)

    def get_sync_log(self) -> list[SyncEvent]:
        """Return the full sync event history."""
        return list(self._sync_log)

    def should_sync(self, direction: SyncDirection, external_state: str) -> bool:
        """Check if a state change should be synced based on configured mappings.

        Returns True if any mapping matches the external_state and allows
        the given direction.
        """
        for mapping in self._mappings:
            if mapping.external_state != external_state:
                continue
            if mapping.direction == SyncDirection.bidirectional:
                return True
            if mapping.direction == direction:
                return True
        return False

    def create_sync_event(
        self,
        source: str,
        entity_id: str,
        old_state: str,
        new_state: str,
        direction: SyncDirection,
    ) -> SyncEvent:
        """Create and record a SyncEvent, resolving the linked task_id."""
        event = SyncEvent(
            source=source,
            entity_id=entity_id,
            task_id=self.get_task_for_entity(entity_id),
            old_state=old_state,
            new_state=new_state,
            direction=direction,
            timestamp=datetime.now(UTC).isoformat(),
            applied=False,
        )
        self.record_sync(event)
        return event
