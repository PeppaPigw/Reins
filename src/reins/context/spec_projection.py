"""Context spec projection — builds queryable index from spec events.

The projection consumes spec events from the journal and maintains
an in-memory index for fast queries. This is the read model in CQRS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.event.spec_events import (
    SPEC_DEACTIVATED,
    SPEC_REGISTERED,
    SPEC_SUPERSEDED,
)


@dataclass(frozen=True)
class SpecQuery:
    """Query parameters for resolving specs.

    Used to find specs that match specific criteria (scope, task type,
    run phase, etc.). All fields are optional for flexible querying.
    """

    scope: str = "workspace"
    """Scope to query: 'workspace' or 'task:{task_id}'"""

    task_type: str | None = None
    """Filter by task type: 'backend', 'frontend', 'fullstack'"""

    run_phase: str | None = None
    """Filter by run phase: 'implement', 'check', 'debug'"""

    actor_type: str | None = None
    """Filter by actor type: 'implement-agent', 'check-agent'"""

    path: str | None = None
    """Filter by file path (for path_pattern matching)"""

    granted_capabilities: set[str] = field(default_factory=set)
    """Capabilities granted to the agent (for visibility filtering)"""

    visibility_tier: int = 1
    """Maximum visibility tier to include (0=all, 1=standard, 2=advanced, 3=expert)"""


@dataclass(frozen=True)
class ResolvedSpec:
    """A spec that matched a query, with its content and metadata."""

    spec_id: str
    spec_type: str
    content: str
    precedence: int
    token_count: int
    source_path: str | None
    matched_criteria: dict[str, Any]
    """Which query criteria this spec matched"""


@dataclass(frozen=True)
class SpecDescriptor:
    """Metadata about a registered spec.

    This is the projection's view of a spec — just the metadata,
    not the full content (which stays in events).
    """

    spec_id: str
    spec_type: str
    scope: str
    applicability: dict[str, Any]
    required_capabilities: list[str]
    visibility_tier: int
    precedence: int
    source_path: str | None
    registered_by: str
    token_count: int
    is_superseded: bool = False
    superseded_by: str | None = None
    is_deactivated: bool = False
    deactivated_reason: str | None = None


@dataclass
class SpecContent:
    """Full spec content loaded from events."""

    spec_id: str
    content: str
    descriptor: SpecDescriptor


class ContextSpecProjection:
    """Projection that builds a queryable index of specs from events.

    This is the read model for the context injection system.
    It maintains:
    - Primary index: specs by spec_id
    - Lifecycle state: superseded/deactivated flags
    - Content cache: full spec content (loaded on demand)
    """

    def __init__(self) -> None:
        # Primary index: spec_id -> SpecDescriptor
        self._specs: dict[str, SpecDescriptor] = {}

        # Content cache: spec_id -> content string
        # Loaded lazily to save memory
        self._content_cache: dict[str, str] = {}

    def apply_event(self, event: EventEnvelope) -> None:
        """Apply an event to update the projection state.

        This is called for each event during projection rebuild.
        """
        if event.type == SPEC_REGISTERED:
            self._apply_spec_registered(event)
        elif event.type == SPEC_SUPERSEDED:
            self._apply_spec_superseded(event)
        elif event.type == SPEC_DEACTIVATED:
            self._apply_spec_deactivated(event)

    def _apply_spec_registered(self, event: EventEnvelope) -> None:
        """Handle SpecRegisteredEvent."""
        payload = event.payload

        descriptor = SpecDescriptor(
            spec_id=payload["spec_id"],
            spec_type=payload["spec_type"],
            scope=payload["scope"],
            applicability=payload["applicability"],
            required_capabilities=payload["required_capabilities"],
            visibility_tier=payload["visibility_tier"],
            precedence=payload["precedence"],
            source_path=payload.get("source_path"),
            registered_by=payload["registered_by"],
            token_count=payload["token_count"],
        )

        self._specs[descriptor.spec_id] = descriptor

        # Cache content
        self._content_cache[descriptor.spec_id] = payload["content"]

    def _apply_spec_superseded(self, event: EventEnvelope) -> None:
        """Handle SpecSupersededEvent."""
        payload = event.payload
        spec_id = payload["spec_id"]
        superseded_by = payload["superseded_by"]

        if spec_id in self._specs:
            old_descriptor = self._specs[spec_id]
            self._specs[spec_id] = SpecDescriptor(
                spec_id=old_descriptor.spec_id,
                spec_type=old_descriptor.spec_type,
                scope=old_descriptor.scope,
                applicability=old_descriptor.applicability,
                required_capabilities=old_descriptor.required_capabilities,
                visibility_tier=old_descriptor.visibility_tier,
                precedence=old_descriptor.precedence,
                source_path=old_descriptor.source_path,
                registered_by=old_descriptor.registered_by,
                token_count=old_descriptor.token_count,
                is_superseded=True,
                superseded_by=superseded_by,
            )

    def _apply_spec_deactivated(self, event: EventEnvelope) -> None:
        """Handle SpecDeactivatedEvent."""
        payload = event.payload
        spec_id = payload["spec_id"]
        reason = payload.get("reason")

        if spec_id in self._specs:
            old_descriptor = self._specs[spec_id]
            self._specs[spec_id] = SpecDescriptor(
                spec_id=old_descriptor.spec_id,
                spec_type=old_descriptor.spec_type,
                scope=old_descriptor.scope,
                applicability=old_descriptor.applicability,
                required_capabilities=old_descriptor.required_capabilities,
                visibility_tier=old_descriptor.visibility_tier,
                precedence=old_descriptor.precedence,
                source_path=old_descriptor.source_path,
                registered_by=old_descriptor.registered_by,
                token_count=old_descriptor.token_count,
                is_superseded=old_descriptor.is_superseded,
                superseded_by=old_descriptor.superseded_by,
                is_deactivated=True,
                deactivated_reason=reason,
            )

    def get_spec(self, spec_id: str) -> SpecDescriptor | None:
        """Get spec descriptor by ID.

        Returns:
            SpecDescriptor if found, None otherwise
        """
        return self._specs.get(spec_id)

    def get_spec_content(self, spec_id: str) -> SpecContent | None:
        """Get full spec content by ID.

        Returns:
            SpecContent with descriptor and content, None if not found
        """
        descriptor = self._specs.get(spec_id)
        if not descriptor:
            return None

        content = self._content_cache.get(spec_id)
        if not content:
            return None

        return SpecContent(
            spec_id=spec_id,
            content=content,
            descriptor=descriptor,
        )

    def list_specs(
        self,
        scope: str | None = None,
        include_superseded: bool = False,
        include_deactivated: bool = False,
    ) -> list[SpecDescriptor]:
        """List all specs matching criteria.

        Args:
            scope: Filter by scope (e.g., 'workspace', 'task:123')
            include_superseded: Include superseded specs
            include_deactivated: Include deactivated specs

        Returns:
            List of SpecDescriptors matching criteria
        """
        specs = list(self._specs.values())

        # Filter by scope
        if scope is not None:
            specs = [s for s in specs if s.scope == scope]

        # Filter lifecycle
        if not include_superseded:
            specs = [s for s in specs if not s.is_superseded]

        if not include_deactivated:
            specs = [s for s in specs if not s.is_deactivated]

        return specs

    def count_specs(self) -> int:
        """Count total specs (including superseded/deactivated)."""
        return len(self._specs)

    def count_active_specs(self) -> int:
        """Count active specs (excluding superseded/deactivated)."""
        return len(
            [
                s
                for s in self._specs.values()
                if not s.is_superseded and not s.is_deactivated
            ]
        )

    def clear(self) -> None:
        """Clear all projection state. Used for testing."""
        self._specs.clear()
        self._content_cache.clear()

    def resolve(self, query: SpecQuery) -> list[ResolvedSpec]:
        """Resolve specs matching the query criteria.

        This is the main query method for the projection. It:
        1. Filters by scope
        2. Excludes superseded/deactivated specs
        3. Filters by applicability (task_type, run_phase, actor_type, path)
        4. Filters by capabilities (visibility filtering)
        5. Filters by visibility tier
        6. Sorts by precedence (highest first)

        Args:
            query: Query parameters

        Returns:
            List of ResolvedSpec objects sorted by precedence (descending)
        """
        candidates = self.list_specs(
            scope=query.scope,
            include_superseded=False,
            include_deactivated=False,
        )

        resolved: list[ResolvedSpec] = []

        for descriptor in candidates:
            # Check applicability
            if not self._matches_applicability(descriptor, query):
                continue

            # Check capability requirements (visibility filtering)
            if not self._has_required_capabilities(
                descriptor, query.granted_capabilities
            ):
                continue

            # Check visibility tier
            if descriptor.visibility_tier > query.visibility_tier:
                continue

            # Get content
            content = self._content_cache.get(descriptor.spec_id, "")

            # Build matched criteria for audit trail
            matched_criteria = {
                "scope": query.scope,
                "task_type": query.task_type,
                "run_phase": query.run_phase,
                "actor_type": query.actor_type,
                "path": query.path,
            }

            resolved.append(
                ResolvedSpec(
                    spec_id=descriptor.spec_id,
                    spec_type=descriptor.spec_type,
                    content=content,
                    precedence=descriptor.precedence,
                    token_count=descriptor.token_count,
                    source_path=descriptor.source_path,
                    matched_criteria=matched_criteria,
                )
            )

        # Sort by precedence (highest first), then by spec_id for determinism
        resolved.sort(key=lambda s: (-s.precedence, s.spec_id))

        return resolved

    def _matches_applicability(
        self, descriptor: SpecDescriptor, query: SpecQuery
    ) -> bool:
        """Check if spec's applicability criteria match the query.

        A spec matches if:
        - Its task_type is None (applies to all) OR matches query.task_type
        - Its run_phase is None (applies to all) OR matches query.run_phase
        - Its actor_type is None (applies to all) OR matches query.actor_type
        - Its path_pattern is None (applies to all) OR matches query.path

        All criteria must match (AND logic).
        """
        applicability = descriptor.applicability

        # Check task_type
        spec_task_type = applicability.get("task_type")
        if spec_task_type is not None and spec_task_type != query.task_type:
            return False

        # Check run_phase
        spec_run_phase = applicability.get("run_phase")
        if spec_run_phase is not None and spec_run_phase != query.run_phase:
            return False

        # Check actor_type
        spec_actor_type = applicability.get("actor_type")
        if spec_actor_type is not None and spec_actor_type != query.actor_type:
            return False

        # Check path_pattern (simple substring match for now)
        # TODO: Implement fnmatch/glob pattern matching in v2
        spec_path_pattern = applicability.get("path_pattern")
        if spec_path_pattern is not None:
            if query.path is None:
                return False
            # Simple substring match for v1
            if spec_path_pattern not in query.path:
                return False

        return True

    def _has_required_capabilities(
        self, descriptor: SpecDescriptor, granted_capabilities: set[str]
    ) -> bool:
        """Check if agent has all required capabilities to see this spec.

        This is visibility filtering, not authorization.
        If a spec requires ['fs:write', 'git:commit'], the agent must
        have both capabilities to see the spec.
        """
        required = set(descriptor.required_capabilities)
        return required.issubset(granted_capabilities)
