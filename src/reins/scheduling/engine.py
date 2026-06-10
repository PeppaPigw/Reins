from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from reins.scheduling.types import (
    ResourcePool,
    ScheduledTask,
    ScheduleSlot,
    SchedulingStats,
    SchedulingStrategy,
    TaskPriority,
    TaskState,
)

_PRIORITY_WEIGHTS = {
    TaskPriority.CRITICAL: 100,
    TaskPriority.HIGH: 75,
    TaskPriority.MEDIUM: 50,
    TaskPriority.LOW: 25,
    TaskPriority.BACKGROUND: 10,
}


class Scheduler:
    """Intelligent task scheduling with priority queues and resource constraints.

    Manages task lifecycle, resource pools, dependency resolution,
    deadline-aware scheduling, and optimal agent assignment.
    """

    def __init__(self, strategy: SchedulingStrategy = SchedulingStrategy.PRIORITY) -> None:
        self._tasks: dict[str, ScheduledTask] = {}
        self._pools: dict[str, ResourcePool] = {}
        self._slots: list[ScheduleSlot] = []
        self._strategy = strategy
        self._agents: set[str] = set()

    def submit_task(self, name: str, priority: TaskPriority = TaskPriority.MEDIUM,
                    estimated_duration_ms: int = 1000,
                    deadline: datetime | None = None,
                    dependencies: list[str] | None = None) -> ScheduledTask:
        task = ScheduledTask(
            name=name,
            priority=priority,
            estimated_duration_ms=estimated_duration_ms,
            deadline=deadline,
            dependencies=tuple(dependencies or []),
        )
        self._tasks[task.task_id] = task
        return task

    def get_task(self, task_id: str) -> ScheduledTask | None:
        return self._tasks.get(task_id)

    def cancel_task(self, task_id: str) -> ScheduledTask | None:
        task = self._tasks.get(task_id)
        if not task or task.state in (TaskState.COMPLETED, TaskState.CANCELLED):
            return task
        updated = task.model_copy(update={"state": TaskState.CANCELLED})
        self._tasks[task_id] = updated
        return updated

    def register_agent(self, agent_id: str) -> None:
        self._agents.add(agent_id)

    def get_ready_tasks(self) -> list[ScheduledTask]:
        ready = []
        for task in self._tasks.values():
            if task.state != TaskState.PENDING:
                continue
            if self._dependencies_met(task):
                ready.append(task)
        return self._sort_by_strategy(ready)

    def assign_task(self, task_id: str, agent_id: str) -> ScheduleSlot | None:
        task = self._tasks.get(task_id)
        if not task or task.state != TaskState.PENDING:
            return None

        now = datetime.now(UTC)
        self._tasks[task_id] = task.model_copy(update={
            "state": TaskState.RUNNING,
            "assigned_to": agent_id,
            "started_at": now,
        })

        slot = ScheduleSlot(task_id=task_id, agent_id=agent_id, start_time=now)
        self._slots.append(slot)
        return slot

    def complete_task(self, task_id: str) -> ScheduledTask | None:
        task = self._tasks.get(task_id)
        if not task or task.state != TaskState.RUNNING:
            return task
        updated = task.model_copy(update={
            "state": TaskState.COMPLETED,
            "completed_at": datetime.now(UTC),
        })
        self._tasks[task_id] = updated
        return updated

    def fail_task(self, task_id: str) -> ScheduledTask | None:
        task = self._tasks.get(task_id)
        if not task or task.state != TaskState.RUNNING:
            return task
        updated = task.model_copy(update={
            "state": TaskState.FAILED,
            "completed_at": datetime.now(UTC),
        })
        self._tasks[task_id] = updated
        return updated

    def create_pool(self, name: str, capacity: int = 10) -> ResourcePool:
        pool = ResourcePool(name=name, capacity=capacity)
        self._pools[pool.pool_id] = pool
        return pool

    def allocate_resource(self, pool_id: str, count: int = 1) -> bool:
        pool = self._pools.get(pool_id)
        if not pool:
            return False
        available = pool.capacity - pool.allocated - pool.reserved
        if count > available:
            return False
        self._pools[pool_id] = pool.model_copy(
            update={"allocated": pool.allocated + count}
        )
        return True

    def release_resource(self, pool_id: str, count: int = 1) -> bool:
        pool = self._pools.get(pool_id)
        if not pool or pool.allocated < count:
            return False
        self._pools[pool_id] = pool.model_copy(
            update={"allocated": pool.allocated - count}
        )
        return True

    def reserve_resource(self, pool_id: str, count: int = 1) -> bool:
        pool = self._pools.get(pool_id)
        if not pool:
            return False
        available = pool.capacity - pool.allocated - pool.reserved
        if count > available:
            return False
        self._pools[pool_id] = pool.model_copy(
            update={"reserved": pool.reserved + count}
        )
        return True

    def get_overdue_tasks(self) -> list[ScheduledTask]:
        now = datetime.now(UTC)
        overdue = []
        for task in self._tasks.values():
            if task.deadline and task.state in (TaskState.PENDING, TaskState.RUNNING):
                if now > task.deadline:
                    overdue.append(task)
        return overdue

    def get_agent_load(self, agent_id: str) -> int:
        return sum(
            1 for t in self._tasks.values()
            if t.assigned_to == agent_id and t.state == TaskState.RUNNING
        )

    def get_stats(self) -> SchedulingStats:
        by_priority: dict[str, int] = defaultdict(int)
        by_state: dict[str, int] = defaultdict(int)

        for task in self._tasks.values():
            by_priority[task.priority.value] += 1
            by_state[task.state.value] += 1

        pending = by_state.get(TaskState.PENDING.value, 0)
        running = by_state.get(TaskState.RUNNING.value, 0)
        completed = by_state.get(TaskState.COMPLETED.value, 0)
        failed = by_state.get(TaskState.FAILED.value, 0)

        return SchedulingStats(
            total_tasks=len(self._tasks),
            pending_tasks=pending,
            running_tasks=running,
            completed_tasks=completed,
            failed_tasks=failed,
            by_priority=dict(by_priority),
            by_state=dict(by_state),
        )

    def _dependencies_met(self, task: ScheduledTask) -> bool:
        for dep_id in task.dependencies:
            dep = self._tasks.get(dep_id)
            if not dep or dep.state != TaskState.COMPLETED:
                return False
        return True

    def _sort_by_strategy(self, tasks: list[ScheduledTask]) -> list[ScheduledTask]:
        if self._strategy == SchedulingStrategy.FIFO:
            return sorted(tasks, key=lambda t: t.created_at)
        elif self._strategy == SchedulingStrategy.PRIORITY:
            return sorted(tasks, key=lambda t: _PRIORITY_WEIGHTS.get(t.priority, 0), reverse=True)
        elif self._strategy == SchedulingStrategy.SHORTEST_FIRST:
            return sorted(tasks, key=lambda t: t.estimated_duration_ms)
        elif self._strategy == SchedulingStrategy.DEADLINE_FIRST:
            def deadline_key(t: ScheduledTask) -> datetime:
                return t.deadline if t.deadline else datetime.max.replace(tzinfo=UTC)
            return sorted(tasks, key=deadline_key)
        return tasks
