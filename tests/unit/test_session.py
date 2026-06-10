"""Tests for session continuity engine."""

from __future__ import annotations

import pytest

from reins.session import (
    MigrationStrategy,
    SessionContext,
    SessionContinuityEngine,
    SessionStatus,
    SuspendReason,
)


@pytest.fixture
def engine() -> SessionContinuityEngine:
    return SessionContinuityEngine()


def test_create_session(engine):
    session = engine.create_session("agent-1")
    assert session.agent_id == "agent-1"
    assert session.status == SessionStatus.ACTIVE
    assert engine.active_count == 1


def test_create_session_with_context(engine):
    ctx = SessionContext(working_directory="/tmp/work", git_branch="feature-x")
    session = engine.create_session("agent-1", context=ctx)
    assert session.context.working_directory == "/tmp/work"
    assert session.context.git_branch == "feature-x"


def test_get_session(engine):
    session = engine.create_session("agent-1")
    retrieved = engine.get_session(session.session_id)
    assert retrieved is not None
    assert retrieved.session_id == session.session_id


def test_get_nonexistent_session(engine):
    assert engine.get_session("nonexistent") is None


def test_add_turn(engine):
    session = engine.create_session("agent-1")
    updated = engine.add_turn(session.session_id, "user", "hello")
    assert len(updated.conversation) == 1
    assert updated.conversation[0].role == "user"
    assert updated.conversation[0].content == "hello"
    assert updated.version == 2


def test_add_multiple_turns(engine):
    session = engine.create_session("agent-1")
    engine.add_turn(session.session_id, "user", "hello")
    updated = engine.add_turn(session.session_id, "assistant", "hi there")
    assert len(updated.conversation) == 2
    assert updated.version == 3


def test_add_turn_nonexistent_session(engine):
    with pytest.raises(KeyError):
        engine.add_turn("nonexistent", "user", "hello")


def test_update_context(engine):
    session = engine.create_session("agent-1")
    new_ctx = SessionContext(working_directory="/new/path", git_branch="main")
    updated = engine.update_context(session.session_id, new_ctx)
    assert updated.context.working_directory == "/new/path"


def test_push_and_pop_task(engine):
    session = engine.create_session("agent-1")
    engine.push_task(session.session_id, "task-1")
    updated = engine.push_task(session.session_id, "task-2")
    assert updated.task_stack == ("task-1", "task-2")

    updated, popped = engine.pop_task(session.session_id)
    assert popped == "task-2"
    assert updated.task_stack == ("task-1",)


def test_pop_empty_task_stack(engine):
    session = engine.create_session("agent-1")
    updated, popped = engine.pop_task(session.session_id)
    assert popped is None


def test_suspend_session(engine):
    session = engine.create_session("agent-1")
    engine.add_turn(session.session_id, "user", "working on feature X")

    suspended = engine.suspend(session.session_id, SuspendReason.USER_REQUEST, "resume after lunch")
    assert suspended.reason == SuspendReason.USER_REQUEST
    assert suspended.resume_hint == "resume after lunch"
    assert suspended.session_state.status == SessionStatus.SUSPENDED
    assert suspended.checksum != ""
    assert engine.active_count == 0
    assert engine.suspended_count == 1


def test_suspend_nonexistent_session(engine):
    with pytest.raises(KeyError):
        engine.suspend("nonexistent")


def test_resume_session(engine):
    session = engine.create_session("agent-1")
    engine.add_turn(session.session_id, "user", "important context")
    engine.suspend(session.session_id)

    result = engine.resume(session.session_id)
    assert result.success
    assert result.restored_turns == 1
    assert result.restored_context
    assert engine.active_count == 1
    assert engine.suspended_count == 0


def test_resume_preserves_conversation(engine):
    session = engine.create_session("agent-1")
    engine.add_turn(session.session_id, "user", "message 1")
    engine.add_turn(session.session_id, "assistant", "response 1")
    engine.suspend(session.session_id)

    engine.resume(session.session_id)
    restored = engine.get_session(session.session_id)
    assert len(restored.conversation) == 2
    assert restored.conversation[0].content == "message 1"


def test_resume_nonexistent_session(engine):
    result = engine.resume("nonexistent")
    assert not result.success
    assert "not found" in result.warnings[0]


def test_serialize_and_deserialize(engine):
    session = engine.create_session("agent-1")
    engine.add_turn(session.session_id, "user", "hello")
    engine.push_task(session.session_id, "task-1")

    data = engine.serialize(session.session_id)
    engine.terminate(session.session_id)
    assert engine.active_count == 0

    restored = engine.deserialize(data)
    assert restored.session_id == session.session_id
    assert len(restored.conversation) == 1
    assert restored.task_stack == ("task-1",)
    assert engine.active_count == 1


def test_serialize_suspended_session(engine):
    session = engine.create_session("agent-1")
    engine.suspend(session.session_id)
    data = engine.serialize(session.session_id)
    assert data is not None
    assert "agent-1" in data


def test_serialize_nonexistent(engine):
    with pytest.raises(KeyError):
        engine.serialize("nonexistent")


def test_prepare_migration(engine):
    session = engine.create_session("agent-1")
    engine.add_turn(session.session_id, "user", "context")

    manifest = engine.prepare_migration(session.session_id, target_host="remote-1")
    assert manifest.session_id == session.session_id
    assert manifest.target_host == "remote-1"
    assert manifest.state_size_bytes > 0
    assert manifest.strategy == MigrationStrategy.FULL_TRANSFER


def test_prepare_migration_incremental(engine):
    session = engine.create_session("agent-1")
    manifest = engine.prepare_migration(
        session.session_id, target_host="remote-2", strategy=MigrationStrategy.INCREMENTAL
    )
    assert manifest.strategy == MigrationStrategy.INCREMENTAL


def test_terminate_active(engine):
    session = engine.create_session("agent-1")
    assert engine.terminate(session.session_id)
    assert engine.active_count == 0


def test_terminate_suspended(engine):
    session = engine.create_session("agent-1")
    engine.suspend(session.session_id)
    assert engine.terminate(session.session_id)
    assert engine.suspended_count == 0


def test_terminate_nonexistent(engine):
    assert not engine.terminate("nonexistent")


def test_list_suspended(engine):
    s1 = engine.create_session("agent-1")
    s2 = engine.create_session("agent-2")
    engine.suspend(s1.session_id, SuspendReason.IDLE_TIMEOUT)
    engine.suspend(s2.session_id, SuspendReason.RESOURCE_PRESSURE)

    suspended = engine.list_suspended()
    assert len(suspended) == 2


def test_session_version_increments(engine):
    session = engine.create_session("agent-1")
    assert session.version == 1
    updated = engine.add_turn(session.session_id, "user", "a")
    assert updated.version == 2
    updated = engine.add_turn(session.session_id, "user", "b")
    assert updated.version == 3


def test_suspend_with_different_reasons(engine):
    for reason in SuspendReason:
        s = engine.create_session(f"agent-{reason.value}")
        suspended = engine.suspend(s.session_id, reason)
        assert suspended.reason == reason
