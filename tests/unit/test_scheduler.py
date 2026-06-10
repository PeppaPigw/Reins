"""Tests for DAG-aware task scheduler with critical path analysis."""

from __future__ import annotations

import pytest

from reins.scheduler import (
    Schedule,
    ScheduledTask,
    SchedulerStats,
    SchedulingPolicy,
    TaskPriority,
    TaskScheduler,
    TaskState,
)


@pytest.fixture
def scheduler() -> TaskScheduler:
    return TaskScheduler(policy=SchedulingPolicy.CRITICAL_PATH, max_parallelism=4)


def test_add_task(scheduler):
    task = scheduler.add_task("build")
    assert task.name == "build"
    assert task.state == TaskState.READY


def test_add_task_with_priority(scheduler):
    task = scheduler.add_task("deploy", priority=TaskPriority.CRITICAL)
    assert task.priority == TaskPriority.CRITICAL


def test_add_task_with_duration(scheduler):
    task = scheduler.add_task("compile", estimated_duration_ms=5000.0)
    assert task.estimated_duration_ms == 5000.0


def test_get_task(scheduler):
    task = scheduler.add_task("lint")
    found = scheduler.get_task(task.task_id)
    assert found is not None
    assert found.name == "lint"


def test_get_task_not_found(scheduler):
    assert scheduler.get_task("nonexistent") is None


def test_task_dependencies_blocked(scheduler):
    t1 = scheduler.add_task("compile")
    t2 = scheduler.add_task("test", dependencies=[t1.task_id])
    assert t2.state == TaskState.BLOCKED


def test_task_unblocked_after_completion(scheduler):
    t1 = scheduler.add_task("compile")
    t2 = scheduler.add_task("test", dependencies=[t1.task_id])
    scheduler.start_task(t1.task_id)
    scheduler.complete_task(t1.task_id, actual_duration_ms=200.0)
    updated = scheduler.get_task(t2.task_id)
    assert updated.state == TaskState.READY


def test_start_task(scheduler):
    task = scheduler.add_task("run")
    started = scheduler.start_task(task.task_id, assigned_to="worker-1")
    assert started.state == TaskState.RUNNING
    assert started.assigned_to == "worker-1"


def test_start_task_not_ready(scheduler):
    t1 = scheduler.add_task("a")
    t2 = scheduler.add_task("b", dependencies=[t1.task_id])
    result = scheduler.start_task(t2.task_id)
    assert result is None


def test_complete_task(scheduler):
    task = scheduler.add_task("job")
    scheduler.start_task(task.task_id)
    completed = scheduler.complete_task(task.task_id, actual_duration_ms=150.0)
    assert completed.state == TaskState.COMPLETED
    assert completed.actual_duration_ms == 150.0


def test_complete_task_not_running(scheduler):
    task = scheduler.add_task("job")
    result = scheduler.complete_task(task.task_id)
    assert result is None


def test_fail_task(scheduler):
    task = scheduler.add_task("flaky")
    scheduler.start_task(task.task_id)
    failed = scheduler.fail_task(task.task_id)
    assert failed.state == TaskState.FAILED


def test_get_ready_tasks(scheduler):
    scheduler.add_task("a")
    scheduler.add_task("b")
    t1 = scheduler.add_task("c")
    scheduler.add_task("d", dependencies=[t1.task_id])
    ready = scheduler.get_ready_tasks()
    assert len(ready) == 3


def test_get_blocked_tasks(scheduler):
    t1 = scheduler.add_task("first")
    scheduler.add_task("second", dependencies=[t1.task_id])
    scheduler.add_task("third", dependencies=[t1.task_id])
    blocked = scheduler.get_blocked_tasks()
    assert len(blocked) == 2


def test_compute_schedule_linear(scheduler):
    t1 = scheduler.add_task("a", estimated_duration_ms=100)
    t2 = scheduler.add_task("b", estimated_duration_ms=200, dependencies=[t1.task_id])
    t3 = scheduler.add_task("c", estimated_duration_ms=300, dependencies=[t2.task_id])
    schedule = scheduler.compute_schedule()
    assert len(schedule.task_order) == 3
    assert schedule.makespan_ms == 600.0


def test_critical_path_identifies_longest(scheduler):
    t1 = scheduler.add_task("start", estimated_duration_ms=100)
    t2 = scheduler.add_task("short", estimated_duration_ms=50, dependencies=[t1.task_id])
    t3 = scheduler.add_task("long", estimated_duration_ms=500, dependencies=[t1.task_id])
    cp = scheduler.get_critical_path()
    assert t3.task_id in cp
    assert t1.task_id in cp


def test_get_next_tasks_priority_policy():
    s = TaskScheduler(policy=SchedulingPolicy.PRIORITY)
    s.add_task("low", priority=TaskPriority.LOW)
    s.add_task("critical", priority=TaskPriority.CRITICAL)
    s.add_task("normal", priority=TaskPriority.NORMAL)
    nexts = s.get_next_tasks(n=2)
    assert nexts[0].priority == TaskPriority.CRITICAL


def test_get_next_tasks_shortest_first():
    s = TaskScheduler(policy=SchedulingPolicy.SHORTEST_FIRST)
    s.add_task("long", estimated_duration_ms=5000)
    s.add_task("short", estimated_duration_ms=100)
    s.add_task("medium", estimated_duration_ms=1000)
    nexts = s.get_next_tasks(n=1)
    assert nexts[0].estimated_duration_ms == 100


def test_get_next_tasks_critical_path(scheduler):
    t1 = scheduler.add_task("root", estimated_duration_ms=100)
    t2 = scheduler.add_task("cp_node", estimated_duration_ms=900, dependencies=[t1.task_id])
    t3 = scheduler.add_task("side", estimated_duration_ms=50)
    scheduler.start_task(t1.task_id)
    scheduler.complete_task(t1.task_id)
    nexts = scheduler.get_next_tasks(n=1)
    assert nexts[0].task_id == t2.task_id


def test_stats_empty():
    s = TaskScheduler()
    stats = s.get_stats()
    assert stats.total_tasks == 0
    assert stats.completed == 0


def test_stats_with_tasks(scheduler):
    t1 = scheduler.add_task("a", priority=TaskPriority.HIGH)
    t2 = scheduler.add_task("b", priority=TaskPriority.LOW)
    scheduler.start_task(t1.task_id)
    scheduler.complete_task(t1.task_id, actual_duration_ms=300.0)
    stats = scheduler.get_stats()
    assert stats.total_tasks == 2
    assert stats.completed == 1
    assert stats.avg_duration_ms == 300.0


def test_parallelism_factor(scheduler):
    scheduler.add_task("a", estimated_duration_ms=100)
    scheduler.add_task("b", estimated_duration_ms=100)
    scheduler.add_task("c", estimated_duration_ms=100)
    stats = scheduler.get_stats()
    assert stats.parallelism_factor >= 1.0


def test_resource_requirements(scheduler):
    task = scheduler.add_task("gpu_job", resource_requirements={"gpu": 2.0, "memory_gb": 16.0})
    assert task.resource_requirements["gpu"] == 2.0
    assert task.resource_requirements["memory_gb"] == 16.0


def test_topological_order_respects_deps(scheduler):
    t1 = scheduler.add_task("first", estimated_duration_ms=100)
    t2 = scheduler.add_task("second", estimated_duration_ms=100, dependencies=[t1.task_id])
    t3 = scheduler.add_task("third", estimated_duration_ms=100, dependencies=[t2.task_id])
    schedule = scheduler.compute_schedule()
    order = list(schedule.task_order)
    assert order.index(t1.task_id) < order.index(t2.task_id)
    assert order.index(t2.task_id) < order.index(t3.task_id)
