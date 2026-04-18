"""Local subagent manager — spawn, supervise, and coordinate child runs.

From SystemDesign §12: local subagents are preferred over remote agent
calls when locality suffices.  A subagent is a child run with:

  - Its own RunState (independent lifecycle)
  - Scoped grants inherited from the parent (narrower, never wider)
  - Access to the same journal (events carry a parent_run_id for correlation)
  - Bounded token budget (from the parent's allocation)
  - Explicit termination conditions (success criteria, timeout, max turns)

The SubagentManager does NOT call any model.  It creates child
RunOrchestrators that receive commands from the parent's planner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import ulid

from reins.context.compiler import ContextCompiler
from reins.isolation.types import IsolationLevel, WorktreeConfig
from reins.isolation.worktree_manager import WorktreeManager
from reins.kernel.event.builder import EventBuilder
from reins.kernel.event.journal import EventJournal
from reins.kernel.intent.envelope import IntentEnvelope
from reins.kernel.orchestrator import RunOrchestrator
from reins.kernel.reducer.reducer import reduce
from reins.kernel.reducer.state import RunState
from reins.kernel.snapshot.store import SnapshotStore
from reins.kernel.types import FailureClass, GrantRef
from reins.memory.checkpoint import CheckpointStore
from reins.policy.engine import PolicyEngine


class SubagentStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    aborted = "aborted"


@dataclass
class SubagentSpec:
    """Specification for spawning a local subagent."""

    objective: str
    parent_run_id: str
    inherited_grants: list[GrantRef] = field(default_factory=list)
    max_turns: int = 20
    token_budget: int = 30_000
    timeout_seconds: int = 300
    success_criteria: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    isolation_level: IsolationLevel = IsolationLevel.NONE
    worktree_config: WorktreeConfig | None = None
    task_id: str | None = None


@dataclass
class SubagentHandle:
    """A managed local subagent."""

    handle_id: str
    parent_run_id: str
    child_run_id: str
    objective: str
    status: SubagentStatus = SubagentStatus.pending
    turn_count: int = 0
    max_turns: int = 20
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    result: dict[str, Any] | None = None
    worktree_id: str | None = None
    isolation_level: IsolationLevel = IsolationLevel.NONE


class SubagentManager:
    """Manages the lifecycle of local subagent runs.

    Invariants:
      - Subagent grants are always a subset of the parent's grants.
      - Subagent events go to the same journal with parent correlation.
      - Subagents respect bounded turns and token budgets.
      - Subagent completion produces an observation to the parent.
    """

    def __init__(
        self,
        journal: EventJournal,
        snapshot_store: SnapshotStore,
        checkpoint_store: CheckpointStore,
        policy_engine: PolicyEngine,
        worktree_manager: WorktreeManager | None = None,
    ) -> None:
        self._journal = journal
        self._snapshot_store = snapshot_store
        self._checkpoint_store = checkpoint_store
        self._policy = policy_engine
        self._worktree_manager = worktree_manager
        self._active: dict[str, SubagentHandle] = {}
        self._children: dict[str, RunOrchestrator] = {}
        self._completed: list[SubagentHandle] = []
        self._builder = EventBuilder(journal)

    async def spawn(self, spec: SubagentSpec) -> SubagentHandle:
        """Spawn a new local subagent. Returns a handle for supervision."""
        await self._validate_inherited_grants(spec)
        child_run_id = str(ulid.new())

        # Create worktree if isolation level requires it
        worktree_id = None
        worktree_path = None
        if spec.isolation_level == IsolationLevel.WORKTREE:
            if self._worktree_manager is None:
                raise ValueError("WorktreeManager required for worktree isolation")
            if spec.worktree_config is None:
                raise ValueError("worktree_config required when isolation_level=WORKTREE")

            # Create worktree
            worktree_state = await self._worktree_manager.create_worktree(
                agent_id=child_run_id,
                task_id=spec.task_id,
                config=spec.worktree_config,
            )
            worktree_id = worktree_state.worktree_id
            worktree_path = str(worktree_state.worktree_path)

        handle = SubagentHandle(
            handle_id=str(ulid.new()),
            parent_run_id=spec.parent_run_id,
            child_run_id=child_run_id,
            objective=spec.objective,
            max_turns=spec.max_turns,
            worktree_id=worktree_id,
            isolation_level=spec.isolation_level,
        )
        self._active[handle.handle_id] = handle

        # Emit correlation event on the parent run
        await self._builder.commit(
            run_id=spec.parent_run_id,
            event_type="subagent.spawned",
            payload={
                "child_run_id": child_run_id,
                "objective": spec.objective,
                "max_turns": spec.max_turns,
                "token_budget": spec.token_budget,
                "inherited_grants": [g.grant_id for g in spec.inherited_grants],
                "isolation_level": spec.isolation_level.value,
                "worktree_id": worktree_id,
                "worktree_path": worktree_path,
            },
            correlation_id=child_run_id,
        )

        # Create child orchestrator
        context = ContextCompiler(token_budget=spec.token_budget)
        child_orch = RunOrchestrator(
            self._journal,
            self._snapshot_store,
            self._checkpoint_store,
            self._policy,
            context,
        )
        self._children[handle.handle_id] = child_orch

        # Intake the child run
        intent = IntentEnvelope(
            run_id=child_run_id,
            objective=spec.objective,
        )
        await child_orch.intake(intent)
        for grant in spec.inherited_grants:
            event = await self._builder.emit_grant_issued(
                child_run_id,
                grant.grant_id,
                grant.capability,
                grant.scope,
                grant.issued_to,
                grant.ttl_seconds,
                approval_hash=grant.approval_hash,
                inherited=True,
            )
            child_orch.apply_event(event)
        handle.status = SubagentStatus.running
        return handle

    async def report_turn(self, handle_id: str) -> bool:
        """Report a completed turn. Returns False if max_turns exceeded."""
        handle = self._active.get(handle_id)
        if handle is None:
            return False
        handle.turn_count += 1
        if handle.turn_count >= handle.max_turns:
            await self.abort(handle_id, reason="max turns exceeded")
            return False
        return True

    async def complete(
        self,
        handle_id: str,
        result: dict[str, Any],
    ) -> SubagentHandle | None:
        """Mark a subagent as completed with a result."""
        handle = self._active.pop(handle_id, None)
        child_orch = self._children.pop(handle_id, None)
        if handle is None:
            return None
        handle.status = SubagentStatus.completed
        handle.result = result
        if child_orch is not None:
            await child_orch.complete()

        # Clean up worktree if it exists
        if handle.worktree_id and self._worktree_manager:
            worktree_state = self._worktree_manager.get_worktree(handle.worktree_id)
            if worktree_state and worktree_state.config.cleanup_on_success:
                await self._worktree_manager.cleanup_agent_worktree(
                    handle.worktree_id,
                    force=False,
                    removed_by="subagent",
                    reason="Subagent completed successfully",
                )

        await self._builder.commit(
            run_id=handle.parent_run_id,
            event_type="subagent.completed",
            payload={
                "child_run_id": handle.child_run_id,
                "objective": handle.objective,
                "turns_used": handle.turn_count,
                "result_summary": result.get("summary", ""),
                "worktree_id": handle.worktree_id,
            },
            correlation_id=handle.child_run_id,
        )
        self._completed.append(handle)
        return handle

    async def fail(
        self,
        handle_id: str,
        reason: str,
    ) -> SubagentHandle | None:
        """Mark a subagent as failed."""
        handle = self._active.pop(handle_id, None)
        child_orch = self._children.pop(handle_id, None)
        if handle is None:
            return None
        handle.status = SubagentStatus.failed
        handle.result = {"error": reason}
        if child_orch is not None:
            await child_orch.fail(FailureClass.remote_agent_failure, reason)

        # Clean up worktree if it exists
        if handle.worktree_id and self._worktree_manager:
            worktree_state = self._worktree_manager.get_worktree(handle.worktree_id)
            if worktree_state and worktree_state.config.cleanup_on_failure:
                await self._worktree_manager.cleanup_agent_worktree(
                    handle.worktree_id,
                    force=True,  # Force removal on failure
                    removed_by="subagent",
                    reason=f"Subagent failed: {reason}",
                )

        await self._builder.commit(
            run_id=handle.parent_run_id,
            event_type="subagent.failed",
            payload={
                "child_run_id": handle.child_run_id,
                "reason": reason,
                "turns_used": handle.turn_count,
                "worktree_id": handle.worktree_id,
            },
            correlation_id=handle.child_run_id,
        )
        self._completed.append(handle)
        return handle

    async def abort(self, handle_id: str, reason: str = "aborted") -> None:
        """Abort a running subagent."""
        handle = self._active.pop(handle_id, None)
        child_orch = self._children.pop(handle_id, None)
        if handle is None:
            return
        handle.status = SubagentStatus.aborted
        handle.result = {"aborted": reason}
        if child_orch is not None:
            await child_orch.abort(reason)

        # Clean up worktree if it exists (always force on abort)
        if handle.worktree_id and self._worktree_manager:
            try:
                await self._worktree_manager.cleanup_agent_worktree(
                    handle.worktree_id,
                    force=True,
                    removed_by="subagent",
                    reason=f"Subagent aborted: {reason}",
                )
            except Exception:
                # Ignore cleanup errors on abort
                pass

        await self._builder.commit(
            run_id=handle.parent_run_id,
            event_type="subagent.aborted",
            payload={
                "child_run_id": handle.child_run_id,
                "reason": reason,
                "worktree_id": handle.worktree_id,
            },
            correlation_id=handle.child_run_id,
        )
        self._completed.append(handle)

    @property
    def active_count(self) -> int:
        return len(self._active)

    @property
    def active_handles(self) -> list[SubagentHandle]:
        return list(self._active.values())

    @property
    def history(self) -> list[SubagentHandle]:
        return list(self._completed)

    def get(self, handle_id: str) -> SubagentHandle | None:
        return self._active.get(handle_id)

    def get_orchestrator(self, handle_id: str) -> RunOrchestrator | None:
        return self._children.get(handle_id)

    async def _validate_inherited_grants(self, spec: SubagentSpec) -> None:
        if not spec.inherited_grants:
            return
        parent_state = RunState(run_id=spec.parent_run_id)
        async for event in self._journal.read_from(spec.parent_run_id):
            parent_state = reduce(parent_state, event)
        active_by_id = {grant.grant_id: grant for grant in parent_state.active_grants}
        invalid = [
            grant.grant_id
            for grant in spec.inherited_grants
            if active_by_id.get(grant.grant_id) != grant
        ]
        if invalid:
            raise ValueError(
                f"inherited grants must be an active subset of parent grants: {', '.join(invalid)}",
            )
