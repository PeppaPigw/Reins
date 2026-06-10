from __future__ import annotations

from collections import defaultdict, deque

from reins.scheduler.types import (
    Schedule,
    ScheduledTask,
    SchedulerStats,
    SchedulingPolicy,
    TaskPriority,
    TaskState,
)

_PRIORITY_WEIGHTS = {
    TaskPriority.CRITICAL: 5,
    TaskPriority.HIGH: 4,
    TaskPriority.NORMAL: 3,
    TaskPriority.LOW: 2,
    TaskPriority.BACKGROUND: 1,
}


class TaskScheduler:
    """DAG-aware task scheduler with critical path analysis and resource constraints.

    Computes optimal execution order respecting dependencies, identifies
    the critical path, and supports multiple scheduling policies.
    """

    def __init__(self, policy: SchedulingPolicy = SchedulingPolicy.CRITICAL_PATH,
                 max_parallelism: int = 4) -> None:
        self._policy = policy
        self._max_parallelism = max_parallelism
        self._tasks: dict[str, ScheduledTask] = {}

    def add_task(self, name: str, priority: TaskPriority = TaskPriority.NORMAL,
                 estimated_duration_ms: float = 1000.0,
                 dependencies: list[str] | None = None,
                 resource_requirements: dict[str, float] | None = None) -> ScheduledTask:
        task = ScheduledTask(
            name=name, priority=priority,
            estimated_duration_ms=estimated_duration_ms,
            dependencies=tuple(dependencies or []),
            resource_requirements=resource_requirements or {},
        )
        self._tasks[task.task_id] = task
        self._update_states()
        return self._tasks[task.task_id]

    def get_task(self, task_id: str) -> ScheduledTask | None:
        return self._tasks.get(task_id)

    def get_ready_tasks(self) -> list[ScheduledTask]:
        return [t for t in self._tasks.values() if t.state == TaskState.READY]

    def start_task(self, task_id: str, assigned_to: str = "") -> ScheduledTask | None:
        task = self._tasks.get(task_id)
        if not task or task.state != TaskState.READY:
            return None
        updated = ScheduledTask(
            task_id=task.task_id, name=task.name, priority=task.priority,
            state=TaskState.RUNNING, estimated_duration_ms=task.estimated_duration_ms,
            dependencies=task.dependencies, assigned_to=assigned_to,
            resource_requirements=task.resource_requirements,
            metadata=task.metadata, created_at=task.created_at,
        )
        self._tasks[task_id] = updated
        return updated

    def complete_task(self, task_id: str, actual_duration_ms: float = 0.0) -> ScheduledTask | None:
        task = self._tasks.get(task_id)
        if not task or task.state != TaskState.RUNNING:
            return None
        updated = ScheduledTask(
            task_id=task.task_id, name=task.name, priority=task.priority,
            state=TaskState.COMPLETED, estimated_duration_ms=task.estimated_duration_ms,
            actual_duration_ms=actual_duration_ms, dependencies=task.dependencies,
            assigned_to=task.assigned_to, resource_requirements=task.resource_requirements,
            metadata=task.metadata, created_at=task.created_at,
        )
        self._tasks[task_id] = updated
        self._update_states()
        return updated

    def fail_task(self, task_id: str) -> ScheduledTask | None:
        task = self._tasks.get(task_id)
        if not task:
            return None
        updated = ScheduledTask(
            task_id=task.task_id, name=task.name, priority=task.priority,
            state=TaskState.FAILED, estimated_duration_ms=task.estimated_duration_ms,
            dependencies=task.dependencies, assigned_to=task.assigned_to,
            resource_requirements=task.resource_requirements,
            metadata=task.metadata, created_at=task.created_at,
        )
        self._tasks[task_id] = updated
        return updated

    def compute_schedule(self) -> Schedule:
        order = self._topological_sort()
        critical_path = self._find_critical_path()
        makespan = sum(
            self._tasks[tid].estimated_duration_ms for tid in critical_path
        ) if critical_path else 0.0

        return Schedule(
            task_order=tuple(order),
            critical_path=tuple(critical_path),
            makespan_ms=makespan,
            parallelism=self._max_parallelism,
        )

    def get_critical_path(self) -> list[str]:
        return self._find_critical_path()

    def get_blocked_tasks(self) -> list[ScheduledTask]:
        return [t for t in self._tasks.values() if t.state == TaskState.BLOCKED]

    def get_next_tasks(self, n: int = 1) -> list[ScheduledTask]:
        ready = self.get_ready_tasks()
        if self._policy == SchedulingPolicy.PRIORITY:
            ready.sort(key=lambda t: -_PRIORITY_WEIGHTS.get(t.priority, 3))
        elif self._policy == SchedulingPolicy.SHORTEST_FIRST:
            ready.sort(key=lambda t: t.estimated_duration_ms)
        elif self._policy == SchedulingPolicy.CRITICAL_PATH:
            cp_set = set(self._find_critical_path())
            ready.sort(key=lambda t: (t.task_id not in cp_set, -_PRIORITY_WEIGHTS.get(t.priority, 3)))
        return ready[:n]

    def get_stats(self) -> SchedulerStats:
        by_priority: dict[str, int] = defaultdict(int)
        for t in self._tasks.values():
            by_priority[t.priority.value] += 1

        completed = [t for t in self._tasks.values() if t.state == TaskState.COMPLETED]
        running = sum(1 for t in self._tasks.values() if t.state == TaskState.RUNNING)
        blocked = sum(1 for t in self._tasks.values() if t.state == TaskState.BLOCKED)

        durations = [t.actual_duration_ms for t in completed if t.actual_duration_ms > 0]
        avg_duration = sum(durations) / len(durations) if durations else 0.0

        cp = self._find_critical_path()
        total_work = sum(t.estimated_duration_ms for t in self._tasks.values())
        cp_work = sum(self._tasks[tid].estimated_duration_ms for tid in cp) if cp else 0.0
        parallelism_factor = total_work / cp_work if cp_work > 0 else 1.0

        return SchedulerStats(
            total_tasks=len(self._tasks),
            completed=len(completed),
            running=running,
            blocked=blocked,
            avg_duration_ms=avg_duration,
            critical_path_length=len(cp),
            parallelism_factor=parallelism_factor,
            by_priority=dict(by_priority),
        )

    def _update_states(self) -> None:
        for task_id, task in self._tasks.items():
            if task.state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.RUNNING):
                continue
            deps_met = all(
                self._tasks.get(dep, ScheduledTask(name="")).state == TaskState.COMPLETED
                for dep in task.dependencies
                if dep in self._tasks
            )
            if deps_met:
                if task.state != TaskState.READY:
                    updated = ScheduledTask(
                        task_id=task.task_id, name=task.name, priority=task.priority,
                        state=TaskState.READY, estimated_duration_ms=task.estimated_duration_ms,
                        dependencies=task.dependencies, resource_requirements=task.resource_requirements,
                        metadata=task.metadata, created_at=task.created_at,
                    )
                    self._tasks[task_id] = updated
            else:
                if task.state != TaskState.BLOCKED:
                    updated = ScheduledTask(
                        task_id=task.task_id, name=task.name, priority=task.priority,
                        state=TaskState.BLOCKED, estimated_duration_ms=task.estimated_duration_ms,
                        dependencies=task.dependencies, resource_requirements=task.resource_requirements,
                        metadata=task.metadata, created_at=task.created_at,
                    )
                    self._tasks[task_id] = updated

    def _topological_sort(self) -> list[str]:
        in_degree: dict[str, int] = {tid: 0 for tid in self._tasks}
        for task in self._tasks.values():
            for dep in task.dependencies:
                if dep in self._tasks:
                    in_degree[task.task_id] = in_degree.get(task.task_id, 0) + 1

        queue = deque(tid for tid, deg in in_degree.items() if deg == 0)
        order: list[str] = []

        while queue:
            tid = queue.popleft()
            order.append(tid)
            for task in self._tasks.values():
                if tid in task.dependencies:
                    in_degree[task.task_id] -= 1
                    if in_degree[task.task_id] == 0:
                        queue.append(task.task_id)

        return order

    def _find_critical_path(self) -> list[str]:
        if not self._tasks:
            return []

        longest_path: dict[str, float] = {}
        predecessor: dict[str, str | None] = {}
        order = self._topological_sort()

        for tid in order:
            task = self._tasks[tid]
            max_incoming = 0.0
            best_pred = None
            for dep in task.dependencies:
                if dep in longest_path:
                    if longest_path[dep] > max_incoming:
                        max_incoming = longest_path[dep]
                        best_pred = dep
            longest_path[tid] = max_incoming + task.estimated_duration_ms
            predecessor[tid] = best_pred

        if not longest_path:
            return []

        end_task = max(longest_path, key=lambda t: longest_path[t])
        path: list[str] = []
        current: str | None = end_task
        while current is not None:
            path.append(current)
            current = predecessor.get(current)
        path.reverse()
        return path
