"""Tests for replay-based testing framework."""

from __future__ import annotations

import pytest

from reins.testing import (
    AssertionKind,
    GoldenSnapshot,
    Mutation,
    MutationKind,
    RecordingMode,
    ReplayAssertion,
    ReplayConfig,
    ReplayMode,
    SessionRecorder,
    SessionReplayer,
    compare_with_golden,
)


@pytest.fixture
def recorder() -> SessionRecorder:
    return SessionRecorder(session_id="sess-1", agent_id="agent-1", tags=("test",))


def test_recorder_captures_events(recorder):
    recorder.record_event("task.started", {"task_id": "t1"})
    recorder.record_event("task.completed", {"task_id": "t1"})
    recording = recorder.finish()
    assert len(recording.events) == 2
    assert recording.events[0].event_type == "task.started"
    assert recording.events[1].event_type == "task.completed"


def test_recorder_captures_tool_calls(recorder):
    recorder.record_tool_call("file_read", {"path": "main.py"}, result="content", duration_ms=50)
    recorder.record_tool_call("file_write", {"path": "main.py", "content": "new"}, duration_ms=30)
    recording = recorder.finish()
    assert len(recording.tool_calls) == 2
    assert recording.tool_calls[0].tool_name == "file_read"
    assert recording.tool_calls[1].result is None or recording.tool_calls[1].tool_name == "file_write"


def test_recorder_captures_decisions(recorder):
    recorder.record_decision("model_selection", {"task": "code"}, output="claude-opus", rationale="complex task")
    recording = recorder.finish()
    assert len(recording.decisions) == 1
    assert recording.decisions[0].decision_type == "model_selection"
    assert recording.decisions[0].output == "claude-opus"


def test_recorder_sequence_increments(recorder):
    recorder.record_event("a")
    recorder.record_tool_call("b")
    recorder.record_decision("c")
    recording = recorder.finish()
    assert recording.events[0].sequence == 1
    assert recording.tool_calls[0].sequence == 2
    assert recording.decisions[0].sequence == 3


def test_recorder_rejects_after_finish(recorder):
    recorder.finish()
    with pytest.raises(RuntimeError, match="Recording has ended"):
        recorder.record_event("late")


def test_recorder_mode_events_only():
    rec = SessionRecorder("s", "a", mode=RecordingMode.EVENTS_ONLY)
    rec.record_event("ok")
    with pytest.raises(ValueError):
        rec.record_tool_call("nope")


def test_recorder_mode_tool_calls_only():
    rec = SessionRecorder("s", "a", mode=RecordingMode.TOOL_CALLS_ONLY)
    rec.record_tool_call("ok")
    with pytest.raises(ValueError):
        rec.record_event("nope")


def test_recorder_metadata(recorder):
    recorder.set_metadata("model", "claude-opus")
    recording = recorder.finish()
    assert recording.metadata["model"] == "claude-opus"


@pytest.mark.asyncio
async def test_replay_strict_event_sequence():
    rec = SessionRecorder("s", "a")
    rec.record_event("start")
    rec.record_event("process")
    rec.record_event("end")
    recording = rec.finish()

    config = ReplayConfig(
        mode=ReplayMode.STRICT,
        assertions=(
            ReplayAssertion(kind=AssertionKind.EVENT_SEQUENCE, expected=["start", "process", "end"]),
        ),
    )
    replayer = SessionReplayer(recording, config)
    result = await replayer.replay()
    assert result.passed
    assert result.passed_assertions == 1


@pytest.mark.asyncio
async def test_replay_strict_sequence_fails_on_mismatch():
    rec = SessionRecorder("s", "a")
    rec.record_event("start")
    rec.record_event("end")
    recording = rec.finish()

    config = ReplayConfig(
        mode=ReplayMode.STRICT,
        assertions=(
            ReplayAssertion(kind=AssertionKind.EVENT_SEQUENCE, expected=["start", "process", "end"]),
        ),
    )
    replayer = SessionReplayer(recording, config)
    result = await replayer.replay()
    assert not result.passed
    assert len(result.failed_assertions) == 1


@pytest.mark.asyncio
async def test_replay_relaxed_allows_extra_events():
    rec = SessionRecorder("s", "a")
    rec.record_event("start")
    rec.record_event("extra")
    rec.record_event("end")
    recording = rec.finish()

    config = ReplayConfig(
        mode=ReplayMode.RELAXED,
        assertions=(
            ReplayAssertion(kind=AssertionKind.EVENT_SEQUENCE, expected=["start", "end"]),
        ),
    )
    replayer = SessionReplayer(recording, config)
    result = await replayer.replay()
    assert result.passed


@pytest.mark.asyncio
async def test_replay_tool_call_match():
    rec = SessionRecorder("s", "a")
    rec.record_tool_call("file_read", {"path": "a.py"})
    rec.record_tool_call("file_read", {"path": "b.py"})
    rec.record_tool_call("file_write", {"path": "c.py"})
    recording = rec.finish()

    config = ReplayConfig(assertions=(
        ReplayAssertion(kind=AssertionKind.TOOL_CALL_MATCH, target="file_read", expected=2),
        ReplayAssertion(kind=AssertionKind.TOOL_CALL_MATCH, target="file_write", expected=1),
    ))
    replayer = SessionReplayer(recording, config)
    result = await replayer.replay()
    assert result.passed
    assert result.passed_assertions == 2


@pytest.mark.asyncio
async def test_replay_tool_call_match_fails():
    rec = SessionRecorder("s", "a")
    rec.record_tool_call("file_read")
    recording = rec.finish()

    config = ReplayConfig(assertions=(
        ReplayAssertion(kind=AssertionKind.TOOL_CALL_MATCH, target="file_write", expected=1),
    ))
    replayer = SessionReplayer(recording, config)
    result = await replayer.replay()
    assert not result.passed


@pytest.mark.asyncio
async def test_replay_timing_bound_passes():
    rec = SessionRecorder("s", "a")
    rec.record_tool_call("fast_op", duration_ms=50)
    rec.record_tool_call("medium_op", duration_ms=200)
    recording = rec.finish()

    config = ReplayConfig(assertions=(
        ReplayAssertion(kind=AssertionKind.TIMING_BOUND, expected=500),
    ))
    replayer = SessionReplayer(recording, config)
    result = await replayer.replay()
    assert result.passed


@pytest.mark.asyncio
async def test_replay_timing_bound_fails():
    rec = SessionRecorder("s", "a")
    rec.record_tool_call("slow_op", duration_ms=5000)
    recording = rec.finish()

    config = ReplayConfig(assertions=(
        ReplayAssertion(kind=AssertionKind.TIMING_BOUND, expected=1000),
    ))
    replayer = SessionReplayer(recording, config)
    result = await replayer.replay()
    assert not result.passed


@pytest.mark.asyncio
async def test_mutation_inject_failure():
    rec = SessionRecorder("s", "a")
    rec.record_tool_call("api_call", {"url": "/users"}, result={"users": []}, duration_ms=100)
    recording = rec.finish()

    config = ReplayConfig(
        mode=ReplayMode.MUTATION,
        mutations=(
            Mutation(kind=MutationKind.INJECT_FAILURE, target_tool="api_call", parameters={"error": "500 Internal Server Error"}),
        ),
        assertions=(
            ReplayAssertion(kind=AssertionKind.NO_REGRESSION),
        ),
    )
    replayer = SessionReplayer(recording, config)
    result = await replayer.replay()
    assert not result.passed


@pytest.mark.asyncio
async def test_mutation_timeout():
    rec = SessionRecorder("s", "a")
    rec.record_tool_call("slow_service", result="ok", duration_ms=100)
    recording = rec.finish()

    config = ReplayConfig(
        mode=ReplayMode.MUTATION,
        mutations=(
            Mutation(kind=MutationKind.TIMEOUT, target_tool="slow_service", parameters={"timeout_ms": 30000}),
        ),
        assertions=(
            ReplayAssertion(kind=AssertionKind.NO_REGRESSION),
        ),
    )
    replayer = SessionReplayer(recording, config)
    result = await replayer.replay()
    assert not result.passed


@pytest.mark.asyncio
async def test_mutation_drop_event():
    rec = SessionRecorder("s", "a")
    rec.record_event("start")
    rec.record_event("critical_step")
    rec.record_event("end")
    recording = rec.finish()

    config = ReplayConfig(
        mode=ReplayMode.MUTATION,
        mutations=(
            Mutation(kind=MutationKind.DROP_EVENT, target_sequence=2),
        ),
        assertions=(
            ReplayAssertion(kind=AssertionKind.EVENT_SEQUENCE, expected=["start", "end"]),
        ),
    )
    replayer = SessionReplayer(recording, config)
    result = await replayer.replay()
    assert result.passed


@pytest.mark.asyncio
async def test_mutation_corrupt_output():
    rec = SessionRecorder("s", "a")
    rec.record_tool_call("compute", result={"answer": 42}, duration_ms=10)
    recording = rec.finish()

    config = ReplayConfig(
        mode=ReplayMode.MUTATION,
        mutations=(
            Mutation(kind=MutationKind.CORRUPT_OUTPUT, target_tool="compute"),
        ),
        assertions=(
            ReplayAssertion(kind=AssertionKind.OUTPUT_EXACT, target="compute", expected={"answer": 42}),
        ),
    )
    replayer = SessionReplayer(recording, config)
    result = await replayer.replay()
    assert not result.passed


@pytest.mark.asyncio
async def test_no_regression_passes_clean_session():
    rec = SessionRecorder("s", "a")
    rec.record_event("start")
    rec.record_tool_call("op", result="ok", duration_ms=10)
    rec.record_event("end")
    recording = rec.finish()

    config = ReplayConfig(assertions=(
        ReplayAssertion(kind=AssertionKind.NO_REGRESSION),
    ))
    replayer = SessionReplayer(recording, config)
    result = await replayer.replay()
    assert result.passed


@pytest.mark.asyncio
async def test_golden_snapshot_comparison():
    rec = SessionRecorder("s", "a")
    rec.record_event("init")
    rec.record_event("process")
    rec.record_tool_call("read")
    rec.record_tool_call("write")
    recording = rec.finish()

    golden = GoldenSnapshot(
        recording_id=recording.recording_id,
        name="baseline",
        content={
            "event_count": 2,
            "tool_call_count": 2,
            "event_types": ["init", "process"],
            "tool_names": ["read", "write"],
        },
    )
    diffs = compare_with_golden(recording, golden)
    assert len(diffs) == 0


@pytest.mark.asyncio
async def test_golden_snapshot_detects_drift():
    rec = SessionRecorder("s", "a")
    rec.record_event("init")
    rec.record_tool_call("read")
    recording = rec.finish()

    golden = GoldenSnapshot(
        recording_id=recording.recording_id,
        name="baseline",
        content={
            "event_count": 3,
            "tool_call_count": 2,
        },
    )
    diffs = compare_with_golden(recording, golden)
    assert len(diffs) == 2


@pytest.mark.asyncio
async def test_replay_captures_diffs_on_failure():
    rec = SessionRecorder("s", "a")
    rec.record_event("only_one")
    recording = rec.finish()

    config = ReplayConfig(
        capture_diffs=True,
        assertions=(
            ReplayAssertion(
                kind=AssertionKind.EVENT_SEQUENCE,
                expected=["first", "second"],
                description="should have two events",
            ),
        ),
    )
    replayer = SessionReplayer(recording, config)
    result = await replayer.replay()
    assert not result.passed
    assert len(result.diffs) == 1
    assert result.diffs[0]["description"] == "should have two events"


@pytest.mark.asyncio
async def test_stop_on_first_failure():
    rec = SessionRecorder("s", "a")
    rec.record_event("x")
    recording = rec.finish()

    config = ReplayConfig(
        stop_on_first_failure=True,
        assertions=(
            ReplayAssertion(kind=AssertionKind.EVENT_SEQUENCE, expected=["a", "b"]),
            ReplayAssertion(kind=AssertionKind.EVENT_SEQUENCE, expected=["c", "d"]),
        ),
    )
    replayer = SessionReplayer(recording, config)
    result = await replayer.replay()
    assert not result.passed
    assert result.passed_assertions == 0
    assert len(result.failed_assertions) == 1
