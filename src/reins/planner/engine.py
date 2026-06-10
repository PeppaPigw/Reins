from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from reins.planner.types import (
    ExecutionPlan,
    ExecutionSlot,
    PlannerStats,
    PlanOptimization,
    PlanTask,
    SchedulingStrategy,
    TaskPriority,
    TaskState,
)


class ExecutionPlanner:
    """Decomposes goals into optimal execution DAGs with parallelism detection.

    Performs topological sorting, critical path analysis, parallelism
    extraction, and resource-aware scheduling to minimize total execution time.
    """

    def __init__(self, strategy: SchedulingStrategy = SchedulingStrategy.BALANCED) -> None:
        self._strategy = strategy
        self._plans: list[ExecutionPlan] = []
        self._optimizations: list[PlanOptimization] = []

    def create_plan(self, goal: str, tasks: list[PlanTask]) -> ExecutionPlan:
        validated = self._validate_dependencies(tasks)
        order = self._topological_sort(validated)
        slots = self._schedule(order, validated)

        total_duration = sum(s.estimated_duration_ms for s in slots)
        total_cost = sum(t.estimated_cost for t in validated)
        critical_path = self._critical_path_length(validated)
        sequential_duration = sum(t.estimated_duration_ms for t in validated)
        parallelism = sequential_duration / total_duration if total_duration > 0 else 1.0

        plan = ExecutionPlan(
            goal=goal,
            tasks=tuple(validated),
            slots=tuple(slots),
            total_estimated_duration_ms=total_duration,
            total_estimated_cost=total_cost,
            critical_path_length=critical_path,
            parallelism_factor=parallelism,
            strategy=self._strategy,
        )
        self._plans.append(plan)
        return plan

    def optimize(self, plan: ExecutionPlan) -> PlanOptimization:
        optimizations: list[str] = []
        tasks = list(plan.tasks)

        parallel_groups = self._find_parallel_groups(tasks)
        max_group_size = max((len(g) for g in parallel_groups), default=0)
        if max_group_size > 1:
            optimizations.append(f"Parallelized {max_group_size} independent tasks")

        reordered = self._priority_reorder(tasks)
        if reordered != tasks:
            optimizations.append("Reordered by priority within dependency constraints")

        optimized_slots = self._schedule(self._topological_sort(reordered), reordered)
        optimized_duration = sum(s.estimated_duration_ms for s in optimized_slots)

        speedup = plan.total_estimated_duration_ms / optimized_duration if optimized_duration > 0 else 1.0

        opt = PlanOptimization(
            plan_id=plan.plan_id,
            original_duration_ms=plan.total_estimated_duration_ms,
            optimized_duration_ms=optimized_duration,
            speedup_factor=speedup,
            optimizations_applied=tuple(optimizations),
        )
        self._optimizations.append(opt)
        return opt

    def get_ready_tasks(self, plan: ExecutionPlan, completed: set[str] | None = None) -> list[PlanTask]:
        done = completed or set()
        ready = []
        for task in plan.tasks:
            if task.task_id in done:
                continue
            if task.state != TaskState.PENDING:
                continue
            if all(dep in done for dep in task.depends_on):
                ready.append(task)
        return ready

    def get_critical_path(self, plan: ExecutionPlan) -> list[PlanTask]:
        task_map = {t.task_id: t for t in plan.tasks}
        longest_path: list[PlanTask] = []

        def dfs(task_id: str, path: list[str]) -> None:
            nonlocal longest_path
            task = task_map.get(task_id)
            if not task:
                return
            current_path = path + [task_id]

            dependents = [t for t in plan.tasks if task_id in t.depends_on]
            if not dependents:
                if len(current_path) > len(longest_path):
                    longest_path = [task_map[tid] for tid in current_path]
            else:
                for dep in dependents:
                    dfs(dep.task_id, current_path)

        roots = [t for t in plan.tasks if not t.depends_on]
        for root in roots:
            dfs(root.task_id, [])

        return longest_path

    def estimate_completion(self, plan: ExecutionPlan, completed: set[str] | None = None) -> float:
        done = completed or set()
        remaining = [t for t in plan.tasks if t.task_id not in done]
        if not remaining:
            return 0.0

        remaining_slots = self._schedule(
            self._topological_sort(remaining),
            remaining,
        )
        return sum(s.estimated_duration_ms for s in remaining_slots)

    def get_stats(self) -> PlannerStats:
        if not self._plans:
            return PlannerStats()

        total_tasks = sum(len(p.tasks) for p in self._plans)
        avg_parallelism = sum(p.parallelism_factor for p in self._plans) / len(self._plans)
        avg_speedup = (
            sum(o.speedup_factor for o in self._optimizations) / len(self._optimizations)
            if self._optimizations else 1.0
        )

        by_strategy: dict[str, int] = defaultdict(int)
        for p in self._plans:
            by_strategy[p.strategy.value] += 1

        return PlannerStats(
            total_plans=len(self._plans),
            total_tasks=total_tasks,
            avg_parallelism=avg_parallelism,
            avg_speedup=avg_speedup,
            by_strategy=dict(by_strategy),
        )

    def _validate_dependencies(self, tasks: list[PlanTask]) -> list[PlanTask]:
        task_ids = {t.task_id for t in tasks}
        validated = []
        for task in tasks:
            valid_deps = tuple(d for d in task.depends_on if d in task_ids)
            if valid_deps != task.depends_on:
                validated.append(PlanTask(
                    task_id=task.task_id,
                    name=task.name,
                    description=task.description,
                    priority=task.priority,
                    state=task.state,
                    depends_on=valid_deps,
                    estimated_duration_ms=task.estimated_duration_ms,
                    estimated_cost=task.estimated_cost,
                    resource_requirements=task.resource_requirements,
                    parallelizable=task.parallelizable,
                    retryable=task.retryable,
                    max_retries=task.max_retries,
                    metadata=task.metadata,
                ))
            else:
                validated.append(task)
        return validated

    def _topological_sort(self, tasks: list[PlanTask]) -> list[str]:
        task_map = {t.task_id: t for t in tasks}
        in_degree: dict[str, int] = {t.task_id: 0 for t in tasks}
        adjacency: dict[str, list[str]] = defaultdict(list)

        for task in tasks:
            for dep in task.depends_on:
                if dep in task_map:
                    adjacency[dep].append(task.task_id)
                    in_degree[task.task_id] += 1

        queue = deque(
            sorted(
                [tid for tid, deg in in_degree.items() if deg == 0],
                key=lambda tid: self._priority_value(task_map[tid].priority),
            )
        )
        order: list[str] = []

        while queue:
            current = queue.popleft()
            order.append(current)
            for neighbor in sorted(
                adjacency[current],
                key=lambda tid: self._priority_value(task_map[tid].priority),
            ):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return order

    def _schedule(self, order: list[str], tasks: list[PlanTask]) -> list[ExecutionSlot]:
        task_map = {t.task_id: t for t in tasks}
        if not order:
            return []

        slots: list[ExecutionSlot] = []
        scheduled: set[str] = set()
        remaining = list(order)

        while remaining:
            batch: list[str] = []
            for tid in remaining:
                task = task_map[tid]
                if all(d in scheduled for d in task.depends_on):
                    if task.parallelizable or not batch:
                        batch.append(tid)

            if not batch:
                batch = [remaining[0]]

            max_duration = max(task_map[tid].estimated_duration_ms for tid in batch)
            parallel = len(batch) > 1

            slots.append(ExecutionSlot(
                task_ids=tuple(batch),
                estimated_duration_ms=max_duration,
                parallel=parallel,
            ))

            for tid in batch:
                scheduled.add(tid)
                remaining.remove(tid)

        return slots

    def _find_parallel_groups(self, tasks: list[PlanTask]) -> list[list[PlanTask]]:
        task_map = {t.task_id: t for t in tasks}
        groups: list[list[PlanTask]] = []
        visited: set[str] = set()

        for task in tasks:
            if task.task_id in visited:
                continue
            group = [task]
            visited.add(task.task_id)

            for other in tasks:
                if other.task_id in visited:
                    continue
                if not self._has_dependency(task, other, task_map) and not self._has_dependency(other, task, task_map):
                    group.append(other)
                    visited.add(other.task_id)

            groups.append(group)

        return groups

    def _has_dependency(self, a: PlanTask, b: PlanTask, task_map: dict[str, PlanTask]) -> bool:
        visited: set[str] = set()
        queue = deque(a.depends_on)
        while queue:
            dep_id = queue.popleft()
            if dep_id == b.task_id:
                return True
            if dep_id in visited:
                continue
            visited.add(dep_id)
            dep_task = task_map.get(dep_id)
            if dep_task:
                queue.extend(dep_task.depends_on)
        return False

    def _critical_path_length(self, tasks: list[PlanTask]) -> int:
        task_map = {t.task_id: t for t in tasks}
        memo: dict[str, int] = {}

        def depth(task_id: str) -> int:
            if task_id in memo:
                return memo[task_id]
            task = task_map.get(task_id)
            if not task or not task.depends_on:
                memo[task_id] = 1
                return 1
            max_dep = max(depth(d) for d in task.depends_on if d in task_map)
            memo[task_id] = 1 + max_dep
            return memo[task_id]

        if not tasks:
            return 0
        return max(depth(t.task_id) for t in tasks)

    def _priority_reorder(self, tasks: list[PlanTask]) -> list[PlanTask]:
        return sorted(tasks, key=lambda t: self._priority_value(t.priority))

    def _priority_value(self, priority: TaskPriority) -> int:
        values = {
            TaskPriority.CRITICAL: 0,
            TaskPriority.HIGH: 1,
            TaskPriority.NORMAL: 2,
            TaskPriority.LOW: 3,
            TaskPriority.BACKGROUND: 4,
        }
        return values.get(priority, 2)
