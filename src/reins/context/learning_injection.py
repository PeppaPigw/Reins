"""Learning injection into agent context.

Queries relevant past learnings and formats them for injection
into future agent context compilation.
"""

from __future__ import annotations

from reins.workflow.retrospective import Learning, RetrospectiveStore


class LearningInjector:
    """Injects relevant past learnings into agent context."""

    def __init__(self, store: RetrospectiveStore, max_learnings: int = 5) -> None:
        self._store = store
        self._max_learnings = max_learnings

    def inject_for_task(
        self, task_type: str | None = None, file_pattern: str | None = None
    ) -> str:
        """Query relevant learnings and format for context injection.

        Returns empty string if no relevant learnings found.
        """
        learnings = self.get_relevant_learnings(task_type, file_pattern)
        if not learnings:
            return ""
        return self._store.format_learnings_for_context(learnings)

    def inject_as_xml(
        self, task_type: str | None = None, file_pattern: str | None = None
    ) -> str:
        """Wrap learnings in <past-learnings> tags for structured injection."""
        content = self.inject_for_task(task_type, file_pattern)
        if not content:
            return ""
        return f"<past-learnings>\n{content}\n</past-learnings>"

    def get_relevant_learnings(
        self, task_type: str | None = None, file_pattern: str | None = None
    ) -> list[Learning]:
        """Delegate to store.query_learnings with filters."""
        return self._store.query_learnings(
            task_type=task_type,
            file_pattern=file_pattern,
            limit=self._max_learnings,
        )
