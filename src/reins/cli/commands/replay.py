"""Time-travel replay CLI commands.

Provides `reins replay state`, `reins replay events`, and `reins replay diff`
subcommands that reconstruct historical run state from the event journal.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import typer

from reins.cli import utils
from reins.kernel.event.journal import EventJournal
from reins.kernel.event.time_travel import RunTimeTravel

app = typer.Typer(
    help=(
        "Time-travel replay commands.\n\n"
        "Reconstruct historical run state from the event journal.\n\n"
        "Examples:\n"
        "  reins replay state RUN-123 --at 2024-01-15T10:30:00Z\n"
        "  reins replay events RUN-123 --type task.created --limit 20\n"
        "  reins replay diff RUN-123 --from 2024-01-15T10:00:00Z --to 2024-01-15T11:00:00Z\n"
    )
)


@app.command("state")
def replay_state(
    run_id: str = typer.Argument(help="Run ID to replay."),
    at: str | None = typer.Option(None, "--at", help="ISO timestamp to replay to."),
    output_format: str = typer.Option("text", "--format", help="Output format: text or json."),
) -> None:
    """Reconstruct run state at a point in time."""
    repo_root = utils.find_repo_root()
    journal = utils.get_journal(repo_root)
    time_travel = RunTimeTravel(journal)

    try:
        if at is not None:
            state = asyncio.run(time_travel.reconstruct_at(run_id, timestamp=at))
        else:
            state = asyncio.run(time_travel.reconstruct_run_state(run_id))
    except Exception as exc:
        utils.exit_with_error(f"Failed to reconstruct state: {exc}")
        return

    if output_format == "json":
        data = {
            "run_id": state.run_id,
            "status": state.status.value,
            "current_node_id": state.current_node_id,
            "open_handles": len(state.open_handles),
            "active_grants": len(state.active_grants),
            "pending_approvals": len(state.pending_approvals),
            "active_task_id": state.active_task_id,
        }
        if at is not None:
            data["replayed_at"] = at
        typer.echo(json.dumps(data, indent=2))
    else:
        utils.console.print(f"[bold]Run State: {state.run_id}[/bold]")
        if at is not None:
            utils.console.print(f"  Replayed at: {at}")
        rows = [
            {"field": "status", "value": state.status.value},
            {"field": "current_node_id", "value": state.current_node_id or "-"},
            {"field": "open_handles", "value": str(len(state.open_handles))},
            {"field": "active_grants", "value": str(len(state.active_grants))},
            {"field": "pending_approvals", "value": str(len(state.pending_approvals))},
            {"field": "active_task_id", "value": state.active_task_id or "-"},
        ]
        utils.console.print(utils.format_table(rows, ["field", "value"]))


@app.command("events")
def replay_events(
    run_id: str = typer.Argument(help="Run ID."),
    since: str | None = typer.Option(None, "--since", help="Show events after this ISO timestamp."),
    until: str | None = typer.Option(None, "--until", help="Show events before this ISO timestamp."),
    event_type: str | None = typer.Option(None, "--type", help="Filter by event type."),
    limit: int = typer.Option(50, "--limit", help="Max events to show."),
) -> None:
    """List events for a run with optional filtering."""
    repo_root = utils.find_repo_root()
    journal = utils.get_journal(repo_root)

    async def _read_events():
        events = []
        async for event in journal.read_from(run_id):
            events.append(event)
        return events

    try:
        events = asyncio.run(_read_events())
    except Exception as exc:
        utils.exit_with_error(f"Failed to read events: {exc}")
        return

    if not events:
        utils.exit_with_error(f"No events found for run '{run_id}'.")
        return

    # Apply filters
    if since is not None:
        since_dt = datetime.fromisoformat(since)
        events = [e for e in events if e.ts >= since_dt]

    if until is not None:
        until_dt = datetime.fromisoformat(until)
        events = [e for e in events if e.ts <= until_dt]

    if event_type is not None:
        events = [e for e in events if e.type == event_type]

    # Apply limit
    events = events[-limit:]

    if not events:
        utils.console.print("[yellow]No events match the given filters.[/yellow]")
        return

    rows = [
        {
            "seq": str(e.seq),
            "timestamp": utils.format_timestamp(e.ts),
            "type": e.type,
            "actor": e.actor.value,
        }
        for e in events
    ]
    utils.console.print(utils.format_table(rows, ["seq", "timestamp", "type", "actor"]))
    utils.console.print(f"\n[dim]Showing {len(events)} event(s)[/dim]")


@app.command("diff")
def replay_diff(
    run_id: str = typer.Argument(help="Run ID."),
    from_ts: str = typer.Option(..., "--from", help="Start ISO timestamp."),
    to_ts: str = typer.Option(..., "--to", help="End ISO timestamp."),
) -> None:
    """Show state changes between two timestamps."""
    repo_root = utils.find_repo_root()
    journal = utils.get_journal(repo_root)
    time_travel = RunTimeTravel(journal)

    try:
        state_from = asyncio.run(time_travel.reconstruct_at(run_id, timestamp=from_ts))
        state_to = asyncio.run(time_travel.reconstruct_at(run_id, timestamp=to_ts))
    except Exception as exc:
        utils.exit_with_error(f"Failed to reconstruct states: {exc}")
        return

    utils.console.print(f"[bold]State Diff: {run_id}[/bold]")
    utils.console.print(f"  From: {from_ts}")
    utils.console.print(f"  To:   {to_ts}")
    utils.console.print("")

    changes: list[dict[str, str]] = []

    if state_from.status != state_to.status:
        changes.append({
            "field": "status",
            "from": state_from.status.value,
            "to": state_to.status.value,
        })

    if state_from.current_node_id != state_to.current_node_id:
        changes.append({
            "field": "current_node_id",
            "from": state_from.current_node_id or "-",
            "to": state_to.current_node_id or "-",
        })

    if len(state_from.open_handles) != len(state_to.open_handles):
        changes.append({
            "field": "open_handles",
            "from": str(len(state_from.open_handles)),
            "to": str(len(state_to.open_handles)),
        })

    if len(state_from.active_grants) != len(state_to.active_grants):
        changes.append({
            "field": "active_grants",
            "from": str(len(state_from.active_grants)),
            "to": str(len(state_to.active_grants)),
        })

    if state_from.active_task_id != state_to.active_task_id:
        changes.append({
            "field": "active_task_id",
            "from": state_from.active_task_id or "-",
            "to": state_to.active_task_id or "-",
        })

    if state_from.last_failure_class != state_to.last_failure_class:
        changes.append({
            "field": "last_failure_class",
            "from": state_from.last_failure_class.value if state_from.last_failure_class else "-",
            "to": state_to.last_failure_class.value if state_to.last_failure_class else "-",
        })

    if not changes:
        utils.console.print("[dim]No state changes detected between timestamps.[/dim]")
        return

    utils.console.print(utils.format_table(changes, ["field", "from", "to"]))
