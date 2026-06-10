"""Tests for semantic conflict detection."""

from __future__ import annotations

import pytest

from reins.conflicts import (
    Change,
    ChangeKind,
    Conflict,
    ConflictDetector,
    ConflictReport,
    ConflictSeverity,
    ConflictType,
    ResolutionStrategy,
)


@pytest.fixture
def detector() -> ConflictDetector:
    return ConflictDetector()


@pytest.mark.asyncio
async def test_no_conflicts_with_single_change(detector):
    changes = [
        Change(agent_id="agent-1", file_path="src/main.py", kind=ChangeKind.FUNCTION_MODIFIED)
    ]
    report = await detector.detect(changes)
    assert len(report.conflicts) == 0
    assert report.total_changes_analyzed == 1


@pytest.mark.asyncio
async def test_no_conflicts_with_non_overlapping_changes(detector):
    changes = [
        Change(
            agent_id="agent-1", file_path="src/main.py",
            kind=ChangeKind.FUNCTION_MODIFIED, line_range=(1, 10),
        ),
        Change(
            agent_id="agent-2", file_path="src/main.py",
            kind=ChangeKind.FUNCTION_MODIFIED, line_range=(50, 60),
        ),
    ]
    report = await detector.detect(changes)
    assert len(report.conflicts) == 0


@pytest.mark.asyncio
async def test_overlapping_modification_detected(detector):
    changes = [
        Change(
            agent_id="agent-1", file_path="src/main.py",
            kind=ChangeKind.FUNCTION_MODIFIED, symbol="process",
            line_range=(10, 20),
        ),
        Change(
            agent_id="agent-2", file_path="src/main.py",
            kind=ChangeKind.FUNCTION_MODIFIED, symbol="process",
            line_range=(15, 25),
        ),
    ]
    report = await detector.detect(changes)
    assert len(report.conflicts) == 1
    conflict = report.conflicts[0]
    assert conflict.conflict_type == ConflictType.OVERLAPPING_MODIFICATION
    assert conflict.severity == ConflictSeverity.HIGH
    assert "process" in conflict.affected_symbols


@pytest.mark.asyncio
async def test_overlapping_different_symbols_medium_severity(detector):
    changes = [
        Change(
            agent_id="agent-1", file_path="src/main.py",
            kind=ChangeKind.FUNCTION_MODIFIED, symbol="foo",
            line_range=(10, 20),
        ),
        Change(
            agent_id="agent-2", file_path="src/main.py",
            kind=ChangeKind.FUNCTION_MODIFIED, symbol="bar",
            line_range=(15, 25),
        ),
    ]
    report = await detector.detect(changes)
    assert len(report.conflicts) == 1
    assert report.conflicts[0].severity == ConflictSeverity.MEDIUM


@pytest.mark.asyncio
async def test_contradictory_api_change_detected(detector):
    changes = [
        Change(
            agent_id="agent-1", file_path="src/api.py",
            kind=ChangeKind.API_SIGNATURE_CHANGED, symbol="get_user",
            new_value="def get_user(id: int) -> User",
        ),
        Change(
            agent_id="agent-2", file_path="src/api.py",
            kind=ChangeKind.API_SIGNATURE_CHANGED, symbol="get_user",
            new_value="def get_user(user_id: str) -> dict",
        ),
    ]
    report = await detector.detect(changes)
    assert len(report.conflicts) == 1
    conflict = report.conflicts[0]
    assert conflict.conflict_type == ConflictType.CONTRADICTORY_API_CHANGE
    assert conflict.severity == ConflictSeverity.HIGH
    assert "get_user" in conflict.affected_symbols


@pytest.mark.asyncio
async def test_no_api_conflict_when_same_signature(detector):
    changes = [
        Change(
            agent_id="agent-1", file_path="src/api.py",
            kind=ChangeKind.API_SIGNATURE_CHANGED, symbol="get_user",
            new_value="def get_user(id: int) -> User",
        ),
        Change(
            agent_id="agent-2", file_path="src/api.py",
            kind=ChangeKind.API_SIGNATURE_CHANGED, symbol="get_user",
            new_value="def get_user(id: int) -> User",
        ),
    ]
    report = await detector.detect(changes)
    api_conflicts = [c for c in report.conflicts if c.conflict_type == ConflictType.CONTRADICTORY_API_CHANGE]
    assert len(api_conflicts) == 0


@pytest.mark.asyncio
async def test_dependency_add_remove_conflict(detector):
    changes = [
        Change(
            agent_id="agent-1", file_path="requirements.txt",
            kind=ChangeKind.DEPENDENCY_ADDED, symbol="requests",
        ),
        Change(
            agent_id="agent-2", file_path="requirements.txt",
            kind=ChangeKind.DEPENDENCY_REMOVED, symbol="requests",
        ),
    ]
    report = await detector.detect(changes)
    assert len(report.conflicts) == 1
    conflict = report.conflicts[0]
    assert conflict.conflict_type == ConflictType.INCOMPATIBLE_DEPENDENCY
    assert conflict.severity == ConflictSeverity.HIGH


@pytest.mark.asyncio
async def test_incompatible_dependency_versions(detector):
    changes = [
        Change(
            agent_id="agent-1", file_path="requirements.txt",
            kind=ChangeKind.DEPENDENCY_VERSION_CHANGED, symbol="pydantic",
            new_value=">=2.0",
        ),
        Change(
            agent_id="agent-2", file_path="requirements.txt",
            kind=ChangeKind.DEPENDENCY_VERSION_CHANGED, symbol="pydantic",
            new_value=">=1.10,<2.0",
        ),
    ]
    report = await detector.detect(changes)
    dep_conflicts = [c for c in report.conflicts if c.conflict_type == ConflictType.INCOMPATIBLE_DEPENDENCY]
    assert len(dep_conflicts) == 1
    assert dep_conflicts[0].severity == ConflictSeverity.MEDIUM


@pytest.mark.asyncio
async def test_compatible_dependency_versions_no_conflict(detector):
    changes = [
        Change(
            agent_id="agent-1", file_path="requirements.txt",
            kind=ChangeKind.DEPENDENCY_VERSION_CHANGED, symbol="pydantic",
            new_value="2.5.0",
        ),
        Change(
            agent_id="agent-2", file_path="requirements.txt",
            kind=ChangeKind.DEPENDENCY_VERSION_CHANGED, symbol="pydantic",
            new_value="2.6.0",
        ),
    ]
    report = await detector.detect(changes)
    dep_conflicts = [c for c in report.conflicts if c.conflict_type == ConflictType.INCOMPATIBLE_DEPENDENCY]
    assert len(dep_conflicts) == 0


@pytest.mark.asyncio
async def test_shared_state_race_detected(detector):
    changes = [
        Change(
            agent_id="agent-1", file_path="src/cache.py",
            kind=ChangeKind.FUNCTION_MODIFIED, symbol="_global_cache",
            new_value="cache.update(key, value)",
        ),
        Change(
            agent_id="agent-2", file_path="src/cache.py",
            kind=ChangeKind.FUNCTION_MODIFIED, symbol="_global_cache",
            new_value="cache.invalidate(key)",
        ),
    ]
    report = await detector.detect(changes)
    race_conflicts = [c for c in report.conflicts if c.conflict_type == ConflictType.SHARED_STATE_RACE]
    assert len(race_conflicts) >= 1
    assert race_conflicts[0].severity == ConflictSeverity.CRITICAL


@pytest.mark.asyncio
async def test_shared_state_race_via_new_value_pattern(detector):
    changes = [
        Change(
            agent_id="agent-1", file_path="src/app.py",
            kind=ChangeKind.FUNCTION_MODIFIED, symbol="init",
            new_value="singleton = AppInstance()",
        ),
        Change(
            agent_id="agent-2", file_path="src/app.py",
            kind=ChangeKind.FUNCTION_MODIFIED, symbol="reset",
            new_value="singleton = None",
        ),
    ]
    report = await detector.detect(changes)
    race_conflicts = [c for c in report.conflicts if c.conflict_type == ConflictType.SHARED_STATE_RACE]
    assert len(race_conflicts) >= 1


@pytest.mark.asyncio
async def test_deleted_dependency_detected(detector):
    changes = [
        Change(
            agent_id="agent-1", file_path="src/utils.py",
            kind=ChangeKind.FUNCTION_REMOVED, symbol="helper_fn",
        ),
        Change(
            agent_id="agent-2", file_path="src/main.py",
            kind=ChangeKind.FUNCTION_MODIFIED, symbol="helper_fn",
        ),
    ]
    report = await detector.detect(changes)
    del_conflicts = [c for c in report.conflicts if c.conflict_type == ConflictType.DELETED_DEPENDENCY]
    assert len(del_conflicts) == 1
    assert del_conflicts[0].severity == ConflictSeverity.HIGH
    assert "helper_fn" in del_conflicts[0].affected_symbols


@pytest.mark.asyncio
async def test_no_deleted_dependency_when_same_agent(detector):
    changes = [
        Change(
            agent_id="agent-1", file_path="src/utils.py",
            kind=ChangeKind.FUNCTION_REMOVED, symbol="helper_fn",
        ),
        Change(
            agent_id="agent-1", file_path="src/main.py",
            kind=ChangeKind.FUNCTION_MODIFIED, symbol="helper_fn",
        ),
    ]
    report = await detector.detect(changes)
    del_conflicts = [c for c in report.conflicts if c.conflict_type == ConflictType.DELETED_DEPENDENCY]
    assert len(del_conflicts) == 0


@pytest.mark.asyncio
async def test_report_has_critical_flag(detector):
    changes = [
        Change(
            agent_id="agent-1", file_path="src/state.py",
            kind=ChangeKind.FUNCTION_MODIFIED, symbol="_shared_state",
            new_value="state.lock()",
        ),
        Change(
            agent_id="agent-2", file_path="src/state.py",
            kind=ChangeKind.FUNCTION_MODIFIED, symbol="_shared_state",
            new_value="state.reset()",
        ),
    ]
    report = await detector.detect(changes)
    assert report.has_critical


@pytest.mark.asyncio
async def test_report_agents_involved(detector):
    changes = [
        Change(agent_id="alpha", file_path="a.py", kind=ChangeKind.FILE_CREATED),
        Change(agent_id="beta", file_path="b.py", kind=ChangeKind.FILE_CREATED),
        Change(agent_id="gamma", file_path="c.py", kind=ChangeKind.FILE_CREATED),
    ]
    report = await detector.detect(changes)
    assert report.agents_involved == ("alpha", "beta", "gamma")


@pytest.mark.asyncio
async def test_empty_changes_returns_empty_report(detector):
    report = await detector.detect([])
    assert len(report.conflicts) == 0
    assert report.total_changes_analyzed == 0


@pytest.mark.asyncio
async def test_overlap_threshold_respected():
    detector = ConflictDetector(overlap_line_threshold=0)
    changes = [
        Change(
            agent_id="agent-1", file_path="src/main.py",
            kind=ChangeKind.FUNCTION_MODIFIED, line_range=(1, 10),
        ),
        Change(
            agent_id="agent-2", file_path="src/main.py",
            kind=ChangeKind.FUNCTION_MODIFIED, line_range=(11, 20),
        ),
    ]
    report = await detector.detect(changes)
    assert len(report.conflicts) == 0

    detector_wide = ConflictDetector(overlap_line_threshold=5)
    report_wide = await detector_wide.detect(changes)
    assert len(report_wide.conflicts) == 1
