"""Context recomposition manager — handles dynamic context updates.

The ContextRecompositionManager responds to triggers (run_phase changes,
capability grants, task switches) and enriches the context by adding
relevant spec_shards based on the new state.
"""

from __future__ import annotations

from typing import Any

from reins.context.compiler_v2 import ContextCompilerV2
from reins.context.spec_projection import ContextSpecProjection
from reins.context.token_budget import TokenBudget


class ContextRecompositionManager:
    """Manages dynamic context updates based on state changes.

    This manager responds to triggers and enriches the context by:
    - Adding phase-specific spec_shards when run_phase changes
    - Adding capability-specific specs when new capabilities are granted
    - Updating task context when the active task switches
    """

    def __init__(
        self,
        compiler: ContextCompilerV2,
        projection: ContextSpecProjection,
    ) -> None:
        self._compiler = compiler
        self._projection = projection

    def on_run_phase_change(
        self,
        base_manifest: dict[str, Any],
        new_phase: str,
        actor_type: str | None = None,
        granted_capabilities: set[str] | None = None,
        token_budget: TokenBudget | None = None,
    ) -> dict[str, Any]:
        """Enrich context when run_phase changes.

        Args:
            base_manifest: Current context manifest (as dict)
            new_phase: New run_phase (e.g., "implement", "check", "debug")
            actor_type: Optional actor type (e.g., "implement-agent")
            granted_capabilities: Current granted capabilities
            token_budget: Optional token budget for enrichment

        Returns:
            Enriched context manifest (as dict)
        """
        # Build enrichment query
        enrichment_query = {
            "run_phase": new_phase,
            "actor_type": actor_type,
        }

        # Enrich context with phase-specific spec_shards
        enriched = self._compiler.enrich_context(
            base_manifest=base_manifest,
            trigger="run_phase_change",
            enrichment_query=enrichment_query,
            granted_capabilities=granted_capabilities or set(),
            token_budget=token_budget,
        )

        return enriched

    def on_capability_grant(
        self,
        base_manifest: dict[str, Any],
        new_capability: str,
        granted_capabilities: set[str],
        token_budget: TokenBudget | None = None,
    ) -> dict[str, Any]:
        """Enrich context when a new capability is granted.

        Args:
            base_manifest: Current context manifest (as dict)
            new_capability: Newly granted capability
            granted_capabilities: All currently granted capabilities
            token_budget: Optional token budget for enrichment

        Returns:
            Enriched context manifest (as dict)
        """
        # Build enrichment query
        enrichment_query = {
            "required_capabilities": [new_capability],
        }

        # Enrich context with capability-specific specs
        enriched = self._compiler.enrich_context(
            base_manifest=base_manifest,
            trigger="capability_grant",
            enrichment_query=enrichment_query,
            granted_capabilities=granted_capabilities,
            token_budget=token_budget,
        )

        return enriched

    def on_task_switch(
        self,
        base_manifest: dict[str, Any],
        new_task_id: str,
        task_state: dict[str, Any],
        granted_capabilities: set[str],
        token_budget: TokenBudget | None = None,
    ) -> dict[str, Any]:
        """Enrich context when the active task switches.

        Args:
            base_manifest: Current context manifest (as dict)
            new_task_id: New active task ID
            task_state: Task state dict (task_id, task_type, etc.)
            granted_capabilities: Current granted capabilities
            token_budget: Optional token budget for enrichment

        Returns:
            Enriched context manifest (as dict)
        """
        # Build enrichment query with task context
        enrichment_query = {
            "task_id": new_task_id,
            "task_type": task_state.get("task_type"),
        }

        # Enrich context with task-specific specs
        enriched = self._compiler.enrich_context(
            base_manifest=base_manifest,
            trigger="task_switch",
            enrichment_query=enrichment_query,
            granted_capabilities=granted_capabilities,
            token_budget=token_budget,
            task_state=task_state,
        )

        return enriched

    def recompose_full(
        self,
        task_state: dict[str, Any] | None,
        granted_capabilities: set[str],
        run_phase: str | None = None,
        actor_type: str | None = None,
        token_budget: TokenBudget | None = None,
    ) -> dict[str, Any]:
        """Recompose context from scratch (full rebuild).

        This is useful when multiple state changes happen simultaneously
        or when recovering from a checkpoint.

        Args:
            task_state: Current task state
            granted_capabilities: Current granted capabilities
            run_phase: Current run_phase
            actor_type: Current actor type
            token_budget: Optional token budget

        Returns:
            Fresh context manifest (as dict)
        """
        # Start with seed context
        manifest = self._compiler.seed_context(
            task_state=task_state,
            granted_capabilities=granted_capabilities,
            token_budget=token_budget,
            scope="workspace",
        )

        # If we have run_phase, enrich with phase-specific specs
        if run_phase:
            manifest = self.on_run_phase_change(
                base_manifest=manifest,
                new_phase=run_phase,
                actor_type=actor_type,
                granted_capabilities=granted_capabilities,
                token_budget=token_budget,
            )

        return manifest
