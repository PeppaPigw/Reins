"""Tests for scheduling engine with priority queues and resources."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from reins.scheduling import (
    ResourcePool,
    ScheduledTask,
    ScheduleSlot,
    Scheduler,
    SchedulingStats,
    SchedulingStrategy,
    TaskPriority,
    TaskState,
)


@pytest.fixture
def scheduler() -> Scheduler:
    return Scheduler()


def test_submit_task(scheduler):
    task = scheduler.submit_task("build feature", priority=TaskPriority.HIGH)
    assert task.name == "build feature"
    assert task.priority == TaskPriority.HIGH
    assert task.state == TaskState.PENDING


def test_get_task(scheduler):
    task = scheduler.submit_task("work")
    assert scheduler.get_task(task.task_id) is not None
    assert scheduler.get_task("nonexistent") is None


def test_cancel_task(scheduler):
    task = scheduler.submit_task("work")
    cancelled = scheduler.cancel_task(task.task_id)
    assert cancelled.state == TaskState.CANCELLED


def test_cancel_completed_noop(scheduler):
    task = scheduler.submit_task("work")
    scheduler.assign_task(task.task_id, "agent-1")
    scheduler.complete_task(task.task_id)
    result = scheduler.cancel_task(task.task_id)
    assert result.state == TaskState.COMPLETED


def test_get_ready_tasks(scheduler):
    scheduler.submit_task("t1")
    scheduler.submit_task("t2")
    ready = scheduler.get_ready_tasks()
    assert len(ready) == 2


def test_get_ready_tasks_respects_dependencies(scheduler):
    t1 = scheduler.submit_task("dep")
    scheduler.submit_task("blocked", dependencies=[t1.task_id])
    ready = scheduler.get_ready_tasks()
    assert len(ready) == 1
    assert ready[0].task_id == t1.task_id


def test_dependencies_unlock_after_completion(scheduler):
    t1 = scheduler.submit_task("dep")
    t2 = scheduler.submit_task("blocked", dependencies=[t1.task_id])
    scheduler.assign_task(t1.task_id, "agent-1")
    scheduler.complete_task(t1.task_id)
    ready = scheduler.get_ready_tasks()
    assert any(t.task_id == t2.task_id for t in ready)


def test_assign_task(scheduler):
    task = scheduler.submit_task("work")
    slot = scheduler.assign_task(task.task_id, "agent-1")
    assert slot is not None
    assert slot.agent_id == "agent-1"
    updated = scheduler.get_task(task.task_id)
    assert updated.state == TaskState.RUNNING


def test_assign_task_not_pending(scheduler):
    task = scheduler.submit_task("work")
    scheduler.assign_task(task.task_id, "agent-1")
    assert scheduler.assign_task(task.task_id, "agent-2") is None


def test_complete_task(scheduler):
    task = scheduler.submit_task("work")
    scheduler.assign_task(task.task_id, "agent-1")
    completed = scheduler.complete_task(task.task_id)
    assert completed.state == TaskState.COMPLETED
    assert completed.completed_at is not None


def test_fail_task(scheduler):
    task = scheduler.submit_task("work")
    scheduler.assign_task(task.task_id, "agent-1")
    failed = scheduler.fail_task(task.task_id)
    assert failed.state == TaskState.FAILED


def test_priority_ordering(scheduler):
    scheduler.submit_task("low", priority=TaskPriority.LOW)
    scheduler.submit_task("critical", priority=TaskPriority.CRITICAL)
    scheduler.submit_task("medium", priority=TaskPriority.MEDIUM)
    ready = scheduler.get_ready_tasks()
    assert ready[0].priority == TaskPriority.CRITICAL
    assert ready[-1].priority == TaskPriority.LOW


def test_shortest_first_strategy():
    s = Scheduler(strategy=SchedulingStrategy.SHORTEST_FIRST)
    s.submit_task("long", estimated_duration_ms=10000)
    s.submit_task("short", estimated_duration_ms=100)
    ready = s.get_ready_tasks()
    assert ready[0].estimated_duration_ms == 100


def test_deadline_first_strategy():
    s = Scheduler(strategy=SchedulingStrategy.DEADLINE_FIRST)
    now = datetime.now(UTC)
    s.submit_task("later", deadline=now + timedelta(hours=2))
    s.submit_task("soon", deadline=now + timedelta(minutes=10))
    ready = s.get_ready_tasks()
    assert ready[0].name == "soon"


def test_create_pool(scheduler):
    pool = scheduler.create_pool("gpu", capacity=4)
    assert pool.name == "gpu"
    assert pool.capacity == 4


def test_allocate_resource(scheduler):
    pool = scheduler.create_pool("gpu", capacity=2)
    assert scheduler.allocate_resource(pool.pool_id) is True
    assert scheduler.allocate_resource(pool.pool_id) is True
    assert scheduler.allocate_resource(pool.pool_id) is False


def test_release_resource(scheduler):
    pool = scheduler.create_pool("gpu", capacity=1)
    scheduler.allocate_resource(pool.pool_id)
    assert scheduler.release_resource(pool.pool_id) is True
    assert scheduler.allocate_resource(pool.pool_id) is True


def test_release_empty_pool(scheduler):
    pool = scheduler.create_pool("gpu")
    assert scheduler.release_resource(pool.pool_id) is False


def test_reserve_resource(scheduler):
    pool = scheduler.create_pool("gpu", capacity=3)
    assert scheduler.reserve_resource(pool.pool_id, 2) is True
    assert scheduler.allocate_resource(pool.pool_id) is True
    assert scheduler.allocate_resource(pool.pool_id) is False


def test_get_overdue_tasks(scheduler):
    past = datetime.now(UTC) - timedelta(hours=1)
    future = datetime.now(UTC) + timedelta(hours=1)
    scheduler.submit_task("overdue", deadline=past)
    scheduler.submit_task("on_time", deadline=future)
    overdue = scheduler.get_overdue_tasks()
    assert len(overdue) == 1
    assert overdue[0].name == "overdue"


def test_get_agent_load(scheduler):
    t1 = scheduler.submit_task("t1")
    t2 = scheduler.submit_task("t2")
    scheduler.submit_task("t3")
    scheduler.assign_task(t1.task_id, "agent-1")
    scheduler.assign_task(t2.task_id, "agent-1")
    assert scheduler.get_agent_load("agent-1") == 2
    assert scheduler.get_agent_load("agent-2") == 0


def test_stats_empty(scheduler):
    stats = scheduler.get_stats()
    assert stats.total_tasks == 0


def test_stats_populated(scheduler):
    t1 = scheduler.submit_task("t1", priority=TaskPriority.HIGH)
    t2 = scheduler.submit_task("t2", priority=TaskPriority.LOW)
    scheduler.assign_task(t1.task_id, "a")
    scheduler.complete_task(t1.task_id)
    scheduler.assign_task(t2.task_id, "a")
    scheduler.fail_task(t2.task_id)
    stats = scheduler.get_stats()
    assert stats.total_tasks == 2
    assert stats.completed_tasks == 1
    assert stats.failed_tasks == 1
    assert "high" in stats.by_priority
