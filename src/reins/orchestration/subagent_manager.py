"""Subagent manager for multi-agent workflow coordination.

Manages subagent lifecycle: creation, context injection, monitoring, and cleanup.
Integrates with WorktreeManager for isolation and ContextInjectionHook for spec delivery.

Key Responsibilities:
- Create isolated execution environments (worktrees)
- Inject task context from JSONL files
- Monitor subagent progress via event stream
- Handle subagent failures and retries
- Clean up resources after completion
"""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

import ulid

from reins.isolation.worktree_manager import WorktreeManager
from reins.isolation.types import WorktreeState
from reins.kernel.event.journal import EventJournal
from reins.kernel.event.builder import EventBuilder
from reins.kernel.event.envelope import EventEnvelope
from reins.orchestration.hooks import ContextInjectionHook
from reins.orchestration.agent_registry import AgentRegistry


@dataclass
class SubagentHandle:
    """Handle for a spawned subagent."""

    agent_id: str
    agent_type: str
    task_id: str
    run_id: str
    worktree_state: WorktreeState | None
    context: dict[str, Any]


@dataclass
class AgentResult:
    """Result from a completed subagent."""

    agent_id: str
    agent_type: str
    status: str  # completed, failed
    exit_code: int | None
    output: dict[str, Any]
    error_message: str | None = None


class SubagentManager:
    """Manages subagent lifecycle and context injection.

    Integration points:
    - Use WorktreeManager for isolation
    - Use ContextInjectionHook for spec delivery
    - Use EventJournal for progress tracking
    - Use AgentRegistry for state tracking
    """

    def __init__(
        self,
        repo_root: Path,
        journal: EventJournal,
        worktree_manager: WorktreeManager,
        context_hook: ContextInjectionHook,
        agent_registry: AgentRegistry,
    ):
        """Initialize subagent manager.

        Args:
            repo_root: Repository root directory
            journal: EventJournal for event emission
            worktree_manager: WorktreeManager for isolation
            context_hook: ContextInjectionHook for spec injection
            agent_registry: AgentRegistry for state tracking
        """
        self.repo_root = repo_root
        self.journal = journal
        self._event_builder = EventBuilder(journal)
        self.worktree_manager = worktree_manager
        self.context_hook = context_hook
        self.agent_registry = agent_registry

    async def create_subagent(
        self,
        agent_type: str,
        task_id: str,
        run_id: str,
        use_worktree: bool = True,
    ) -> SubagentHandle:
        """Create a new subagent with isolated environment.

        Args:
            agent_type: Agent type (implement, check, debug, research)
            task_id: Task ID the agent will work on
            run_id: Run ID for event emission
            use_worktree: Whether to create isolated worktree (default True)

        Returns:
            SubagentHandle for monitoring and cleanup
        """
        agent_id = f"agent-{ulid.new()}"

        # 1. Inject context before spawning
        context = await self.context_hook.before_subagent_spawn(
            agent_type=agent_type,
            run_id=run_id,
        )

        # 2. Create isolated worktree if requested
        worktree_state = None

        if use_worktree:
            # Create worktree for agent
            worktree_state = await self.worktree_manager.create_worktree_for_agent(
                agent_id=agent_id,
                task_id=task_id,
                branch_name=f"agent/{agent_type}/{task_id}",
                base_branch=self._resolve_base_branch(),
            )

        # 3. Register agent in registry
        await self.agent_registry.register_agent(
            agent_type=agent_type,
            task_id=task_id,
            run_id=run_id,
            worktree_path=str(worktree_state.worktree_path) if worktree_state else None,
            agent_id=agent_id,
        )

        # 4. Update agent status to running
        await self.agent_registry.update_status(
            agent_id=agent_id,
            status="running",
            run_id=run_id,
        )

        # 5. Emit subagent spawned event
        await self._event_builder.commit(
            run_id=run_id,
            event_type="orchestrator.subagent_spawned",
            payload={
                "agent_id": agent_id,
                "agent_type": agent_type,
                "task_id": task_id,
                "worktree_id": worktree_state.worktree_id if worktree_state else None,
                "worktree_path": str(worktree_state.worktree_path) if worktree_state else None,
                "context_size": len(str(context)),
            },
        )

        return SubagentHandle(
            agent_id=agent_id,
            agent_type=agent_type,
            task_id=task_id,
            run_id=run_id,
            worktree_state=worktree_state,
            context=context,
        )

    async def inject_context(
        self,
        handle: SubagentHandle,
        additional_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Inject additional context into subagent.

        Args:
            handle: SubagentHandle for the agent
            additional_context: Optional additional context to inject

        Returns:
            Combined context dict
        """
        # Start with existing context
        context = dict(handle.context)

        # Merge additional context if provided
        if additional_context:
            context.update(additional_context)

        # Emit context compiled event
        await self._event_builder.commit(
            run_id=handle.run_id,
            event_type="context.compiled",
            payload={
                "agent_id": handle.agent_id,
                "agent_type": handle.agent_type,
                "context_size": len(str(context)),
            },
        )

        return context

    async def monitor_progress(
        self,
        handle: SubagentHandle,
        event_types: list[str] | None = None,
    ) -> AsyncIterator[EventEnvelope]:
        """Monitor subagent progress via event stream.

        Args:
            handle: SubagentHandle for the agent
            event_types: Optional list of event types to filter (default: all)

        Yields:
            EventEnvelope for each relevant event
        """
        from_seq = 0
        terminal_events = {
            "orchestrator.subagent_completed",
            "orchestrator.subagent_failed",
        }

        while True:
            saw_event = False
            async for event in self.journal.read_from(handle.run_id, from_seq=from_seq):
                saw_event = True
                from_seq = max(from_seq, event.seq + 1)

                if event_types and event.type not in event_types:
                    continue

                payload = event.payload
                if not isinstance(payload, dict):
                    continue

                if payload.get("agent_id") != handle.agent_id:
                    continue

                yield event

                if event.type in terminal_events:
                    return

            if not saw_event:
                await asyncio.sleep(0.05)

    async def collect_results(
        self,
        handle: SubagentHandle,
        timeout_seconds: float = 300.0,
    ) -> AgentResult:
        """Wait for subagent completion and collect results.

        Args:
            handle: SubagentHandle for the agent
            timeout_seconds: Maximum time to wait (default 5 minutes)

        Returns:
            AgentResult with status and output

        Raises:
            asyncio.TimeoutError: If agent doesn't complete within timeout
        """
        try:
            # Wait for completion event with timeout
            async with asyncio.timeout(timeout_seconds):
                async for event in self.monitor_progress(
                    handle,
                    event_types=[
                        "orchestrator.subagent_completed",
                        "orchestrator.subagent_failed",
                    ],
                ):
                    payload = event.payload
                    if not isinstance(payload, dict):
                        continue

                    status = "completed" if event.type == "orchestrator.subagent_completed" else "failed"
                    exit_code = payload.get("exit_code")
                    error_message = payload.get("error_message")

                    # Update agent status in registry
                    await self.agent_registry.update_status(
                        agent_id=handle.agent_id,
                        status=status,
                        run_id=handle.run_id,
                        exit_code=exit_code,
                        error_message=error_message,
                    )

                    # Collect result from context hook
                    result_output = payload.get("output", {})

                    if status == "completed":
                        await self.context_hook.after_subagent_complete(
                            agent_type=handle.agent_type,
                            run_id=handle.run_id,
                            result=result_output,
                        )
                    else:
                        await self.context_hook.on_error(
                            agent_type=handle.agent_type,
                            run_id=handle.run_id,
                            error=RuntimeError(
                                error_message
                                or f"Subagent {handle.agent_id} failed"
                            ),
                        )

                    return AgentResult(
                        agent_id=handle.agent_id,
                        agent_type=handle.agent_type,
                        status=status,
                        exit_code=exit_code,
                        output=result_output,
                        error_message=error_message,
                    )

                # If we get here, no completion event was found
                raise RuntimeError(f"No completion event found for agent {handle.agent_id}")

        except asyncio.TimeoutError:
            # Timeout - mark agent as failed
            await self.agent_registry.update_status(
                agent_id=handle.agent_id,
                status="failed",
                run_id=handle.run_id,
                error_message=f"Timeout after {timeout_seconds}s",
            )

            # Call on_error hook
            await self.context_hook.on_error(
                agent_type=handle.agent_type,
                run_id=handle.run_id,
                error=asyncio.TimeoutError(f"Agent timeout after {timeout_seconds}s"),
            )

            raise

    async def cleanup(
        self,
        handle: SubagentHandle,
        remove_worktree: bool = True,
    ) -> None:
        """Clean up subagent resources.

        Args:
            handle: SubagentHandle for the agent
            remove_worktree: Whether to remove worktree (default True)
        """
        # 1. Remove worktree if requested
        if remove_worktree and handle.worktree_state:
            await self.worktree_manager.cleanup_agent_worktree(
                handle.worktree_state.worktree_id,
                force=True,
            )

        # 2. Remove agent from registry
        await self.agent_registry.cleanup_agent(
            agent_id=handle.agent_id,
            run_id=handle.run_id,
        )

        # 3. Emit cleanup event
        await self._event_builder.commit(
            run_id=handle.run_id,
            event_type="orchestrator.subagent_cleanup",
            payload={
                "agent_id": handle.agent_id,
                "agent_type": handle.agent_type,
                "task_id": handle.task_id,
                "worktree_removed": remove_worktree,
            },
        )

    async def handle_failure(
        self,
        handle: SubagentHandle,
        error: Exception,
        retry: bool = False,
    ) -> AgentResult | None:
        """Handle subagent failure.

        Args:
            handle: SubagentHandle for the failed agent
            error: Exception that caused failure
            retry: Whether to retry the agent (default False)

        Returns:
            AgentResult if retry is False, None if retrying
        """
        # Update agent status to failed
        await self.agent_registry.update_status(
            agent_id=handle.agent_id,
            status="failed",
            run_id=handle.run_id,
            error_message=str(error),
        )

        # Call on_error hook
        await self.context_hook.on_error(
            agent_type=handle.agent_type,
            run_id=handle.run_id,
            error=error,
        )

        # Emit failure event
        await self._event_builder.commit(
            run_id=handle.run_id,
            event_type="orchestrator.subagent_failed",
            payload={
                "agent_id": handle.agent_id,
                "agent_type": handle.agent_type,
                "task_id": handle.task_id,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "will_retry": retry,
            },
        )

        if retry:
            # TODO: Implement retry logic
            return None

        return AgentResult(
            agent_id=handle.agent_id,
            agent_type=handle.agent_type,
            status="failed",
            exit_code=1,
            output={},
            error_message=str(error),
        )

    def _resolve_base_branch(self) -> str:
        """Return the current repo branch, falling back to ``main``."""
        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return "main"

        branch = result.stdout.strip()
        return branch or "main"
