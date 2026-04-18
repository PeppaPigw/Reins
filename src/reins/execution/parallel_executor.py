"""Parallel task executor for spawning multiple subagents concurrently.

Coordinates parallel execution of multiple tasks using isolated worktrees.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from reins.isolation.types import IsolationLevel, WorktreeConfig
from reins.isolation.worktree_manager import WorktreeManager
from reins.kernel.event.journal import EventJournal
from reins.kernel.snapshot.store import SnapshotStore
from reins.memory.checkpoint import CheckpointStore
from reins.policy.engine import PolicyEngine
from reins.subagent.manager import SubagentManager, SubagentSpec, SubagentStatus


class TaskExecutionState(str, Enum):
    """State of a task in parallel execution."""

    PENDING = "pending"
    """Task is waiting to start"""

    RUNNING = "running"
    """Task is currently executing"""

    COMPLETED = "completed"
    """Task completed successfully"""

    FAILED = "failed"
    """Task failed"""

    CANCELLED = "cancelled"
    """Task was cancelled"""


@dataclass
class ParallelExecutionResult:
    """Result of parallel task execution."""

    task_id: str
    """ID of the task"""

    state: TaskExecutionState
    """Final state of the task"""

    result: dict[str, Any] | None = None
    """Task result if completed"""

    error: str | None = None
    """Error message if failed"""

    started_at: datetime | None = None
    """When the task started"""

    completed_at: datetime | None = None
    """When the task completed"""

    duration_seconds: float | None = None
    """Task duration in seconds"""


@dataclass
class ParallelTaskSpec:
    """Specification for a task in parallel execution."""

    task_id: str
    """Unique task identifier"""

    objective: str
    """Task objective"""

    isolation_level: IsolationLevel = IsolationLevel.WORKTREE
    """Isolation level (default: worktree)"""

    worktree_config: WorktreeConfig | None = None
    """Worktree configuration"""

    max_turns: int = 20
    """Maximum turns for the subagent"""

    token_budget: int = 30_000
    """Token budget for the subagent"""

    timeout_seconds: int = 300
    """Timeout in seconds"""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata"""


class ParallelTaskExecutor:
    """Executes multiple tasks in parallel using isolated subagents.

    Coordinates parallel execution with worktree isolation, tracks state,
    and handles completion/failure of parallel tasks.
    """

    def __init__(
        self,
        journal: EventJournal,
        snapshot_store: SnapshotStore,
        checkpoint_store: CheckpointStore,
        policy_engine: PolicyEngine,
        worktree_manager: WorktreeManager,
        parent_run_id: str,
        max_parallel: int = 4,
    ) -> None:
        """Initialize parallel task executor.

        Args:
            journal: Event journal
            snapshot_store: Snapshot store
            checkpoint_store: Checkpoint store
            policy_engine: Policy engine
            worktree_manager: Worktree manager for isolation
            parent_run_id: Parent run ID
            max_parallel: Maximum number of parallel tasks (default: 4)
        """
        self._journal = journal
        self._snapshot_store = snapshot_store
        self._checkpoint_store = checkpoint_store
        self._policy_engine = policy_engine
        self._worktree_manager = worktree_manager
        self._parent_run_id = parent_run_id
        self._max_parallel = max_parallel

        # Create subagent manager
        self._subagent_manager = SubagentManager(
            journal=journal,
            snapshot_store=snapshot_store,
            checkpoint_store=checkpoint_store,
            policy_engine=policy_engine,
            worktree_manager=worktree_manager,
        )

        # Track execution state
        self._tasks: dict[str, ParallelTaskSpec] = {}
        self._states: dict[str, TaskExecutionState] = {}
        self._results: dict[str, ParallelExecutionResult] = {}
        self._handle_ids: dict[str, str] = {}  # task_id -> handle_id

    async def execute_parallel(
        self,
        tasks: list[ParallelTaskSpec],
    ) -> list[ParallelExecutionResult]:
        """Execute multiple tasks in parallel.

        Args:
            tasks: List of task specifications

        Returns:
            List of execution results
        """
        # Register tasks
        for task in tasks:
            self._tasks[task.task_id] = task
            self._states[task.task_id] = TaskExecutionState.PENDING

        # Execute in batches respecting max_parallel
        results: list[ParallelExecutionResult] = []

        for i in range(0, len(tasks), self._max_parallel):
            batch = tasks[i : i + self._max_parallel]
            batch_results = await self._execute_batch(batch)
            results.extend(batch_results)

        return results

    async def _execute_batch(
        self,
        tasks: list[ParallelTaskSpec],
    ) -> list[ParallelExecutionResult]:
        """Execute a batch of tasks in parallel.

        Args:
            tasks: Batch of tasks to execute

        Returns:
            List of execution results
        """
        # Spawn all tasks in parallel
        spawn_tasks = [self._spawn_task(task) for task in tasks]
        await asyncio.gather(*spawn_tasks, return_exceptions=True)

        # Wait for all tasks to complete
        wait_tasks = [self._wait_for_task(task.task_id) for task in tasks]
        results = await asyncio.gather(*wait_tasks, return_exceptions=True)

        # Convert exceptions to failed results
        final_results: list[ParallelExecutionResult] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append(
                    ParallelExecutionResult(
                        task_id=tasks[i].task_id,
                        state=TaskExecutionState.FAILED,
                        error=str(result),
                    )
                )
            else:
                final_results.append(result)

        return final_results

    async def _spawn_task(self, task: ParallelTaskSpec) -> None:
        """Spawn a single task.

        Args:
            task: Task specification
        """
        try:
            # Create subagent spec
            spec = SubagentSpec(
                objective=task.objective,
                parent_run_id=self._parent_run_id,
                isolation_level=task.isolation_level,
                worktree_config=task.worktree_config,
                task_id=task.task_id,
                max_turns=task.max_turns,
                token_budget=task.token_budget,
                timeout_seconds=task.timeout_seconds,
            )

            # Spawn subagent
            handle = await self._subagent_manager.spawn(spec)

            # Track handle
            self._handle_ids[task.task_id] = handle.handle_id
            self._states[task.task_id] = TaskExecutionState.RUNNING

            # Record start time
            self._results[task.task_id] = ParallelExecutionResult(
                task_id=task.task_id,
                state=TaskExecutionState.RUNNING,
                started_at=datetime.now(UTC),
            )

        except Exception as e:
            self._states[task.task_id] = TaskExecutionState.FAILED
            self._results[task.task_id] = ParallelExecutionResult(
                task_id=task.task_id,
                state=TaskExecutionState.FAILED,
                error=str(e),
            )

    async def _wait_for_task(self, task_id: str) -> ParallelExecutionResult:
        """Wait for a task to complete.

        Args:
            task_id: Task ID to wait for

        Returns:
            Execution result
        """
        handle_id = self._handle_ids.get(task_id)
        if not handle_id:
            return ParallelExecutionResult(
                task_id=task_id,
                state=TaskExecutionState.FAILED,
                error="Task not spawned",
            )

        # Poll for completion
        # In a real implementation, this would use event-based waiting
        while True:
            handle = self._subagent_manager.get(handle_id)
            if not handle:
                break

            if handle.status == SubagentStatus.completed:
                completed_at = datetime.now(UTC)
                result = self._results.get(task_id)
                if result and result.started_at:
                    duration = (completed_at - result.started_at).total_seconds()
                else:
                    duration = None

                return ParallelExecutionResult(
                    task_id=task_id,
                    state=TaskExecutionState.COMPLETED,
                    result=handle.result,
                    started_at=result.started_at if result else None,
                    completed_at=completed_at,
                    duration_seconds=duration,
                )

            elif handle.status == SubagentStatus.failed:
                return ParallelExecutionResult(
                    task_id=task_id,
                    state=TaskExecutionState.FAILED,
                    error=handle.result.get("error") if handle.result else None,
                    started_at=self._results.get(task_id).started_at
                    if task_id in self._results
                    else None,
                    completed_at=datetime.now(UTC),
                )

            elif handle.status == SubagentStatus.aborted:
                return ParallelExecutionResult(
                    task_id=task_id,
                    state=TaskExecutionState.CANCELLED,
                    error="Task aborted",
                    started_at=self._results.get(task_id).started_at
                    if task_id in self._results
                    else None,
                    completed_at=datetime.now(UTC),
                )

            # Wait a bit before polling again
            await asyncio.sleep(0.1)

        # Handle not found
        return ParallelExecutionResult(
            task_id=task_id,
            state=TaskExecutionState.FAILED,
            error="Handle lost",
        )

    def get_state(self, task_id: str) -> TaskExecutionState | None:
        """Get current state of a task.

        Args:
            task_id: Task ID

        Returns:
            Task state or None if not found
        """
        return self._states.get(task_id)

    def get_result(self, task_id: str) -> ParallelExecutionResult | None:
        """Get result of a task.

        Args:
            task_id: Task ID

        Returns:
            Execution result or None if not found
        """
        return self._results.get(task_id)

    def list_active(self) -> list[str]:
        """List IDs of active tasks.

        Returns:
            List of task IDs in RUNNING state
        """
        return [
            task_id
            for task_id, state in self._states.items()
            if state == TaskExecutionState.RUNNING
        ]

    def list_completed(self) -> list[str]:
        """List IDs of completed tasks.

        Returns:
            List of task IDs in COMPLETED state
        """
        return [
            task_id
            for task_id, state in self._states.items()
            if state == TaskExecutionState.COMPLETED
        ]

    def list_failed(self) -> list[str]:
        """List IDs of failed tasks.

        Returns:
            List of task IDs in FAILED state
        """
        return [
            task_id
            for task_id, state in self._states.items()
            if state == TaskExecutionState.FAILED
        ]
