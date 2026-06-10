from __future__ import annotations

from collections import defaultdict, deque
from datetime import UTC, datetime

from reins.goals.types import (
    DecompositionStrategy,
    Goal,
    GoalPriority,
    GoalProgress,
    GoalStats,
    GoalStatus,
    GoalTree,
)


class GoalDecomposer:
    """Hierarchical goal breakdown with dependency tracking and progress monitoring.

    Manages goal trees, tracks completion, detects blocked goals,
    and computes critical paths through dependency graphs.
    """

    def __init__(self) -> None:
        self._goals: dict[str, Goal] = {}
        self._children: dict[str, list[str]] = defaultdict(list)

    def add_goal(self, goal: Goal) -> Goal:
        self._goals[goal.goal_id] = goal
        if goal.parent_id:
            self._children[goal.parent_id].append(goal.goal_id)
        return goal

    def get_goal(self, goal_id: str) -> Goal | None:
        return self._goals.get(goal_id)

    def update_status(self, goal_id: str, status: GoalStatus) -> Goal | None:
        goal = self._goals.get(goal_id)
        if not goal:
            return None
        completed_at = datetime.now(UTC) if status == GoalStatus.COMPLETED else goal.completed_at
        updated = Goal(
            goal_id=goal.goal_id,
            name=goal.name,
            description=goal.description,
            priority=goal.priority,
            status=status,
            parent_id=goal.parent_id,
            dependencies=goal.dependencies,
            strategy=goal.strategy,
            acceptance_criteria=goal.acceptance_criteria,
            metadata=goal.metadata,
            created_at=goal.created_at,
            completed_at=completed_at,
        )
        self._goals[goal_id] = updated
        return updated

    def get_children(self, goal_id: str) -> list[Goal]:
        child_ids = self._children.get(goal_id, [])
        return [self._goals[cid] for cid in child_ids if cid in self._goals]

    def get_progress(self, goal_id: str) -> GoalProgress:
        goal = self._goals.get(goal_id)
        if not goal:
            return GoalProgress(goal_id=goal_id)

        children = self._children.get(goal_id, [])
        if not children:
            ratio = 1.0 if goal.status == GoalStatus.COMPLETED else 0.0
            return GoalProgress(goal_id=goal_id, completion_ratio=ratio)

        total = len(children)
        completed = sum(
            1 for cid in children
            if cid in self._goals and self._goals[cid].status == GoalStatus.COMPLETED
        )
        blocked = sum(
            1 for cid in children
            if cid in self._goals and self._goals[cid].status == GoalStatus.BLOCKED
        )
        ratio = completed / total if total else 0.0
        depth = self._compute_depth(goal_id)

        return GoalProgress(
            goal_id=goal_id,
            completion_ratio=ratio,
            subgoals_total=total,
            subgoals_completed=completed,
            subgoals_blocked=blocked,
            depth=depth,
        )

    def get_blocked_goals(self) -> list[Goal]:
        blocked = []
        for goal in self._goals.values():
            if goal.status in (GoalStatus.COMPLETED, GoalStatus.FAILED, GoalStatus.ABANDONED):
                continue
            if goal.dependencies:
                all_met = all(
                    self._goals.get(dep_id) and self._goals[dep_id].status == GoalStatus.COMPLETED
                    for dep_id in goal.dependencies
                )
                if not all_met:
                    blocked.append(goal)
        return blocked

    def get_ready_goals(self) -> list[Goal]:
        ready = []
        for goal in self._goals.values():
            if goal.status != GoalStatus.PENDING:
                continue
            if goal.dependencies:
                all_met = all(
                    self._goals.get(dep_id) and self._goals[dep_id].status == GoalStatus.COMPLETED
                    for dep_id in goal.dependencies
                )
                if not all_met:
                    continue
            ready.append(goal)
        return ready

    def get_tree(self, root_id: str) -> GoalTree:
        if root_id not in self._goals:
            return GoalTree(root_id=root_id)

        all_ids = self._collect_descendants(root_id)
        all_ids.add(root_id)
        total = len(all_ids)
        completed = sum(
            1 for gid in all_ids
            if gid in self._goals and self._goals[gid].status == GoalStatus.COMPLETED
        )
        ratio = completed / total if total else 0.0
        max_depth = self._compute_depth(root_id)
        critical_path = self._find_critical_path(root_id)

        return GoalTree(
            root_id=root_id,
            total_goals=total,
            max_depth=max_depth,
            completion_ratio=ratio,
            critical_path=tuple(critical_path),
        )

    def remove_goal(self, goal_id: str) -> bool:
        if goal_id not in self._goals:
            return False
        goal = self._goals.pop(goal_id)
        if goal.parent_id and goal.parent_id in self._children:
            children = self._children[goal.parent_id]
            if goal_id in children:
                children.remove(goal_id)
        for child_id in self._children.pop(goal_id, []):
            if child_id in self._goals:
                child = self._goals[child_id]
                self._goals[child_id] = Goal(
                    goal_id=child.goal_id,
                    name=child.name,
                    description=child.description,
                    priority=child.priority,
                    status=child.status,
                    parent_id=None,
                    dependencies=child.dependencies,
                    strategy=child.strategy,
                    acceptance_criteria=child.acceptance_criteria,
                    metadata=child.metadata,
                    created_at=child.created_at,
                    completed_at=child.completed_at,
                )
        return True

    def get_stats(self) -> GoalStats:
        if not self._goals:
            return GoalStats()

        by_priority: dict[str, int] = defaultdict(int)
        by_status: dict[str, int] = defaultdict(int)
        for g in self._goals.values():
            by_priority[g.priority.value] += 1
            by_status[g.status.value] += 1

        active = sum(1 for g in self._goals.values() if g.status == GoalStatus.ACTIVE)
        completed = sum(1 for g in self._goals.values() if g.status == GoalStatus.COMPLETED)
        blocked = len(self.get_blocked_goals())
        failed = sum(1 for g in self._goals.values() if g.status == GoalStatus.FAILED)

        completions = [
            self.get_progress(gid).completion_ratio
            for gid in self._goals
        ]
        avg_completion = sum(completions) / len(completions) if completions else 0.0

        return GoalStats(
            total_goals=len(self._goals),
            active_goals=active,
            completed_goals=completed,
            blocked_goals=blocked,
            failed_goals=failed,
            avg_completion=avg_completion,
            by_priority=dict(by_priority),
            by_status=dict(by_status),
        )

    def _collect_descendants(self, goal_id: str) -> set[str]:
        descendants: set[str] = set()
        queue = deque(self._children.get(goal_id, []))
        while queue:
            current = queue.popleft()
            if current in descendants:
                continue
            descendants.add(current)
            queue.extend(self._children.get(current, []))
        return descendants

    def _compute_depth(self, goal_id: str) -> int:
        children = self._children.get(goal_id, [])
        if not children:
            return 0
        return 1 + max(self._compute_depth(cid) for cid in children)

    def _find_critical_path(self, root_id: str) -> list[str]:
        children = self._children.get(root_id, [])
        if not children:
            return [root_id]

        longest: list[str] = []
        for child_id in children:
            child_path = self._find_critical_path(child_id)
            if len(child_path) > len(longest):
                longest = child_path
        return [root_id] + longest
