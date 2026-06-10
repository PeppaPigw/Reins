"""Tests for goal decomposition with hierarchical breakdown and dependency tracking."""

from __future__ import annotations

import pytest

from reins.goals import (
    DecompositionStrategy,
    Goal,
    GoalDecomposer,
    GoalPriority,
    GoalProgress,
    GoalStats,
    GoalStatus,
    GoalTree,
)


@pytest.fixture
def decomposer() -> GoalDecomposer:
    return GoalDecomposer()


def _goal(name="test-goal", parent_id=None, dependencies=(), priority=GoalPriority.MEDIUM):
    return Goal(name=name, parent_id=parent_id, dependencies=dependencies, priority=priority)


def test_add_and_get_goal(decomposer):
    goal = decomposer.add_goal(_goal(name="build feature"))
    retrieved = decomposer.get_goal(goal.goal_id)
    assert retrieved is not None
    assert retrieved.name == "build feature"


def test_get_goal_not_found(decomposer):
    assert decomposer.get_goal("nonexistent") is None


def test_update_status(decomposer):
    goal = decomposer.add_goal(_goal())
    updated = decomposer.update_status(goal.goal_id, GoalStatus.ACTIVE)
    assert updated.status == GoalStatus.ACTIVE


def test_update_status_completed_sets_timestamp(decomposer):
    goal = decomposer.add_goal(_goal())
    updated = decomposer.update_status(goal.goal_id, GoalStatus.COMPLETED)
    assert updated.completed_at is not None


def test_update_status_not_found(decomposer):
    assert decomposer.update_status("nonexistent", GoalStatus.ACTIVE) is None


def test_get_children(decomposer):
    parent = decomposer.add_goal(_goal(name="parent"))
    child1 = decomposer.add_goal(_goal(name="child1", parent_id=parent.goal_id))
    child2 = decomposer.add_goal(_goal(name="child2", parent_id=parent.goal_id))
    children = decomposer.get_children(parent.goal_id)
    assert len(children) == 2


def test_get_children_empty(decomposer):
    goal = decomposer.add_goal(_goal())
    assert decomposer.get_children(goal.goal_id) == []


def test_progress_leaf_completed(decomposer):
    goal = decomposer.add_goal(_goal())
    decomposer.update_status(goal.goal_id, GoalStatus.COMPLETED)
    progress = decomposer.get_progress(goal.goal_id)
    assert progress.completion_ratio == 1.0


def test_progress_leaf_pending(decomposer):
    goal = decomposer.add_goal(_goal())
    progress = decomposer.get_progress(goal.goal_id)
    assert progress.completion_ratio == 0.0


def test_progress_with_children(decomposer):
    parent = decomposer.add_goal(_goal(name="parent"))
    c1 = decomposer.add_goal(_goal(name="c1", parent_id=parent.goal_id))
    c2 = decomposer.add_goal(_goal(name="c2", parent_id=parent.goal_id))
    decomposer.update_status(c1.goal_id, GoalStatus.COMPLETED)
    progress = decomposer.get_progress(parent.goal_id)
    assert progress.completion_ratio == pytest.approx(0.5)
    assert progress.subgoals_total == 2
    assert progress.subgoals_completed == 1


def test_progress_nonexistent(decomposer):
    progress = decomposer.get_progress("nonexistent")
    assert progress.completion_ratio == 0.0


def test_blocked_goals_detected(decomposer):
    g1 = decomposer.add_goal(_goal(name="first"))
    g2 = decomposer.add_goal(_goal(name="second", dependencies=(g1.goal_id,)))
    blocked = decomposer.get_blocked_goals()
    assert any(g.goal_id == g2.goal_id for g in blocked)


def test_blocked_goals_resolved(decomposer):
    g1 = decomposer.add_goal(_goal(name="first"))
    g2 = decomposer.add_goal(_goal(name="second", dependencies=(g1.goal_id,)))
    decomposer.update_status(g1.goal_id, GoalStatus.COMPLETED)
    blocked = decomposer.get_blocked_goals()
    assert not any(g.goal_id == g2.goal_id for g in blocked)


def test_ready_goals(decomposer):
    g1 = decomposer.add_goal(_goal(name="first"))
    g2 = decomposer.add_goal(_goal(name="second", dependencies=(g1.goal_id,)))
    ready = decomposer.get_ready_goals()
    assert any(g.goal_id == g1.goal_id for g in ready)
    assert not any(g.goal_id == g2.goal_id for g in ready)


def test_ready_goals_after_dependency_met(decomposer):
    g1 = decomposer.add_goal(_goal(name="first"))
    g2 = decomposer.add_goal(_goal(name="second", dependencies=(g1.goal_id,)))
    decomposer.update_status(g1.goal_id, GoalStatus.COMPLETED)
    ready = decomposer.get_ready_goals()
    assert any(g.goal_id == g2.goal_id for g in ready)


def test_get_tree(decomposer):
    root = decomposer.add_goal(_goal(name="root"))
    c1 = decomposer.add_goal(_goal(name="c1", parent_id=root.goal_id))
    c2 = decomposer.add_goal(_goal(name="c2", parent_id=root.goal_id))
    gc1 = decomposer.add_goal(_goal(name="gc1", parent_id=c1.goal_id))
    tree = decomposer.get_tree(root.goal_id)
    assert tree.total_goals == 4
    assert tree.max_depth == 2


def test_get_tree_completion(decomposer):
    root = decomposer.add_goal(_goal(name="root"))
    c1 = decomposer.add_goal(_goal(name="c1", parent_id=root.goal_id))
    c2 = decomposer.add_goal(_goal(name="c2", parent_id=root.goal_id))
    decomposer.update_status(c1.goal_id, GoalStatus.COMPLETED)
    decomposer.update_status(root.goal_id, GoalStatus.COMPLETED)
    tree = decomposer.get_tree(root.goal_id)
    assert tree.completion_ratio == pytest.approx(2.0 / 3.0, abs=0.01)


def test_get_tree_critical_path(decomposer):
    root = decomposer.add_goal(_goal(name="root"))
    c1 = decomposer.add_goal(_goal(name="c1", parent_id=root.goal_id))
    c2 = decomposer.add_goal(_goal(name="c2", parent_id=root.goal_id))
    gc1 = decomposer.add_goal(_goal(name="gc1", parent_id=c1.goal_id))
    tree = decomposer.get_tree(root.goal_id)
    assert len(tree.critical_path) == 3
    assert tree.critical_path[0] == root.goal_id


def test_get_tree_nonexistent(decomposer):
    tree = decomposer.get_tree("nonexistent")
    assert tree.total_goals == 0


def test_remove_goal(decomposer):
    goal = decomposer.add_goal(_goal())
    assert decomposer.remove_goal(goal.goal_id)
    assert decomposer.get_goal(goal.goal_id) is None


def test_remove_goal_not_found(decomposer):
    assert not decomposer.remove_goal("nonexistent")


def test_remove_goal_clears_parent_reference(decomposer):
    parent = decomposer.add_goal(_goal(name="parent"))
    child = decomposer.add_goal(_goal(name="child", parent_id=parent.goal_id))
    decomposer.remove_goal(child.goal_id)
    children = decomposer.get_children(parent.goal_id)
    assert len(children) == 0


def test_remove_goal_orphans_children(decomposer):
    parent = decomposer.add_goal(_goal(name="parent"))
    child = decomposer.add_goal(_goal(name="child", parent_id=parent.goal_id))
    decomposer.remove_goal(parent.goal_id)
    orphan = decomposer.get_goal(child.goal_id)
    assert orphan is not None
    assert orphan.parent_id is None


def test_stats_empty():
    d = GoalDecomposer()
    stats = d.get_stats()
    assert stats.total_goals == 0


def test_stats_with_data(decomposer):
    g1 = decomposer.add_goal(_goal(priority=GoalPriority.HIGH))
    g2 = decomposer.add_goal(_goal(priority=GoalPriority.LOW))
    decomposer.update_status(g1.goal_id, GoalStatus.COMPLETED)
    stats = decomposer.get_stats()
    assert stats.total_goals == 2
    assert stats.completed_goals == 1
    assert stats.by_priority["high"] == 1
    assert stats.by_priority["low"] == 1


def test_depth_computation(decomposer):
    root = decomposer.add_goal(_goal(name="root"))
    c1 = decomposer.add_goal(_goal(name="c1", parent_id=root.goal_id))
    gc1 = decomposer.add_goal(_goal(name="gc1", parent_id=c1.goal_id))
    ggc1 = decomposer.add_goal(_goal(name="ggc1", parent_id=gc1.goal_id))
    progress = decomposer.get_progress(root.goal_id)
    assert progress.depth == 3
