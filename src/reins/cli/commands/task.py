from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import typer

from reins.cli import utils
from reins.cli.commands import task_context
from reins.export.task_exporter import TaskExporter
from reins.task.manager import TaskManager
from reins.task.metadata import TaskStatus

app = typer.Typer(
    help=(
        "Task lifecycle and context commands.\n\n"
        "Examples:\n"
        "  reins task create \"Implement JWT auth\" --type backend --priority P0\n"
        "  reins task start 04-18-implement-jwt-auth --assignee peppa\n"
        "  reins task init-context 04-18-implement-jwt-auth backend\n"
    )
)


def _manager(repo_root: Path, run_id: str) -> tuple[TaskManager, TaskExporter]:
    projection = utils.rebuild_task_projection(repo_root)
    manager = TaskManager(utils.get_journal(repo_root), projection, run_id=run_id)
    exporter = TaskExporter(projection, repo_root / ".reins" / "tasks")
    return manager, exporter


@app.command("create")
def create_command(
    title: str = typer.Argument(..., help="Task title."),
    slug: str | None = typer.Option(None, "--slug", help="Optional slug override."),
    package: str | None = typer.Option(None, "--package", help="Optional package metadata."),
    priority: str = typer.Option("P1", "--priority", help="Task priority P0-P3."),
    task_type: str = typer.Option("backend", "--type", help="Task type."),
    prd: str = typer.Option("", "--prd", help="Inline PRD content."),
    acceptance: list[str] | None = typer.Option(
        None,
        "--acceptance",
        help="Repeatable acceptance criterion.",
    ),
    assignee: str | None = typer.Option(None, "--assignee", help="Initial assignee."),
    base_branch: str = typer.Option("main", "--base-branch", help="Base branch."),
) -> None:
    """
    Create a new task and export its filesystem artifacts.
    """
    repo_root = utils.find_repo_root()
    run_id = utils.make_run_id("task")
    try:
        if priority not in {"P0", "P1", "P2", "P3"}:
            raise utils.CLIError("Priority must be one of: P0, P1, P2, P3")

        manager, exporter = _manager(repo_root, run_id)
        identity = utils.read_developer_identity(repo_root)
        created_by = identity["name"] if identity else "cli"
        final_assignee = assignee or created_by or "unassigned"
        metadata: dict[str, Any] = {}
        if package:
            metadata["package"] = package

        task_id = asyncio.run(
            manager.create_task(
                title=title,
                task_type=task_type,
                prd_content=prd or title,
                acceptance_criteria=acceptance or [],
                created_by=created_by,
                slug=slug,
                priority=priority,
                assignee=final_assignee,
                base_branch=base_branch,
                metadata=metadata,
            )
        )
        exporter.export_task(task_id)

        utils.console.print(f"[green]Created task[/green] [bold]{task_id}[/bold].")
    except Exception as exc:  # pragma: no cover - exercised via CLI tests
        asyncio.run(utils.emit_cli_error(repo_root, run_id, "task.create", exc, {"title": title}))
        utils.exit_with_error(str(exc))


@app.command("list")
def list_command(
    status: str | None = typer.Option(None, "--status", help="Filter by status."),
    assignee: str | None = typer.Option(None, "--assignee", help="Filter by assignee."),
    include_archived: bool = typer.Option(False, "--include-archived", help="Include archived tasks."),
) -> None:
    """
    List tasks from the rebuilt task projection.
    """
    repo_root = utils.find_repo_root()
    projection = utils.rebuild_task_projection(repo_root)
    status_filter = TaskStatus(status) if status else None
    tasks = projection.list_tasks(
        status=status_filter,
        assignee=assignee,
        include_archived=include_archived,
    )

    rows = [
        {
            "task_id": task.task_id,
            "title": task.title,
            "status": task.status.value,
            "assignee": task.assignee,
            "priority": task.priority,
            "type": task.task_type,
        }
        for task in tasks
    ]
    if not rows:
        utils.console.print("[yellow]No tasks found.[/yellow]")
        return
    utils.console.print(utils.format_table(rows, ["task_id", "title", "status", "assignee", "priority", "type"]))


@app.command("show")
def show_command(task_id: str = typer.Argument(..., help="Task ID.")) -> None:
    """
    Show task metadata, PRD, and available context files.
    """
    repo_root = utils.find_repo_root()
    projection = utils.rebuild_task_projection(repo_root)
    task = projection.get_task(task_id)
    if task is None:
        utils.exit_with_error(f"Task not found: {task_id}")

    utils.console.print(f"[bold]{task.title}[/bold] ({task.task_id})")
    utils.console.print(f"Status: {task.status.value}")
    utils.console.print(f"Type: {task.task_type}")
    utils.console.print(f"Priority: {task.priority}")
    utils.console.print(f"Assignee: {task.assignee}")
    utils.console.print(f"Branch: {task.branch} -> {task.base_branch}")
    if task.parent_task_id:
        utils.console.print(f"Parent: {task.parent_task_id}")
    if task.metadata:
        utils.console.print(f"Metadata: {task.metadata}")

    prd_path = utils.task_dir(repo_root, task_id) / "prd.md"
    if prd_path.exists():
        utils.console.print("")
        utils.console.print(prd_path.read_text(encoding="utf-8"))

    context_messages = utils.load_task_context_messages(utils.task_dir(repo_root, task_id))
    if context_messages:
        utils.console.print("")
        rows = [{"agent": agent, "messages": len(messages)} for agent, messages in sorted(context_messages.items())]
        utils.console.print(utils.format_table(rows, ["agent", "messages"]))


@app.command("start")
def start_command(
    task_id: str = typer.Argument(..., help="Task ID."),
    assignee: str | None = typer.Option(None, "--assignee", help="Assignee starting the task."),
) -> None:
    """
    Start a task and update `.reins/.current-task`.
    """
    repo_root = utils.find_repo_root()
    run_id = utils.make_run_id("task")
    try:
        manager, _ = _manager(repo_root, run_id)
        identity = utils.read_developer_identity(repo_root)
        final_assignee = assignee or (identity["name"] if identity else "cli")
        asyncio.run(manager.start_task(task_id, assignee=final_assignee))
        utils.set_current_task_pointer(repo_root, task_id)
        utils.console.print(f"[green]Started task[/green] [bold]{task_id}[/bold].")
    except Exception as exc:  # pragma: no cover - exercised via CLI tests
        asyncio.run(utils.emit_cli_error(repo_root, run_id, "task.start", exc, {"task_id": task_id}))
        utils.exit_with_error(str(exc))


@app.command("finish")
def finish_command(
    task_id: str = typer.Argument(..., help="Task ID."),
    note: str = typer.Option("Completed via CLI", "--note", help="Completion note."),
) -> None:
    """
    Finish a task and clear `.reins/.current-task` if it is active.
    """
    repo_root = utils.find_repo_root()
    run_id = utils.make_run_id("task")
    try:
        manager, exporter = _manager(repo_root, run_id)
        identity = utils.read_developer_identity(repo_root)
        asyncio.run(
            manager.complete_task(
                task_id,
                outcome={"note": note, "completed_via": "cli"},
                completed_by=identity["name"] if identity else "cli",
            )
        )
        exporter.export_task(task_id)
        if utils.get_current_task_id(repo_root) == task_id:
            utils.set_current_task_pointer(repo_root, None)
        utils.console.print(f"[green]Finished task[/green] [bold]{task_id}[/bold].")
    except Exception as exc:  # pragma: no cover - exercised via CLI tests
        asyncio.run(utils.emit_cli_error(repo_root, run_id, "task.finish", exc, {"task_id": task_id}))
        utils.exit_with_error(str(exc))


@app.command("archive")
def archive_command(
    task_id: str = typer.Argument(..., help="Task ID."),
    reason: str | None = typer.Option(None, "--reason", help="Optional archive reason."),
) -> None:
    """
    Archive a task and clear `.reins/.current-task` if it is active.
    """
    repo_root = utils.find_repo_root()
    run_id = utils.make_run_id("task")
    try:
        manager, exporter = _manager(repo_root, run_id)
        identity = utils.read_developer_identity(repo_root)
        asyncio.run(
            manager.archive_task(
                task_id,
                archived_by=identity["name"] if identity else "cli",
                reason=reason,
            )
        )
        exporter.export_task(task_id)
        if utils.get_current_task_id(repo_root) == task_id:
            utils.set_current_task_pointer(repo_root, None)
        utils.console.print(f"[green]Archived task[/green] [bold]{task_id}[/bold].")
    except Exception as exc:  # pragma: no cover - exercised via CLI tests
        asyncio.run(utils.emit_cli_error(repo_root, run_id, "task.archive", exc, {"task_id": task_id}))
        utils.exit_with_error(str(exc))


task_context.register(app)
