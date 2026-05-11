"""Tests for time-travel replay CLI commands."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reins.cli.commands.replay import app
from reins.cli.main import app as main_app
from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.event.journal import EventJournal
from reins.kernel.types import Actor


runner = CliRunner()


def _make_event(
    run_id: str,
    event_type: str,
    seq: int,
    ts: datetime,
    payload: dict | None = None,
) -> EventEnvelope:
    """Create a test event envelope."""
    return EventEnvelope(
        run_id=run_id,
        actor=Actor.runtime,
        type=event_type,
        payload=payload or {},
        seq=seq,
        ts=ts,
    )


def _setup_journal(tmp_path: Path, events: list[EventEnvelope]) -> Path:
    """Write events to a journal file and return the repo root."""
    repo_root = tmp_path / "project"
    repo_root.mkdir()
    reins_dir = repo_root / ".reins"
    reins_dir.mkdir()
    journal_path = reins_dir / "journal.jsonl"

    from reins.kernel.event.envelope import event_to_dict

    lines = []
    for event in events:
        lines.append(json.dumps(event_to_dict(event), sort_keys=True))
    journal_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return repo_root


def _base_time() -> datetime:
    return datetime(2024, 6, 15, 10, 0, 0, tzinfo=UTC)


def _sample_events(run_id: str = "test-run-001") -> list[EventEnvelope]:
    """Create a sequence of events for testing."""
    base = _base_time()
    return [
        _make_event(run_id, "run.started", 1, base),
        _make_event(run_id, "path.routed", 2, base + timedelta(seconds=5), {"path": "fast"}),
        _make_event(
            run_id, "command.dispatched", 3, base + timedelta(seconds=10),
            {"command_id": "cmd-1", "adapter": "shell"},
        ),
        _make_event(
            run_id, "command.completed", 4, base + timedelta(seconds=15),
            {"command_id": "cmd-1", "exit_code": 0},
        ),
    ]


def test_replay_state_reconstructs_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """replay state reconstructs the full run state."""
    events = _sample_events()
    repo_root = _setup_journal(tmp_path, events)
    monkeypatch.chdir(repo_root)

    result = runner.invoke(app, ["state", "test-run-001"])
    assert result.exit_code == 0
    assert "test-run-001" in result.output
    assert "executing" in result.output


def test_replay_state_at_timestamp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """replay state --at reconstructs state at a specific timestamp."""
    events = _sample_events()
    repo_root = _setup_journal(tmp_path, events)
    monkeypatch.chdir(repo_root)

    # Replay at a time after run.started but before path.routed
    at_ts = (_base_time() + timedelta(seconds=2)).isoformat()
    result = runner.invoke(app, ["state", "test-run-001", "--at", at_ts])
    assert result.exit_code == 0
    assert "routing" in result.output


def test_replay_state_json_format(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """replay state --format json outputs JSON."""
    events = _sample_events()
    repo_root = _setup_journal(tmp_path, events)
    monkeypatch.chdir(repo_root)

    result = runner.invoke(app, ["state", "test-run-001", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["run_id"] == "test-run-001"
    assert data["status"] == "executing"


def test_replay_events_lists_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """replay events lists all events for a run."""
    events = _sample_events()
    repo_root = _setup_journal(tmp_path, events)
    monkeypatch.chdir(repo_root)

    result = runner.invoke(app, ["events", "test-run-001"])
    assert result.exit_code == 0
    assert "run.started" in result.output
    assert "path.routed" in result.output
    assert "4 event(s)" in result.output


def test_replay_events_filters_by_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """replay events --type filters by event type."""
    events = _sample_events()
    repo_root = _setup_journal(tmp_path, events)
    monkeypatch.chdir(repo_root)

    result = runner.invoke(app, ["events", "test-run-001", "--type", "run.started"])
    assert result.exit_code == 0
    assert "run.started" in result.output
    assert "path.routed" not in result.output
    assert "1 event(s)" in result.output


def test_replay_events_filters_by_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """replay events --since/--until filters by timestamp range."""
    events = _sample_events()
    repo_root = _setup_journal(tmp_path, events)
    monkeypatch.chdir(repo_root)

    since_ts = (_base_time() + timedelta(seconds=8)).isoformat()
    result = runner.invoke(app, ["events", "test-run-001", "--since", since_ts])
    assert result.exit_code == 0
    assert "run.started" not in result.output
    assert "command.dispatched" in result.output


def test_replay_events_respects_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """replay events --limit restricts output count."""
    events = _sample_events()
    repo_root = _setup_journal(tmp_path, events)
    monkeypatch.chdir(repo_root)

    result = runner.invoke(app, ["events", "test-run-001", "--limit", "2"])
    assert result.exit_code == 0
    assert "2 event(s)" in result.output


def test_replay_diff_shows_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """replay diff shows state changes between two timestamps."""
    events = _sample_events()
    repo_root = _setup_journal(tmp_path, events)
    monkeypatch.chdir(repo_root)

    from_ts = (_base_time() + timedelta(seconds=2)).isoformat()
    to_ts = (_base_time() + timedelta(seconds=12)).isoformat()
    result = runner.invoke(app, ["diff", "test-run-001", "--from", from_ts, "--to", to_ts])
    assert result.exit_code == 0
    assert "status" in result.output
    assert "routing" in result.output
    assert "executing" in result.output


def test_replay_command_registered_in_app() -> None:
    """replay command is registered in the main CLI app."""
    # Check that 'replay' is a registered command group
    command_names = [cmd.name for cmd in main_app.registered_groups]
    assert "replay" in command_names


def test_replay_nonexistent_run_shows_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """replay state for a nonexistent run shows empty/default state."""
    events = _sample_events()
    repo_root = _setup_journal(tmp_path, events)
    monkeypatch.chdir(repo_root)

    result = runner.invoke(app, ["state", "nonexistent-run"])
    assert result.exit_code == 0
    # Should show default created state since no events match
    assert "created" in result.output
