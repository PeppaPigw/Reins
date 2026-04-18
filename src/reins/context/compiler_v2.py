"""New context compiler for Reins v2.0 with spec injection.

This replaces the old compiler with a spec-based system that:
1. Loads specs from ContextSpecProjection
2. Allocates tokens by spec type
3. Assembles context with audit trail
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from reins.context.spec_projection import ContextSpecProjection, ResolvedSpec, SpecQuery
from reins.context.token_budget import TokenBudget, allocate_tokens, estimate_tokens


@dataclass(frozen=True)
class SpecSection:
    """One spec included in the assembled context."""

    spec_id: str
    spec_type: str
    content: str
    token_count: int
    precedence: int
    was_truncated: bool = False
    original_token_count: int | None = None


@dataclass(frozen=True)
class ContextAssemblyManifest:
    """Complete manifest of assembled context.

    This is what gets injected into the agent session.
    It includes the actual content plus audit trail.
    """

    standing_law: list[SpecSection]
    """Always-on conventions and standards"""

    task_contract: list[SpecSection]
    """Task-specific requirements (if task active)"""

    spec_shards: list[SpecSection]
    """On-demand guidance (phase/actor specific)"""

    total_tokens: int
    """Total tokens used"""

    token_breakdown: dict[str, int]
    """Token usage by spec type"""

    budget: TokenBudget
    """Budget that was used"""

    query_params: dict[str, Any]
    """Query parameters used for resolution (audit trail)"""

    resolved_spec_ids: list[str]
    """All spec IDs that were resolved (audit trail)"""

    dropped_spec_ids: list[str]
    """Spec IDs that were dropped due to budget (audit trail)"""

    @property
    def all_sections(self) -> list[SpecSection]:
        """Get all spec sections in order."""
        return self.standing_law + self.task_contract + self.spec_shards

    def to_text(self) -> str:
        """Convert manifest to text for injection into agent context."""
        lines: list[str] = []

        if self.standing_law:
            lines.append("# Standing Law (Project Conventions)\n")
            for section in self.standing_law:
                lines.append(f"## {section.spec_id}\n")
                lines.append(section.content)
                lines.append("\n---\n")

        if self.task_contract:
            lines.append("# Task Contract (Requirements)\n")
            for section in self.task_contract:
                lines.append(f"## {section.spec_id}\n")
                lines.append(section.content)
                lines.append("\n---\n")

        if self.spec_shards:
            lines.append("# Guidance (Phase-Specific)\n")
            for section in self.spec_shards:
                lines.append(f"## {section.spec_id}\n")
                lines.append(section.content)
                lines.append("\n---\n")

        return "".join(lines)


class ContextCompilerV2:
    """Assembles token-budgeted context from specs.

    This is the v2.0 compiler that uses the spec injection system.
    """

    def __init__(self, projection: ContextSpecProjection) -> None:
        self._projection = projection

    def seed_context(
        self,
        task_state: dict[str, Any] | None = None,
        granted_capabilities: set[str] | None = None,
        token_budget: TokenBudget | None = None,
        scope: str = "workspace",
    ) -> ContextAssemblyManifest:
        """Assemble seed context at session bootstrap.

        Seed context includes:
        - Standing law: Always-on conventions
        - Task contract: Task requirements (if task active)
        - Spec shards: Empty at seed time (added per-turn)

        Args:
            task_state: Current task state (if any)
            granted_capabilities: Capabilities granted to agent
            token_budget: Token budget (uses default if None)
            scope: Scope to query ('workspace' or 'task:id')

        Returns:
            ContextAssemblyManifest with assembled context
        """
        if granted_capabilities is None:
            granted_capabilities = set()

        if token_budget is None:
            token_budget = TokenBudget.default()

        # Build query for standing law
        query = SpecQuery(
            scope=scope,
            task_type=task_state.get("task_type") if task_state else None,
            run_phase=None,  # No phase filtering at seed time
            actor_type=None,
            path=None,
            granted_capabilities=granted_capabilities,
            visibility_tier=1,
        )

        # Resolve all specs
        all_resolved = self._projection.resolve(query)

        # Separate by spec type
        standing_law_specs = [s for s in all_resolved if s.spec_type == "standing_law"]
        task_contract_specs = [
            s for s in all_resolved if s.spec_type == "task_contract"
        ]

        # Allocate tokens by type
        standing_law_sections, standing_law_dropped = self._allocate_for_type(
            standing_law_specs, token_budget.standing_law
        )

        task_contract_sections, task_contract_dropped = self._allocate_for_type(
            task_contract_specs, token_budget.task_contract
        )

        # Calculate totals
        total_tokens = sum(s.token_count for s in standing_law_sections) + sum(
            s.token_count for s in task_contract_sections
        )

        token_breakdown = {
            "standing_law": sum(s.token_count for s in standing_law_sections),
            "task_contract": sum(s.token_count for s in task_contract_sections),
            "spec_shards": 0,
        }

        # Build audit trail
        resolved_spec_ids = [s.spec_id for s in all_resolved]
        dropped_spec_ids = standing_law_dropped + task_contract_dropped

        query_params = {
            "scope": scope,
            "task_type": task_state.get("task_type") if task_state else None,
            "granted_capabilities": list(granted_capabilities),
            "visibility_tier": 1,
        }

        return ContextAssemblyManifest(
            standing_law=standing_law_sections,
            task_contract=task_contract_sections,
            spec_shards=[],  # Empty at seed time
            total_tokens=total_tokens,
            token_breakdown=token_breakdown,
            budget=token_budget,
            query_params=query_params,
            resolved_spec_ids=resolved_spec_ids,
            dropped_spec_ids=dropped_spec_ids,
        )

    def _allocate_for_type(
        self, specs: list[ResolvedSpec], budget: int
    ) -> tuple[list[SpecSection], list[str]]:
        """Allocate tokens for a specific spec type.

        Args:
            specs: Resolved specs (already sorted by precedence)
            budget: Token budget for this type

        Returns:
            Tuple of (included sections, dropped spec_ids)
        """
        # Prepare for allocation
        spec_tuples = [(s.spec_id, s.content, s.token_count) for s in specs]

        # Allocate tokens
        allocation = allocate_tokens(spec_tuples, budget, allow_truncation=True)

        # Build sections
        sections: list[SpecSection] = []

        for spec_id, token_count in allocation.included:
            spec = next(s for s in specs if s.spec_id == spec_id)
            sections.append(
                SpecSection(
                    spec_id=spec.spec_id,
                    spec_type=spec.spec_type,
                    content=spec.content,
                    token_count=token_count,
                    precedence=spec.precedence,
                )
            )

        for spec_id, original_tokens, truncated_tokens in allocation.truncated:
            spec = next(s for s in specs if s.spec_id == spec_id)
            # Truncate content to fit
            truncated_content = self._truncate_content(
                spec.content, original_tokens, truncated_tokens
            )
            sections.append(
                SpecSection(
                    spec_id=spec.spec_id,
                    spec_type=spec.spec_type,
                    content=truncated_content,
                    token_count=truncated_tokens,
                    precedence=spec.precedence,
                    was_truncated=True,
                    original_token_count=original_tokens,
                )
            )

        dropped_ids = [spec_id for spec_id, _ in allocation.dropped]

        return sections, dropped_ids

    def _truncate_content(
        self, content: str, original_tokens: int, target_tokens: int
    ) -> str:
        """Truncate content to fit target token count.

        Uses simple character-based truncation (4 chars per token).
        More sophisticated truncation (sentence boundaries) can be added in v2.
        """
        if target_tokens >= original_tokens:
            return content

        target_chars = target_tokens * 4
        if len(content) <= target_chars:
            return content

        return content[:target_chars] + "\n\n[... truncated ...]"
