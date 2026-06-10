"""Tests for behavior versioning engine."""

from __future__ import annotations

import pytest

from reins.behavior_versioning import (
    BehaviorBaseline,
    BehaviorDiff,
    BehaviorSignature,
    BehaviorVersioner,
    ChangeKind,
    DriftStatus,
)


@pytest.fixture
def versioner() -> BehaviorVersioner:
    return BehaviorVersioner()


def test_capture_signature(versioner):
    sig = versioner.capture_signature("agent-1",
                                       action_profile={"read": 10, "write": 3},
                                       success_rate=0.95)
    assert sig.agent_id == "agent-1"
    assert sig.action_profile["read"] == 10
    assert sig.success_rate == 0.95


def test_create_baseline(versioner):
    versioner.capture_signature("a", action_profile={"x": 5})
    baseline = versioner.create_baseline("a")
    assert baseline is not None
    assert baseline.agent_id == "a"


def test_create_baseline_no_signature(versioner):
    assert versioner.create_baseline("nonexistent") is None


def test_get_baseline(versioner):
    versioner.capture_signature("a", action_profile={"x": 1})
    versioner.create_baseline("a")
    assert versioner.get_baseline("a") is not None
    assert versioner.get_baseline("missing") is None


def test_golden_baseline(versioner):
    versioner.capture_signature("a", action_profile={"x": 1})
    versioner.create_baseline("a", is_golden=True)
    golden = versioner.get_golden_baseline("a")
    assert golden is not None
    assert golden.is_golden is True


def test_detect_drift_stable(versioner):
    versioner.capture_signature("a", action_profile={"x": 10}, success_rate=0.95)
    versioner.create_baseline("a", is_golden=True)
    assert versioner.detect_drift("a") == DriftStatus.STABLE


def test_detect_drift_drifting(versioner):
    versioner.capture_signature("a", action_profile={"x": 10}, success_rate=0.95)
    versioner.create_baseline("a", is_golden=True)
    versioner.capture_signature("a", action_profile={"x": 10, "new_action": 5},
                                success_rate=0.90)
    assert versioner.detect_drift("a") == DriftStatus.DRIFTING


def test_detect_drift_diverged(versioner):
    versioner.capture_signature("a", action_profile={"x": 10, "y": 5},
                                success_rate=0.95)
    versioner.create_baseline("a", is_golden=True)
    versioner.capture_signature("a", action_profile={"z": 10},
                                success_rate=0.5)
    assert versioner.detect_drift("a") == DriftStatus.DIVERGED


def test_compute_diff(versioner):
    versioner.capture_signature("a", action_profile={"read": 10}, success_rate=0.9)
    versioner.create_baseline("a")
    versioner.capture_signature("a", action_profile={"read": 10, "write": 5},
                                success_rate=0.88)
    diff = versioner.compute_diff("a")
    assert diff is not None
    assert "write" in diff.added_actions
    assert diff.change_kind == ChangeKind.MINOR


def test_compute_diff_major(versioner):
    versioner.capture_signature("a", action_profile={"x": 10, "y": 5},
                                success_rate=0.95)
    versioner.create_baseline("a")
    versioner.capture_signature("a", action_profile={"z": 10},
                                success_rate=0.6)
    diff = versioner.compute_diff("a")
    assert diff.change_kind == ChangeKind.MAJOR
    assert "x" in diff.removed_actions


def test_bump_version_patch(versioner):
    versioner.capture_signature("a", action_profile={"x": 1})
    new = versioner.bump_version("a", ChangeKind.PATCH)
    assert new == "0.1.1"


def test_bump_version_minor(versioner):
    versioner.capture_signature("a", action_profile={"x": 1})
    new = versioner.bump_version("a", ChangeKind.MINOR)
    assert new == "0.2.0"


def test_bump_version_major(versioner):
    versioner.capture_signature("a", action_profile={"x": 1})
    new = versioner.bump_version("a", ChangeKind.MAJOR)
    assert new == "1.0.0"


def test_rollback(versioner):
    versioner.capture_signature("a", action_profile={"x": 10}, success_rate=0.99)
    versioner.create_baseline("a")
    versioner.capture_signature("a", action_profile={"y": 5}, success_rate=0.5)
    rolled = versioner.rollback("a", "0.1.0")
    assert rolled is not None
    assert rolled.action_profile == {"x": 10}
    assert rolled.success_rate == 0.99


def test_rollback_nonexistent(versioner):
    assert versioner.rollback("a", "9.9.9") is None


def test_get_history(versioner):
    versioner.capture_signature("a", action_profile={"x": 1})
    versioner.create_baseline("a")
    versioner.bump_version("a", ChangeKind.MINOR)
    versioner.create_baseline("a")
    history = versioner.get_history("a")
    assert len(history) == 2


def test_get_diffs(versioner):
    versioner.capture_signature("a", action_profile={"x": 1})
    versioner.create_baseline("a")
    versioner.capture_signature("a", action_profile={"x": 1, "y": 2})
    versioner.compute_diff("a")
    assert len(versioner.get_diffs()) == 1
    assert len(versioner.get_diffs(agent_id="a")) == 1
    assert len(versioner.get_diffs(agent_id="b")) == 0


def test_stats(versioner):
    versioner.capture_signature("a", action_profile={"x": 10}, success_rate=0.9)
    versioner.create_baseline("a", is_golden=True)
    versioner.capture_signature("a", action_profile={"x": 10, "y": 5})
    versioner.compute_diff("a")
    stats = versioner.get_stats()
    assert stats.total_agents == 1
    assert stats.total_versions == 1
    assert stats.total_diffs == 1
