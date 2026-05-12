from __future__ import annotations

from typing import Any, Protocol


class RunLifecycleAdvisor(Protocol):
    """Protocol for intelligence layer integration with RunOrchestrator.

    The kernel owns this protocol definition. Intelligence layer provides
    the concrete implementation. This keeps the dependency direction clean:
    kernel does NOT import intelligence.
    """

    async def on_intake(self, objective: str, context: dict[str, Any]) -> dict[str, Any]:
        """Called after intake. Returns advisory context (e.g., DAG proposal)."""
        ...

    async def on_before_route(self, state: dict[str, Any]) -> dict[str, Any]:
        """Called before routing. Returns strategy recommendation."""
        ...

    async def on_after_execution(
        self, task_id: str, domain: str, success: bool, context: dict[str, Any]
    ) -> None:
        """Called after command execution. Records outcome for trust/memory."""
        ...

    async def on_repair_required(
        self, failure: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Called when repair is needed. Returns enriched recovery guidance."""
        ...

    async def on_complete(self, task_id: str, domain: str) -> None:
        """Called on run completion. Updates trust and memory."""
        ...

    async def on_fail(self, task_id: str, domain: str, reason: str) -> None:
        """Called on run failure. Updates trust with failure severity."""
        ...
