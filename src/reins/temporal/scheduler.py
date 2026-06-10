from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from reins.temporal.types import (
    Deadline,
    EscalationEvent,
    EscalationLevel,
    Priority,
    ScheduledTask,
    ScheduleReport,
    ScheduleStatus,
    SLA,
)


_PRIORITY_WEIGHTS = {
    Priority.CRITICAL: 4,
    Priority.HIGH: 3,
    Priority.MEDIUM: 2,
    Priority.LOW: 1,
}


class TemporalScheduler:
    """Time-aware task scheduling with deadlines, SLAs, and automatic escalation.

    Provides deadline tracking, priority-based ordering, dependency resolution,
    SLA monitoring, and automatic escalation when tasks approach or exceed
    their time budgets.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, ScheduledTask] = {}
        self._escalations: list[EscalationEvent] = []

    def schedule(self, task: ScheduledTask) -> ScheduledTask:
        scheduled = ScheduledTask(
            task_id=task.task_id,
            name=task.name,
            agent_id=task.agent_id,
            deadline=task.deadline,
            dependencies=task.dependencies,
            priority=task.priority,
            status=ScheduleStatus.SCHEDULED,
            scheduled_at=datetime.now(UTC),
            started_at=task.started_at,
            completed_at=task.completed_at,
            escalation_level=task.escalation_level,
            metadata=task.metadata,
        )
        self._tasks[scheduled.task_id] = scheduled
        return scheduled

    def start(self, task_id: str) -> ScheduledTask:
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Unknown task: {task_id}")
        if task.status not in (ScheduleStatus.PENDING, ScheduleStatus.SCHEDULED):
            raise ValueError(f"Cannot start task in status: {task.status.value}")

        for dep_id in task.dependencies:
            dep = self._tasks.get(dep_id)
            if dep and dep.status != ScheduleStatus.COMPLETED:
                raise ValueError(f"Dependency {dep_id} not completed")

        updated = ScheduledTask(
            task_id=task.task_id,
            name=task.name,
            agent_id=task.agent_id,
            deadline=task.deadline,
            dependencies=task.dependencies,
            priority=task.priority,
            status=ScheduleStatus.RUNNING,
            scheduled_at=task.scheduled_at,
            started_at=datetime.now(UTC),
            completed_at=None,
            escalation_level=task.escalation_level,
            metadata=task.metadata,
        )
        self._tasks[task_id] = updated
        return updated

    def complete(self, task_id: str) -> ScheduledTask:
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Unknown task: {task_id}")

        updated = ScheduledTask(
            task_id=task.task_id,
            name=task.name,
            agent_id=task.agent_id,
            deadline=task.deadline,
            dependencies=task.dependencies,
            priority=task.priority,
            status=ScheduleStatus.COMPLETED,
            scheduled_at=task.scheduled_at,
            started_at=task.started_at,
            completed_at=datetime.now(UTC),
            escalation_level=task.escalation_level,
            metadata=task.metadata,
        )
        self._tasks[task_id] = updated
        return updated

    def fail(self, task_id: str) -> ScheduledTask:
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Unknown task: {task_id}")

        updated = ScheduledTask(
            task_id=task.task_id,
            name=task.name,
            agent_id=task.agent_id,
            deadline=task.deadline,
            dependencies=task.dependencies,
            priority=task.priority,
            status=ScheduleStatus.FAILED,
            scheduled_at=task.scheduled_at,
            started_at=task.started_at,
            completed_at=datetime.now(UTC),
            escalation_level=task.escalation_level,
            metadata=task.metadata,
        )
        self._tasks[task_id] = updated
        return updated

    def check_deadlines(self, now: datetime | None = None) -> list[EscalationEvent]:
        now = now or datetime.now(UTC)
        new_escalations: list[EscalationEvent] = []

        for task in self._tasks.values():
            if task.status in (ScheduleStatus.COMPLETED, ScheduleStatus.FAILED, ScheduleStatus.TIMED_OUT):
                continue
            if not task.deadline:
                continue

            remaining = (task.deadline.due_at - now).total_seconds()
            total_budget = self._get_total_budget(task)

            if remaining <= 0:
                event = self._escalate(task, EscalationLevel.BLOCKED, now, remaining, total_budget)
                new_escalations.append(event)
                self._update_task_escalation(task.task_id, EscalationLevel.BLOCKED)
            elif task.deadline.sla:
                elapsed = total_budget - remaining
                pct = elapsed / total_budget if total_budget > 0 else 1.0
                level = self._compute_escalation_level(pct, task.deadline.sla)
                if level != EscalationLevel.NONE and level != task.escalation_level:
                    event = self._escalate(task, level, now, remaining, total_budget)
                    new_escalations.append(event)
                    self._update_task_escalation(task.task_id, level)

        self._escalations.extend(new_escalations)
        return new_escalations

    def get_priority_queue(self) -> list[ScheduledTask]:
        runnable = [
            t for t in self._tasks.values()
            if t.status in (ScheduleStatus.PENDING, ScheduleStatus.SCHEDULED)
            and self._dependencies_met(t)
        ]

        def sort_key(task: ScheduledTask) -> tuple[int, float]:
            priority_weight = -_PRIORITY_WEIGHTS.get(task.priority, 0)
            deadline_urgency = 0.0
            if task.deadline:
                remaining = (task.deadline.due_at - datetime.now(UTC)).total_seconds()
                deadline_urgency = -1.0 / max(remaining, 1.0)
            return (priority_weight, deadline_urgency)

        runnable.sort(key=sort_key)
        return runnable

    def get_report(self, now: datetime | None = None) -> ScheduleReport:
        now = now or datetime.now(UTC)
        on_track = 0
        at_risk = 0
        overdue = 0
        completed = 0

        for task in self._tasks.values():
            if task.status == ScheduleStatus.COMPLETED:
                completed += 1
            elif task.status in (ScheduleStatus.TIMED_OUT, ScheduleStatus.FAILED):
                overdue += 1
            elif task.deadline:
                remaining = (task.deadline.due_at - now).total_seconds()
                if remaining <= 0:
                    overdue += 1
                elif task.deadline.sla:
                    total = task.deadline.sla.max_duration_seconds
                    elapsed = total - remaining
                    if elapsed / total >= task.deadline.sla.warning_threshold_pct:
                        at_risk += 1
                    else:
                        on_track += 1
                else:
                    on_track += 1
            else:
                on_track += 1

        return ScheduleReport(
            total_tasks=len(self._tasks),
            on_track=on_track,
            at_risk=at_risk,
            overdue=overdue,
            completed=completed,
            escalations=tuple(self._escalations),
        )

    def get_task(self, task_id: str) -> ScheduledTask | None:
        return self._tasks.get(task_id)

    def _dependencies_met(self, task: ScheduledTask) -> bool:
        for dep_id in task.dependencies:
            dep = self._tasks.get(dep_id)
            if not dep or dep.status != ScheduleStatus.COMPLETED:
                return False
        return True

    def _get_total_budget(self, task: ScheduledTask) -> float:
        if task.deadline and task.deadline.sla:
            return float(task.deadline.sla.max_duration_seconds)
        if task.deadline and task.scheduled_at:
            return (task.deadline.due_at - task.scheduled_at).total_seconds()
        return 3600.0

    def _compute_escalation_level(self, pct: float, sla: SLA) -> EscalationLevel:
        if pct >= 1.0:
            return EscalationLevel.BLOCKED
        thresholds = [
            (0.95, EscalationLevel.CRITICAL),
            (0.9, EscalationLevel.ALERT),
            (sla.warning_threshold_pct, EscalationLevel.WARNING),
        ]
        for threshold, level in thresholds:
            if pct >= threshold:
                return level
        return EscalationLevel.NONE

    def _escalate(
        self, task: ScheduledTask, level: EscalationLevel,
        now: datetime, remaining: float, total: float,
    ) -> EscalationEvent:
        elapsed = total - remaining
        reason = f"Task '{task.name}' reached {level.value} level ({elapsed:.0f}s elapsed of {total:.0f}s budget)"
        return EscalationEvent(
            task_id=task.task_id,
            level=level,
            reason=reason,
            elapsed_seconds=elapsed,
            threshold_seconds=total,
        )

    def _update_task_escalation(self, task_id: str, level: EscalationLevel) -> None:
        task = self._tasks[task_id]
        updated = ScheduledTask(
            task_id=task.task_id,
            name=task.name,
            agent_id=task.agent_id,
            deadline=task.deadline,
            dependencies=task.dependencies,
            priority=task.priority,
            status=task.status,
            scheduled_at=task.scheduled_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
            escalation_level=level,
            metadata=task.metadata,
        )
        self._tasks[task_id] = updated
