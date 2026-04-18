from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import typer

from reins.cli import utils
from reins.context.spec_projection import ContextSpecProjection
from reins.kernel.event.envelope import event_to_dict
from reins.kernel.reducer.reducer import reduce
from reins.kernel.reducer.state import RunState
from reins.task.projection import TaskContextProjection

app = typer.Typer(
    help=(
        "Journal inspection and export commands.\n\n"
        "Examples:\n"
        "  reins journal show --limit 20 --type task.created\n"
        "  reins journal export out.json --format json\n"
    )
)


def _filtered_events(
    repo_root: Path,
    *,
    event_type: str | None = None,
    actor: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
) -> list:
    events = utils.load_all_events(repo_root)
    if event_type:
        events = [event for event in events if event.type == event_type]
    if actor:
        events = [event for event in events if event.actor.value == actor]
    if from_ts:
        start = datetime.fromisoformat(from_ts)
        events = [event for event in events if event.ts >= start]
    if to_ts:
        end = datetime.fromisoformat(to_ts)
        events = [event for event in events if event.ts <= end]
    return events


@app.command("show")
def show_command(
    limit: int = typer.Option(20, "--limit", min=1, help="Maximum number of events."),
    event_type: str | None = typer.Option(None, "--type", help="Filter by event type."),
    actor: str | None = typer.Option(None, "--actor", help="Filter by actor."),
) -> None:
    """
    Show recent events from the journal.
    """
    repo_root = utils.find_repo_root()
    events = _filtered_events(repo_root, event_type=event_type, actor=actor)[-limit:]
    rows = [
        {
            "ts": utils.format_timestamp(event.ts),
            "run_id": event.run_id,
            "seq": str(event.seq),
            "type": event.type,
            "actor": event.actor.value,
        }
        for event in events
    ]
    if not rows:
        utils.console.print("[yellow]No journal events found.[/yellow]")
        return
    utils.console.print(utils.format_table(rows, ["ts", "run_id", "seq", "type", "actor"]))


@app.command("replay")
def replay_command(
    from_ts: str | None = typer.Option(None, "--from", help="Inclusive ISO timestamp."),
    to_ts: str | None = typer.Option(None, "--to", help="Inclusive ISO timestamp."),
) -> None:
    """
    Replay events to reconstruct task/spec/run summaries.
    """
    repo_root = utils.find_repo_root()
    events = _filtered_events(repo_root, from_ts=from_ts, to_ts=to_ts)
    task_projection = TaskContextProjection()
    spec_projection = ContextSpecProjection()
    for event in events:
        task_projection.apply_event(event)
        spec_projection.apply_event(event)

    run_states: dict[str, RunState] = {}
    for event in events:
        state = run_states.setdefault(event.run_id, RunState(run_id=event.run_id))
        run_states[event.run_id] = reduce(state, event)

    utils.console.print(f"Events replayed: [bold]{len(events)}[/bold]")
    utils.console.print(f"Tasks reconstructed: [bold]{task_projection.count_tasks()}[/bold]")
    utils.console.print(f"Specs reconstructed: [bold]{spec_projection.count_specs()}[/bold]")

    if run_states:
        rows = [
            {"run_id": run_id, "status": state.status.value}
            for run_id, state in sorted(run_states.items())
        ]
        utils.console.print("")
        utils.console.print(utils.format_table(rows, ["run_id", "status"]))


@app.command("export")
def export_command(
    output_file: Path = typer.Argument(..., resolve_path=True),
    format: str = typer.Option("json", "--format", help="json or jsonl"),
) -> None:
    """
    Export journal contents to JSON or JSONL.
    """
    repo_root = utils.find_repo_root()
    events = utils.load_all_events(repo_root)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    if format == "json":
        output_file.write_text(
            json.dumps([event_to_dict(event) for event in events], indent=2),
            encoding="utf-8",
        )
    elif format == "jsonl":
        output_file.write_text(
            "".join(json.dumps(event_to_dict(event), sort_keys=True) + "\n" for event in events),
            encoding="utf-8",
        )
    else:
        utils.exit_with_error("Export format must be one of: json, jsonl")
    utils.console.print(f"[green]Exported journal[/green] to {output_file}.")


@app.command("stats")
def stats_command() -> None:
    """
    Show aggregate journal statistics by type, actor, and run.
    """
    repo_root = utils.find_repo_root()
    events = utils.load_all_events(repo_root)
    summary = utils.summarize_events(events)
    utils.console.print(f"Total events: [bold]{summary['total']}[/bold]")

    if summary["types"]:
        utils.console.print("")
        type_rows = [{"type": key, "count": str(value)} for key, value in summary["types"].most_common()]
        utils.console.print(utils.format_table(type_rows, ["type", "count"]))

    if summary["actors"]:
        utils.console.print("")
        actor_rows = [{"actor": key, "count": str(value)} for key, value in summary["actors"].most_common()]
        utils.console.print(utils.format_table(actor_rows, ["actor", "count"]))
