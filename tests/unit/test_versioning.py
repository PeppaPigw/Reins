"""Tests for semantic versioning of agent behavior."""

from __future__ import annotations

import pytest

from reins.versioning import (
    BehaviorChange,
    BehaviorVersion,
    ChangeKind,
    CompatibilityLevel,
    Migration,
    MigrationStatus,
    SemanticVersion,
    VersioningEngine,
    VersioningStats,
)


@pytest.fixture
def engine() -> VersioningEngine:
    return VersioningEngine()


def test_initial_version(engine):
    v = engine.get_current_version("agent-1")
    assert str(v) == "0.0.0"


def test_record_breaking_change(engine):
    engine.record_change("agent-1", ChangeKind.BREAKING, "removed old API")
    v = engine.get_current_version("agent-1")
    assert v.major == 1
    assert v.minor == 0
    assert v.patch == 0


def test_record_feature_change(engine):
    engine.record_change("agent-1", ChangeKind.FEATURE, "added new capability")
    v = engine.get_current_version("agent-1")
    assert v.major == 0
    assert v.minor == 1


def test_record_fix_change(engine):
    engine.record_change("agent-1", ChangeKind.FIX, "fixed edge case")
    v = engine.get_current_version("agent-1")
    assert v.patch == 1


def test_record_multiple_changes(engine):
    engine.record_change("agent-1", ChangeKind.FIX, "fix1")
    engine.record_change("agent-1", ChangeKind.FIX, "fix2")
    v = engine.get_current_version("agent-1")
    assert v.patch == 2


def test_breaking_resets_minor_patch(engine):
    engine.record_change("agent-1", ChangeKind.FEATURE, "feat")
    engine.record_change("agent-1", ChangeKind.FIX, "fix")
    engine.record_change("agent-1", ChangeKind.BREAKING, "break")
    v = engine.get_current_version("agent-1")
    assert str(v) == "1.0.0"


def test_no_auto_bump(engine):
    engine.record_change("agent-1", ChangeKind.INTERNAL, "internal", auto_bump=False)
    v = engine.get_current_version("agent-1")
    assert str(v) == "0.0.0"


def test_release_version(engine):
    bv = engine.release_version("agent-1", SemanticVersion(major=2, minor=0, patch=0))
    assert bv.version.major == 2


def test_version_history(engine):
    engine.record_change("agent-1", ChangeKind.FIX, "fix1")
    engine.record_change("agent-1", ChangeKind.FEATURE, "feat1")
    history = engine.get_version_history("agent-1")
    assert len(history) == 2


def test_version_history_empty(engine):
    assert engine.get_version_history("unknown") == []


def test_compatibility_same_major(engine):
    v1 = SemanticVersion(major=1, minor=0, patch=0)
    v2 = SemanticVersion(major=1, minor=2, patch=3)
    assert engine.check_compatibility("a", v1, v2) == CompatibilityLevel.BACKWARD_COMPATIBLE


def test_compatibility_different_major(engine):
    v1 = SemanticVersion(major=1, minor=0, patch=0)
    v2 = SemanticVersion(major=2, minor=0, patch=0)
    assert engine.check_compatibility("a", v1, v2) == CompatibilityLevel.INCOMPATIBLE


def test_compatibility_same_version(engine):
    v = SemanticVersion(major=1, minor=2, patch=3)
    assert engine.check_compatibility("a", v, v) == CompatibilityLevel.FULLY_COMPATIBLE


def test_compatibility_patch_only(engine):
    v1 = SemanticVersion(major=1, minor=2, patch=0)
    v2 = SemanticVersion(major=1, minor=2, patch=5)
    assert engine.check_compatibility("a", v1, v2) == CompatibilityLevel.FULLY_COMPATIBLE


def test_get_changes_all(engine):
    engine.record_change("a", ChangeKind.FIX, "fix")
    engine.record_change("b", ChangeKind.FEATURE, "feat")
    assert len(engine.get_changes()) == 2


def test_get_changes_by_agent(engine):
    engine.record_change("a", ChangeKind.FIX, "fix")
    engine.record_change("b", ChangeKind.FEATURE, "feat")
    assert len(engine.get_changes(agent_id="a")) == 1


def test_get_changes_by_kind(engine):
    engine.record_change("a", ChangeKind.FIX, "fix")
    engine.record_change("a", ChangeKind.FEATURE, "feat")
    assert len(engine.get_changes(kind=ChangeKind.FIX)) == 1


def test_create_migration(engine):
    m = engine.create_migration("agent-1", "1.0.0", "2.0.0", steps=["step1", "step2"])
    assert m.status == MigrationStatus.PENDING
    assert len(m.steps) == 2


def test_get_migration(engine):
    m = engine.create_migration("a", "1.0.0", "2.0.0")
    assert engine.get_migration(m.migration_id) is not None


def test_get_migration_not_found(engine):
    assert engine.get_migration("nonexistent") is None


def test_update_migration_status(engine):
    m = engine.create_migration("a", "1.0.0", "2.0.0")
    updated = engine.update_migration_status(m.migration_id, MigrationStatus.COMPLETED)
    assert updated.status == MigrationStatus.COMPLETED


def test_update_migration_not_found(engine):
    assert engine.update_migration_status("nonexistent", MigrationStatus.FAILED) is None


def test_get_migrations_by_agent(engine):
    engine.create_migration("a", "1.0.0", "2.0.0")
    engine.create_migration("b", "1.0.0", "2.0.0")
    assert len(engine.get_migrations(agent_id="a")) == 1


def test_get_migrations_by_status(engine):
    m = engine.create_migration("a", "1.0.0", "2.0.0")
    engine.update_migration_status(m.migration_id, MigrationStatus.COMPLETED)
    engine.create_migration("a", "2.0.0", "3.0.0")
    completed = engine.get_migrations(status=MigrationStatus.COMPLETED)
    assert len(completed) == 1


def test_stats_empty():
    eng = VersioningEngine()
    stats = eng.get_stats()
    assert stats.total_agents == 0
    assert stats.total_changes == 0


def test_stats_with_data(engine):
    engine.record_change("a", ChangeKind.FIX, "fix")
    engine.record_change("a", ChangeKind.FEATURE, "feat")
    engine.create_migration("a", "0.0.1", "0.1.0")
    stats = engine.get_stats()
    assert stats.total_agents == 1
    assert stats.total_changes == 2
    assert stats.total_versions == 2
    assert stats.total_migrations == 1
    assert ChangeKind.FIX.value in stats.by_change_kind


def test_semver_is_compatible(engine):
    v1 = SemanticVersion(major=1, minor=0, patch=0)
    v2 = SemanticVersion(major=1, minor=5, patch=3)
    assert v1.is_compatible_with(v2)


def test_semver_not_compatible(engine):
    v1 = SemanticVersion(major=1, minor=0, patch=0)
    v2 = SemanticVersion(major=2, minor=0, patch=0)
    assert not v1.is_compatible_with(v2)
