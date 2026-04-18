"""Applicability matching for context specs.

Matches specs based on run_phase, actor_type, capabilities, and other
applicability rules to determine which specs should be included in context.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from reins.context.spec_projection import SpecDescriptor


@dataclass
class ApplicabilityQuery:
    """Query for matching specs by applicability."""

    run_phase: str | None = None
    """Current run phase (e.g., 'plan', 'implement', 'check')"""

    actor_type: str | None = None
    """Type of actor (e.g., 'planner', 'implementer', 'checker')"""

    granted_capabilities: set[str] | None = None
    """Set of granted capabilities"""

    scope: str = "workspace"
    """Scope to match (e.g., 'workspace', 'task:123')"""

    additional_filters: dict[str, Any] | None = None
    """Additional custom filters"""


class ApplicabilityMatcher:
    """Matches specs based on applicability rules.

    Filters specs by run_phase, actor_type, capabilities, and other
    applicability criteria to determine which specs should be included.
    """

    def match(
        self,
        specs: list[SpecDescriptor],
        query: ApplicabilityQuery,
    ) -> list[SpecDescriptor]:
        """Match specs against applicability query.

        Args:
            specs: List of specs to filter
            query: Applicability query

        Returns:
            List of specs that match the query
        """
        matched: list[SpecDescriptor] = []

        for spec in specs:
            if self._matches_spec(spec, query):
                matched.append(spec)

        return matched

    def _matches_spec(
        self,
        spec: SpecDescriptor,
        query: ApplicabilityQuery,
    ) -> bool:
        """Check if a spec matches the query.

        Args:
            spec: Spec to check
            query: Applicability query

        Returns:
            True if spec matches, False otherwise
        """
        # Check scope
        if not self._matches_scope(spec.scope, query.scope):
            return False

        # Check applicability rules
        if spec.applicability:
            # Check run_phase - if spec requires a phase, query must match
            if "run_phase" in spec.applicability:
                required_phase = spec.applicability["run_phase"]
                if query.run_phase is not None and query.run_phase != required_phase:
                    return False

            # Check actor_type - if spec requires an actor, query must match
            if "actor_type" in spec.applicability:
                required_actor = spec.applicability["actor_type"]
                if query.actor_type is not None and query.actor_type != required_actor:
                    return False

            # Check capabilities
            if "required_capabilities" in spec.applicability:
                required_caps = set(spec.applicability["required_capabilities"])
                granted_caps = query.granted_capabilities or set()
                # Only check if query explicitly provides capabilities
                if query.granted_capabilities is not None and not required_caps.issubset(granted_caps):
                    return False

            # Check additional filters
            if query.additional_filters:
                for key, value in query.additional_filters.items():
                    if key in spec.applicability:
                        if spec.applicability[key] != value:
                            return False

        # Check required capabilities at spec level
        if spec.required_capabilities:
            required_caps = set(spec.required_capabilities)
            granted_caps = query.granted_capabilities or set()
            # Only check if query explicitly provides capabilities
            # If no capabilities in query, assume we're just filtering by other criteria
            if query.granted_capabilities is not None and not required_caps.issubset(granted_caps):
                return False

        return True

    def _matches_scope(self, spec_scope: str, query_scope: str) -> bool:
        """Check if spec scope matches query scope.

        Args:
            spec_scope: Scope from spec (e.g., 'workspace', 'task:123')
            query_scope: Scope from query

        Returns:
            True if scopes match
        """
        # Exact match
        if spec_scope == query_scope:
            return True

        # Workspace scope matches everything
        if spec_scope == "workspace":
            return True

        # Task scope matches if query is for that specific task
        if spec_scope.startswith("task:") and query_scope.startswith("task:"):
            return spec_scope == query_scope

        return False

    def filter_by_phase(
        self,
        specs: list[SpecDescriptor],
        run_phase: str,
    ) -> list[SpecDescriptor]:
        """Filter specs by run phase.

        Args:
            specs: List of specs to filter
            run_phase: Run phase to match

        Returns:
            List of specs matching the phase
        """
        query = ApplicabilityQuery(run_phase=run_phase)
        return self.match(specs, query)

    def filter_by_actor(
        self,
        specs: list[SpecDescriptor],
        actor_type: str,
    ) -> list[SpecDescriptor]:
        """Filter specs by actor type.

        Args:
            specs: List of specs to filter
            actor_type: Actor type to match

        Returns:
            List of specs matching the actor type
        """
        query = ApplicabilityQuery(actor_type=actor_type)
        return self.match(specs, query)

    def filter_by_capabilities(
        self,
        specs: list[SpecDescriptor],
        granted_capabilities: set[str],
    ) -> list[SpecDescriptor]:
        """Filter specs by granted capabilities.

        Args:
            specs: List of specs to filter
            granted_capabilities: Set of granted capabilities

        Returns:
            List of specs that can be used with the given capabilities
        """
        query = ApplicabilityQuery(granted_capabilities=granted_capabilities)
        return self.match(specs, query)

    def filter_by_scope(
        self,
        specs: list[SpecDescriptor],
        scope: str,
    ) -> list[SpecDescriptor]:
        """Filter specs by scope.

        Args:
            specs: List of specs to filter
            scope: Scope to match

        Returns:
            List of specs matching the scope
        """
        return [spec for spec in specs if self._matches_scope(spec.scope, scope)]
