"""Tests for execution planning & optimization engine."""

from __future__ import annotations

import pytest

from reins.planner import (
    ExecutionPlan,
    ExecutionPlanner,
    ExecutionSlot,
    PlannerStats,
    PlanOptimization,
    PlanTask,
    SchedulingStrategy,
    TaskPriority,
    TaskState,
)


@pytest.fixture
def planner() -> ExecutionPlanner:
    return ExecutionPlanner()


def _task(name="task", task_id=None, depends_on=(), priority=TaskPriority.NORMAL,
          duration=1000.0, cost=0.01, parallelizable=True):
    kwargs = {
        "name": name,
        "depends_on": depends_on,
        "priority": priority,
        "estimated_duration_ms": duration,
        "estimated_cost": cost,
        "parallelizable": parallelizable,
    }
    if task_id:
        kwargs["task_id"] = task_id
    return PlanTask(**kwargs)


def test_create_plan_empty(planner):
    plan = planner.create_plan("empty goal", [])
    assert len(plan.tasks) == 0
    assert len(plan.slots) == 0


def test_create_plan_single_task(planner):
    tasks = [_task("do thing", task_id="t1")]
    plan = planner.create_plan("single task", tasks)
    assert len(plan.tasks) == 1
    assert len(plan.slots) == 1
    assert plan.total_estimated_duration_ms == 1000.0


def test_create_plan_independent_tasks_parallel(planner):
    tasks = [
        _task("a", task_id="a", duration=1000),
        _task("b", task_id="b", duration=2000),
        _task("c", task_id="c", duration=1500),
    ]
    plan = planner.create_plan("parallel work", tasks)
    assert plan.parallelism_factor > 1.0
    assert plan.total_estimated_duration_ms < 4500


def test_create_plan_sequential_dependencies(planner):
    tasks = [
        _task("first", task_id="t1", duration=1000),
        _task("second", task_id="t2", depends_on=("t1",), duration=1000),
        _task("third", task_id="t3", depends_on=("t2",), duration=1000),
    ]
    plan = planner.create_plan("sequential", tasks)
    assert plan.total_estimated_duration_ms == 3000.0
    assert plan.critical_path_length == 3


def test_create_plan_diamond_dependency(planner):
    tasks = [
        _task("root", task_id="root", duration=1000),
        _task("left", task_id="left", depends_on=("root",), duration=2000),
        _task("right", task_id="right", depends_on=("root",), duration=1000),
        _task("join", task_id="join", depends_on=("left", "right"), duration=1000),
    ]
    plan = planner.create_plan("diamond", tasks)
    assert plan.critical_path_length == 3
    assert plan.total_estimated_cost == pytest.approx(0.04)


def test_create_plan_invalid_dependency_removed(planner):
    tasks = [
        _task("a", task_id="a", depends_on=("nonexistent",)),
    ]
    plan = planner.create_plan("invalid deps", tasks)
    assert plan.tasks[0].depends_on == ()


def test_get_ready_tasks(planner):
    tasks = [
        _task("a", task_id="a"),
        _task("b", task_id="b", depends_on=("a",)),
        _task("c", task_id="c"),
    ]
    plan = planner.create_plan("ready test", tasks)

    ready = planner.get_ready_tasks(plan)
    ready_ids = {t.task_id for t in ready}
    assert "a" in ready_ids
    assert "c" in ready_ids
    assert "b" not in ready_ids


def test_get_ready_tasks_after_completion(planner):
    tasks = [
        _task("a", task_id="a"),
        _task("b", task_id="b", depends_on=("a",)),
    ]
    plan = planner.create_plan("completion", tasks)

    ready = planner.get_ready_tasks(plan, completed={"a"})
    assert len(ready) == 1
    assert ready[0].task_id == "b"


def test_get_critical_path(planner):
    tasks = [
        _task("root", task_id="root"),
        _task("fast", task_id="fast", depends_on=("root",)),
        _task("slow", task_id="slow", depends_on=("root",)),
        _task("end", task_id="end", depends_on=("fast", "slow")),
    ]
    plan = planner.create_plan("critical path", tasks)
    path = planner.get_critical_path(plan)
    assert len(path) >= 3


def test_estimate_completion_all_done(planner):
    tasks = [_task("a", task_id="a")]
    plan = planner.create_plan("done", tasks)
    remaining = planner.estimate_completion(plan, completed={"a"})
    assert remaining == 0.0


def test_estimate_completion_partial(planner):
    tasks = [
        _task("a", task_id="a", duration=1000),
        _task("b", task_id="b", depends_on=("a",), duration=2000),
        _task("c", task_id="c", duration=500),
    ]
    plan = planner.create_plan("partial", tasks)
    remaining = planner.estimate_completion(plan, completed={"a", "c"})
    assert remaining == 2000.0


def test_optimize_plan(planner):
    tasks = [
        _task("a", task_id="a", duration=1000),
        _task("b", task_id="b", duration=2000),
        _task("c", task_id="c", duration=1500),
    ]
    plan = planner.create_plan("optimize me", tasks)
    opt = planner.optimize(plan)
    assert opt.speedup_factor >= 1.0
    assert len(opt.optimizations_applied) > 0


def test_optimize_sequential_plan(planner):
    tasks = [
        _task("a", task_id="a", duration=1000),
        _task("b", task_id="b", depends_on=("a",), duration=1000),
    ]
    plan = planner.create_plan("sequential", tasks)
    opt = planner.optimize(plan)
    assert opt.speedup_factor >= 1.0


def test_priority_affects_ordering(planner):
    tasks = [
        _task("low", task_id="low", priority=TaskPriority.LOW, duration=100),
        _task("critical", task_id="critical", priority=TaskPriority.CRITICAL, duration=100),
        _task("normal", task_id="normal", priority=TaskPriority.NORMAL, duration=100),
    ]
    plan = planner.create_plan("priority", tasks)
    first_slot_tasks = plan.slots[0].task_ids
    assert "critical" in first_slot_tasks


def test_non_parallelizable_task(planner):
    tasks = [
        _task("serial", task_id="serial", parallelizable=False, duration=1000),
        _task("parallel1", task_id="p1", duration=500),
        _task("parallel2", task_id="p2", duration=500),
    ]
    plan = planner.create_plan("mixed", tasks)
    assert plan.total_estimated_duration_ms >= 1000


def test_strategy_stored_in_plan():
    planner = ExecutionPlanner(strategy=SchedulingStrategy.COST_OPTIMIZED)
    tasks = [_task("a", task_id="a")]
    plan = planner.create_plan("cost", tasks)
    assert plan.strategy == SchedulingStrategy.COST_OPTIMIZED


def test_stats_empty(planner):
    stats = planner.get_stats()
    assert stats.total_plans == 0
    assert stats.total_tasks == 0


def test_stats_after_plans(planner):
    tasks = [_task("a"), _task("b"), _task("c")]
    planner.create_plan("plan1", tasks)
    planner.create_plan("plan2", [_task("x")])

    stats = planner.get_stats()
    assert stats.total_plans == 2
    assert stats.total_tasks == 4
    assert stats.avg_parallelism >= 1.0
    assert stats.by_strategy["balanced"] == 2


def test_stats_with_optimizations(planner):
    tasks = [_task("a"), _task("b"), _task("c")]
    plan = planner.create_plan("opt", tasks)
    planner.optimize(plan)

    stats = planner.get_stats()
    assert stats.avg_speedup >= 1.0


def test_plan_goal_stored(planner):
    plan = planner.create_plan("deploy to production", [_task("a")])
    assert plan.goal == "deploy to production"


def test_plan_has_created_at(planner):
    plan = planner.create_plan("test", [_task("a")])
    assert plan.created_at is not None


def test_slot_parallel_flag(planner):
    tasks = [
        _task("a", task_id="a", duration=1000),
        _task("b", task_id="b", duration=1000),
    ]
    plan = planner.create_plan("parallel slots", tasks)
    parallel_slots = [s for s in plan.slots if s.parallel]
    assert len(parallel_slots) >= 1
