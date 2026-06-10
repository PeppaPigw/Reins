"""Tests for temporal scheduling with deadlines, SLAs, and escalation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from reins.temporal import (
    Deadline,
    EscalationLevel,
    Priority,
    ScheduledTask,
    ScheduleStatus,
    SLA,
    TemporalScheduler,
)


@pytest.fixture
def scheduler() -> TemporalScheduler:
    return TemporalScheduler()


@pytest.fixture
def sla_fast() -> SLA:
    return SLA(name="fast", max_duration_seconds=300, warning_threshold_pct=0.8)


def _future(seconds: int) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=seconds)


def _past(seconds: int) -> datetime:
    return datetime.now(UTC) - timedelta(seconds=seconds)


def test_schedule_task(scheduler):
    task = ScheduledTask(name="build feature", agent_id="agent-1")
    result = scheduler.schedule(task)
    assert result.status == ScheduleStatus.SCHEDULED
    assert result.scheduled_at is not None


def test_start_task(scheduler):
    task = ScheduledTask(name="build feature")
    scheduler.schedule(task)
    started = scheduler.start(task.task_id)
    assert started.status == ScheduleStatus.RUNNING
    assert started.started_at is not None


def test_complete_task(scheduler):
    task = ScheduledTask(name="build feature")
    scheduler.schedule(task)
    scheduler.start(task.task_id)
    completed = scheduler.complete(task.task_id)
    assert completed.status == ScheduleStatus.COMPLETED
    assert completed.completed_at is not None


def test_fail_task(scheduler):
    task = ScheduledTask(name="risky op")
    scheduler.schedule(task)
    scheduler.start(task.task_id)
    failed = scheduler.fail(task.task_id)
    assert failed.status == ScheduleStatus.FAILED


def test_cannot_start_completed_task(scheduler):
    task = ScheduledTask(name="done")
    scheduler.schedule(task)
    scheduler.start(task.task_id)
    scheduler.complete(task.task_id)
    with pytest.raises(ValueError, match="Cannot start"):
        scheduler.start(task.task_id)


def test_dependency_blocks_start(scheduler):
    dep = ScheduledTask(name="prerequisite")
    task = ScheduledTask(name="dependent", dependencies=(dep.task_id,))
    scheduler.schedule(dep)
    scheduler.schedule(task)

    with pytest.raises(ValueError, match="not completed"):
        scheduler.start(task.task_id)

    scheduler.start(dep.task_id)
    scheduler.complete(dep.task_id)
    started = scheduler.start(task.task_id)
    assert started.status == ScheduleStatus.RUNNING


def test_deadline_escalation_overdue(scheduler, sla_fast):
    deadline = Deadline(due_at=_past(60), sla=sla_fast)
    task = ScheduledTask(name="overdue task", deadline=deadline)
    scheduler.schedule(task)

    escalations = scheduler.check_deadlines()
    assert len(escalations) == 1
    assert escalations[0].level == EscalationLevel.BLOCKED


def test_deadline_warning_threshold(scheduler, sla_fast):
    deadline = Deadline(due_at=_future(280), sla=sla_fast)
    task = ScheduledTask(name="almost due", deadline=deadline)
    scheduled = scheduler.schedule(task)

    now = scheduled.scheduled_at + timedelta(seconds=250)
    escalations = scheduler.check_deadlines(now=now)
    assert len(escalations) >= 1
    assert escalations[0].level in (EscalationLevel.WARNING, EscalationLevel.ALERT, EscalationLevel.CRITICAL)


def test_no_escalation_when_on_track(scheduler, sla_fast):
    deadline = Deadline(due_at=_future(600), sla=sla_fast)
    task = ScheduledTask(name="plenty of time", deadline=deadline)
    scheduler.schedule(task)

    escalations = scheduler.check_deadlines()
    assert len(escalations) == 0


def test_priority_queue_ordering(scheduler):
    low = ScheduledTask(name="low", priority=Priority.LOW)
    high = ScheduledTask(name="high", priority=Priority.HIGH)
    critical = ScheduledTask(name="critical", priority=Priority.CRITICAL)

    scheduler.schedule(low)
    scheduler.schedule(high)
    scheduler.schedule(critical)

    queue = scheduler.get_priority_queue()
    assert queue[0].name == "critical"
    assert queue[1].name == "high"
    assert queue[2].name == "low"


def test_priority_queue_excludes_blocked(scheduler):
    dep = ScheduledTask(name="blocker")
    blocked = ScheduledTask(name="blocked", dependencies=(dep.task_id,), priority=Priority.CRITICAL)
    free = ScheduledTask(name="free", priority=Priority.LOW)

    scheduler.schedule(dep)
    scheduler.schedule(blocked)
    scheduler.schedule(free)

    queue = scheduler.get_priority_queue()
    names = [t.name for t in queue]
    assert "blocked" not in names
    assert "blocker" in names
    assert "free" in names


def test_report_counts(scheduler, sla_fast):
    t1 = ScheduledTask(name="done")
    scheduler.schedule(t1)
    scheduler.start(t1.task_id)
    scheduler.complete(t1.task_id)

    t2 = ScheduledTask(name="overdue", deadline=Deadline(due_at=_past(100), sla=sla_fast))
    scheduler.schedule(t2)

    t3 = ScheduledTask(name="on track", deadline=Deadline(due_at=_future(600), sla=sla_fast))
    scheduler.schedule(t3)

    report = scheduler.get_report()
    assert report.total_tasks == 3
    assert report.completed == 1
    assert report.overdue == 1
    assert report.on_track == 1


def test_get_task(scheduler):
    task = ScheduledTask(name="find me")
    scheduler.schedule(task)
    found = scheduler.get_task(task.task_id)
    assert found is not None
    assert found.name == "find me"


def test_get_unknown_task(scheduler):
    assert scheduler.get_task("nonexistent") is None


def test_unknown_task_start_raises(scheduler):
    with pytest.raises(ValueError, match="Unknown task"):
        scheduler.start("fake-id")
