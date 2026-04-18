from __future__ import annotations

import asyncio

import typer

from reins.cli import utils

app = typer.Typer(
    help=(
        "Worktree lifecycle commands.\n\n"
        "Examples:\n"
        "  reins worktree create agent-1 task-123 --branch feat/task-123\n"
        "  reins worktree cleanup-orphans --force\n"
    )
)


@app.command("create")
def create_command(
    agent_id: str = typer.Argument(..., help="Agent identifier."),
    task_id: str = typer.Argument(..., help="Task identifier."),
    branch: str = typer.Option(..., "--branch", help="Branch name for the worktree."),
    base: str = typer.Option("main", "--base", help="Base branch."),
) -> None:
    """
    Create a tracked worktree for an agent/task pair.
    """
    repo_root = utils.find_repo_root()
    run_id = utils.make_run_id("worktree")
    manager = utils.hydrate_worktree_manager(repo_root, run_id)
    try:
        state = asyncio.run(
            manager.create_worktree_for_agent(
                agent_id=agent_id,
                task_id=task_id,
                branch_name=branch,
                base_branch=base,
            )
        )
    except Exception as exc:  # pragma: no cover - exercised via CLI tests
        asyncio.run(
            utils.emit_cli_error(
                repo_root,
                run_id,
                "worktree.create",
                exc,
                {"agent_id": agent_id, "task_id": task_id, "branch": branch},
            )
        )
        utils.exit_with_error(str(exc))
        return

    utils.console.print(f"[green]Created worktree[/green] [bold]{state.worktree_id}[/bold].")
    utils.console.print(f"Path: {state.worktree_path}")


@app.command("list")
def list_command(
    active_only: bool = typer.Option(False, "--active-only", help="Only show tracked active worktrees."),
) -> None:
    """
    List tracked worktrees and registry information.
    """
    repo_root = utils.find_repo_root()
    run_id = utils.make_run_id("worktree")
    manager = utils.hydrate_worktree_manager(repo_root, run_id)
    registry = utils.get_agent_registry(repo_root, run_id)
    records = {record.agent_id: record for record in asyncio.run(registry.list_all())}
    rows = []
    for state in manager.list_worktrees():
        record = records.get(state.agent_id)
        rows.append(
            {
                "worktree_id": state.worktree_id,
                "agent_id": state.agent_id,
                "task_id": state.task_id or "",
                "branch": state.branch_name,
                "status": record.status if record else "unknown",
                "path": utils.relpath(state.worktree_path, repo_root),
            }
        )

    if not active_only:
        tracked_paths = {state.worktree_path for state in manager.list_worktrees()}
        for path in utils.discover_git_worktrees(repo_root):
            if path == repo_root or path in tracked_paths:
                continue
            rows.append(
                {
                    "worktree_id": "(orphan)",
                    "agent_id": "",
                    "task_id": "",
                    "branch": "",
                    "status": "orphan",
                    "path": utils.relpath(path, repo_root),
                }
            )

    if not rows:
        utils.console.print("[yellow]No worktrees found.[/yellow]")
        return
    utils.console.print(utils.format_table(rows, ["worktree_id", "agent_id", "task_id", "branch", "status", "path"]))


@app.command("verify")
def verify_command(worktree_id: str = typer.Argument(..., help="Worktree ID.")) -> None:
    """
    Run verification hooks for a tracked worktree.
    """
    repo_root = utils.find_repo_root()
    run_id = utils.make_run_id("worktree")
    manager = utils.hydrate_worktree_manager(repo_root, run_id)
    try:
        results = asyncio.run(manager.verify_worktree(worktree_id))
    except Exception as exc:  # pragma: no cover - exercised via CLI tests
        asyncio.run(utils.emit_cli_error(repo_root, run_id, "worktree.verify", exc, {"worktree_id": worktree_id}))
        utils.exit_with_error(str(exc))
        return
    rows = [
        {
            "command": result["command"],
            "returncode": str(result["returncode"]),
            "stderr": result["stderr"].strip(),
        }
        for result in results
    ]
    utils.console.print(utils.format_table(rows, ["command", "returncode", "stderr"]))


@app.command("cleanup")
def cleanup_command(
    worktree_id: str = typer.Argument(..., help="Worktree ID."),
    force: bool = typer.Option(False, "--force", help="Force cleanup and discard changes."),
) -> None:
    """
    Remove a tracked worktree.
    """
    repo_root = utils.find_repo_root()
    run_id = utils.make_run_id("worktree")
    manager = utils.hydrate_worktree_manager(repo_root, run_id)
    try:
        asyncio.run(manager.cleanup_agent_worktree(worktree_id, force=force, removed_by="cli"))
    except Exception as exc:  # pragma: no cover - exercised via CLI tests
        asyncio.run(utils.emit_cli_error(repo_root, run_id, "worktree.cleanup", exc, {"worktree_id": worktree_id}))
        utils.exit_with_error(str(exc))
        return
    utils.console.print(f"[green]Removed worktree[/green] [bold]{worktree_id}[/bold].")


@app.command("cleanup-orphans")
def cleanup_orphans_command(
    force: bool = typer.Option(False, "--force", help="Force cleanup and discard changes."),
) -> None:
    """
    Remove orphaned git worktrees that are not tracked by Reins.
    """
    repo_root = utils.find_repo_root()
    run_id = utils.make_run_id("worktree")
    manager = utils.hydrate_worktree_manager(repo_root, run_id)
    cleaned = asyncio.run(manager.cleanup_orphans(force=force))
    if not cleaned:
        utils.console.print("[yellow]No orphaned worktrees cleaned up.[/yellow]")
        return
    rows = [{"path": utils.relpath(path, repo_root)} for path in cleaned]
    utils.console.print(utils.format_table(rows, ["path"]))
