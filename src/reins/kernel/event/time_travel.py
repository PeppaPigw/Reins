"""Historical replay helpers for event-sourced run and task queries.

The APIs in this module stay read-only. They reconstruct historical views by
replaying journal events through the existing reducer and task projection.
"""

from __future__ import annotations

from typing import AsyncIterator

from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.event.journal import EventJournal, TimestampLike
from reins.kernel.event.task_events import (
    TASK_ARCHIVED,
    TASK_COMPLETED,
    TASK_CREATED,
    TASK_STARTED,
    TASK_UPDATED,
)
from reins.kernel.reducer.reducer import reduce
from reins.kernel.reducer.state import RunState
from reins.task.metadata import TaskMetadata
from reins.task.projection import TaskContext, TaskContextProjection

TASK_EVENT_TYPES = {
    TASK_CREATED,
    TASK_STARTED,
    TASK_COMPLETED,
    TASK_ARCHIVED,
    TASK_UPDATED,
}


class RunTimeTravel:
    """Reconstruct run and task history at a point in time."""

    def __init__(self, journal: EventJournal) -> None:
        self._journal = journal

    async def reconstruct_at(
        self,
        run_id: str,
        *,
        timestamp: TimestampLike,
    ) -> RunState:
        """Replay reducer state up to and including ``timestamp``."""
        return await self.reconstruct_run_state(run_id, timestamp=timestamp)

    async def reconstruct_run_state(
        self,
        run_id: str,
        *,
        timestamp: TimestampLike | None = None,
    ) -> RunState:
        """Replay the run reducer up to a cutoff timestamp."""
        state = RunState(run_id=run_id)
        async for event in self._iter_events(run_id, timestamp=timestamp):
            state = reduce(state, event)
        return state

    async def reconstruct_task_projection(
        self,
        run_id: str,
        *,
        timestamp: TimestampLike | None = None,
    ) -> TaskContextProjection:
        """Replay task events up to the cutoff timestamp into a fresh projection."""
        projection = TaskContextProjection()
        async for event in self._iter_events(run_id, timestamp=timestamp):
            if event.type in TASK_EVENT_TYPES:
                projection.apply_event(event)
        return projection

    async def query_tasks(
        self,
        run_id: str,
        *,
        timestamp: TimestampLike | None = None,
        include_archived: bool = True,
    ) -> list[TaskMetadata]:
        """Return task metadata as it existed at the cutoff timestamp."""
        projection = await self.reconstruct_task_projection(run_id, timestamp=timestamp)
        return projection.list_tasks(include_archived=include_archived)

    async def task_state_at(
        self,
        run_id: str,
        task_id: str,
        *,
        timestamp: TimestampLike | None = None,
    ) -> TaskContext | None:
        """Return a task context reconstructed at the cutoff timestamp."""
        projection = await self.reconstruct_task_projection(run_id, timestamp=timestamp)
        return projection.get_task_context(task_id)

    async def task_events_at(
        self,
        run_id: str,
        task_id: str,
        *,
        timestamp: TimestampLike | None = None,
    ) -> list[EventEnvelope]:
        """Return task-scoped events visible at the cutoff timestamp."""
        events: list[EventEnvelope] = []
        async for event in self._iter_events(run_id, timestamp=timestamp):
            if event.payload.get("task_id") == task_id:
                events.append(event)
        return events

    async def _iter_events(
        self,
        run_id: str,
        *,
        timestamp: TimestampLike | None = None,
    ) -> AsyncIterator[EventEnvelope]:
        if timestamp is None:
            async for event in self._journal.read_from(run_id):
                yield event
            return

        async for event in self._journal.read_until(run_id, timestamp=timestamp):
            yield event
