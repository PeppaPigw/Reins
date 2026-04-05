"""Tests for the run timeline — observability projection."""

import pytest

from reins.kernel.event.builder import EventBuilder
from reins.kernel.event.journal import EventJournal
from reins.kernel.types import RunStatus
from reins.timeline.builder import TimelineBuilder, _summarize_event


@pytest.mark.asyncio
async def test_timeline_reconstructs_run(tmp_path):
    """Build a timeline from a sequence of events and verify the projection."""
    journal = EventJournal(tmp_path / "journal.jsonl")
    builder = EventBuilder(journal)

    # Emit a realistic run sequence
    await builder.emit_run_started("run-1", "implement feature X")
    await builder.emit_path_routed("run-1", "deliberative")
    await builder.emit_grant_issued(
        "run-1", "g1", "fs.write.workspace", "workspace", "model", 600,
    )
    await builder.emit_command_executed("run-1", "cmd-1", {"stdout": "ok", "exit_code": 0})
    await builder.emit_eval_completed("run-1", "eval-1", True, details="all tests pass")
    await builder.emit_run_completed("run-1")

    # Build timeline
    tl_builder = TimelineBuilder(journal)
    timeline = await tl_builder.build("run-1")

    assert timeline.run_id == "run-1"
    assert timeline.event_count == 6
    assert timeline.final_status == RunStatus.completed
    assert timeline.failure_class is None
    assert timeline.first_ts is not None
    assert timeline.last_ts is not None
    assert timeline.duration_seconds >= 0

    # Verify entry summaries are human-readable
    assert "Run started: implement feature X" in timeline.entries[0].summary
    assert "Routed to deliberative" in timeline.entries[1].summary
    assert "Granted" in timeline.entries[2].summary
    assert "Executed command" in timeline.entries[3].summary
    assert "Eval PASS" in timeline.entries[4].summary
    assert "Run completed" in timeline.entries[5].summary


@pytest.mark.asyncio
async def test_timeline_captures_failure(tmp_path):
    journal = EventJournal(tmp_path / "journal.jsonl")
    builder = EventBuilder(journal)

    await builder.emit_run_started("run-2", "broken task")
    await builder.emit_run_failed("run-2", "logic_failure", "assertion error in test_foo")

    tl = await TimelineBuilder(journal).build("run-2")
    assert tl.final_status == RunStatus.failed
    assert tl.failure_class == "logic_failure"
    assert "Run failed" in tl.entries[-1].summary


@pytest.mark.asyncio
async def test_timeline_tracks_subagents(tmp_path):
    journal = EventJournal(tmp_path / "journal.jsonl")
    builder = EventBuilder(journal)

    await builder.emit_run_started("run-3", "parent task")
    await builder.commit(
        "run-3", "subagent.spawned",
        {"child_run_id": "child-1", "objective": "sub task", "max_turns": 10,
         "token_budget": 30000, "inherited_grants": []},
        correlation_id="child-1",
    )
    await builder.commit(
        "run-3", "subagent.completed",
        {"child_run_id": "child-1", "objective": "sub task",
         "turns_used": 3, "result_summary": "done"},
        correlation_id="child-1",
    )
    await builder.emit_run_completed("run-3")

    tl = await TimelineBuilder(journal).build("run-3")
    assert "child-1" in tl.subagent_ids
    assert tl.event_count == 4
    assert "Spawned subagent" in tl.entries[1].summary
    assert "Subagent completed" in tl.entries[2].summary


@pytest.mark.asyncio
async def test_timeline_summary_for_context(tmp_path):
    """Test the compact summary output suitable for the context compiler."""
    journal = EventJournal(tmp_path / "journal.jsonl")
    builder = EventBuilder(journal)

    await builder.emit_run_started("run-4", "quick task")
    await builder.emit_path_routed("run-4", "fast")
    await builder.emit_run_completed("run-4")

    summary = await TimelineBuilder(journal).build_summary("run-4")
    assert summary["run_id"] == "run-4"
    assert summary["status"] == "completed"
    assert summary["event_count"] == 3
    assert len(summary["entries"]) == 3
    assert summary["entries"][0]["type"] == "run.started"


@pytest.mark.asyncio
async def test_timeline_pending_approvals(tmp_path):
    journal = EventJournal(tmp_path / "journal.jsonl")
    builder = EventBuilder(journal)

    await builder.emit_run_started("run-5", "needs approval")
    await builder.emit_approval_requested("run-5", "ap-1", "deploy to prod")

    tl = await TimelineBuilder(journal).build("run-5")
    assert tl.final_status == RunStatus.waiting_approval
    assert "ap-1" in tl.pending_approvals
    assert "Approval requested" in tl.entries[-1].summary
