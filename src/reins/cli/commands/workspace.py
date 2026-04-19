from __future__ import annotations

from datetime import datetime
from pathlib import Path

import typer

from reins.cli import utils
from reins.workspace.activity import ActivityReporter
from reins.workspace.context import DeveloperContext
from reins.workspace.manager import WorkspaceManager

app = typer.Typer(help="Workspace management commands.")


def _manager(repo_root: Path, run_id: str) -> WorkspaceManager:
    return WorkspaceManager(
        repo_root / ".reins",
        journal=utils.get_journal(repo_root),
        run_id=run_id,
    )


def _parse_date(value: str | None, *, end: bool = False) -> datetime:
    if value is None:
        return datetime.now()

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None and len(value) == 10 and end:
        return datetime.combine(parsed.date(), datetime.max.time())
    return parsed


@app.command("init")
def init_command(developer: str = typer.Argument(..., help="Developer name.")) -> None:
    """Initialize a developer workspace and set the active identity."""
    repo_root = utils.find_repo_root()
    run_id = utils.make_run_id("workspace")
    context = DeveloperContext(repo_root / ".reins")
    existing = context.get_current_developer()
    if existing and existing != developer:
        utils.exit_with_error(
            f"Developer already initialized as {existing}. Remove .reins/.developer to switch."
        )

    context.set_current_developer(developer)
    workspace_dir = _manager(repo_root, run_id).initialize_workspace(developer)
    utils.console.print(f"[green]Initialized workspace[/green] [bold]{developer}[/bold].")
    utils.console.print(f"Workspace: {utils.relpath(workspace_dir, repo_root)}")


@app.command("list")
def list_command() -> None:
    """List all developer workspaces."""
    repo_root = utils.find_repo_root()
    manager = _manager(repo_root, utils.make_run_id("workspace"))
    workspaces = manager.list_workspaces()
    if not workspaces:
        utils.console.print("[yellow]No workspaces found.[/yellow]")
        return

    rows = [{"developer": name} for name in workspaces]
    utils.console.print(utils.format_table(rows, ["developer"]))


@app.command("stats")
def stats_command(developer: str = typer.Argument(..., help="Developer name.")) -> None:
    """Show workspace statistics for a developer."""
    repo_root = utils.find_repo_root()
    manager = _manager(repo_root, utils.make_run_id("workspace"))
    context = DeveloperContext(repo_root / ".reins")
    stats = manager.get_workspace_stats(developer)

    rows = [
        {"field": "developer", "value": stats.developer},
        {"field": "total_sessions", "value": str(stats.total_sessions)},
        {"field": "total_commits", "value": str(stats.total_commits)},
        {
            "field": "last_active",
            "value": stats.last_active.isoformat() if stats.last_active else "-",
        },
        {"field": "journal_files", "value": str(stats.journal_files)},
        {"field": "total_lines", "value": str(stats.total_lines)},
        {"field": "archived_journal_files", "value": str(stats.archived_journal_files)},
    ]
    utils.console.print(utils.format_table(rows, ["field", "value"]))

    tasks = context.get_developer_tasks(developer)
    if tasks:
        utils.console.print("")
        utils.console.print("[bold]My Tasks[/bold]")
        task_rows = [
            {"task_id": task.task_id, "title": task.title, "status": task.status.value}
            for task in tasks
        ]
        utils.console.print(utils.format_table(task_rows, ["task_id", "title", "status"]))


@app.command("cleanup")
def cleanup_command(
    developer: str = typer.Argument(..., help="Developer name."),
    keep_days: int = typer.Option(30, "--keep-days", help="Days of history to keep active."),
) -> None:
    """Archive older journal files for a developer workspace."""
    repo_root = utils.find_repo_root()
    manager = _manager(repo_root, utils.make_run_id("workspace"))
    manager.cleanup_workspace(developer, keep_recent_days=keep_days)
    utils.console.print(
        f"[green]Cleaned workspace[/green] [bold]{developer}[/bold] (keep_days={keep_days})."
    )


@app.command("report")
def report_command(
    developer: str = typer.Argument(..., help="Developer name."),
    start_date: str | None = typer.Option(None, "--start-date", help="Start date (ISO or YYYY-MM-DD)."),
    end_date: str | None = typer.Option(None, "--end-date", help="End date (ISO or YYYY-MM-DD)."),
) -> None:
    """Generate an activity report for a developer."""
    repo_root = utils.find_repo_root()
    reporter = ActivityReporter(repo_root / ".reins")
    report = reporter.generate_activity_report(
        developer,
        _parse_date(start_date),
        _parse_date(end_date, end=True),
    )
    rows = [
        {"field": "developer", "value": report.developer},
        {"field": "period", "value": report.period},
        {"field": "sessions_count", "value": str(report.sessions_count)},
        {"field": "commits_count", "value": str(report.commits_count)},
        {"field": "tasks_completed", "value": str(report.tasks_completed)},
        {"field": "files_changed", "value": str(report.files_changed)},
        {"field": "lines_added", "value": str(report.lines_added)},
        {"field": "lines_removed", "value": str(report.lines_removed)},
    ]
    utils.console.print(utils.format_table(rows, ["field", "value"]))
