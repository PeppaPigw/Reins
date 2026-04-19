from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path

import typer

from reins.cli import utils
from reins.isolation.types import WorktreeState
from reins.isolation.worktree_config import load_worktree_config

app = typer.Typer(
    help=(
        "Worktree lifecycle commands.\n\n"
        "Examples:\n"
        "  reins worktree create feature-lane --task 04-19-cli\n"
        "  reins worktree create agent-1 task-123 --branch feat/task-123\n"
        "  reins worktree verify feature-lane\n"
        "  reins worktree prune --all\n"
    )
)


def _slug(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._/-]+", "-", value).strip("-")
    return normalized or "worktree"


def _default_branch(name: str, task_id: str | None) -> str:
    if task_id:
        return f"feat/{_slug(task_id)}"
    return f"worktree/{_slug(name)}"


def _default_worktree_base(repo_root: Path) -> Path:
    template = load_worktree_config(repo_root)
    if template.source_path is not None:
        return template.worktree_dir
    return (repo_root / ".reins" / "worktrees").resolve()


def _current_branch(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    branch = result.stdout.strip()
    return branch or "HEAD"


def _git_worktrees(repo_root: Path) -> dict[Path, dict[str, str]]:
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return {}

    worktrees: dict[Path, dict[str, str]] = {}
    current: dict[str, str] | None = None
    current_path: Path | None = None
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            current_path = Path(line.split(" ", 1)[1]).resolve()
            current = {}
            worktrees[current_path] = current
            continue
        if current is None or not line.strip():
            continue
        key, _, value = line.partition(" ")
        current[key] = value.strip()
    return worktrees


def _worktree_dirty(path: Path) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        candidate = line[3:] if len(line) > 3 else line
        if candidate.startswith((".reins/", ".trellis/")):
            continue
        return True
    return False


def _task_exists(repo_root: Path, task_id: str | None) -> bool:
    if task_id is None:
        return True
    return (repo_root / ".reins" / "tasks" / task_id).exists()


def _resolve_state(manager, key: str) -> WorktreeState:
    for state in manager.list_worktrees():
        if key in {state.worktree_id, state.agent_id, state.worktree_path.name}:
            return state
    raise utils.CLIError(f"Worktree not found: {key}")


def _verification_rows(repo_root: Path, state: WorktreeState) -> tuple[list[dict[str, str]], list[str]]:
    git_worktrees = _git_worktrees(repo_root)
    git_metadata = git_worktrees.get(state.worktree_path.resolve())
    dirty = _worktree_dirty(state.worktree_path) if state.worktree_path.exists() else False
    task_ok = _task_exists(repo_root, state.task_id)

    checks = [
        ("directory exists", state.worktree_path.exists(), str(state.worktree_path)),
        ("git worktree registered", git_metadata is not None, state.worktree_path.name),
        (
            "branch matches",
            git_metadata is not None and git_metadata.get("branch", "").endswith(state.branch_name),
            state.branch_name,
        ),
        ("working tree clean", not dirty, "clean"),
        ("task association valid", task_ok, state.task_id or "(none)"),
    ]
    rows = [
        {"check": name, "status": "pass" if passed else "fail", "detail": detail}
        for name, passed, detail in checks
    ]
    failures = [name for name, passed, _detail in checks if not passed]
    return rows, failures


@app.command("create")
def create_command(
    name: str = typer.Argument(..., help="Worktree name or legacy agent identifier."),
    task_id: str | None = typer.Argument(None, help="Legacy positional task identifier."),
    branch: str | None = typer.Option(None, "--branch", help="Branch name for the worktree."),
    task: str | None = typer.Option(None, "--task", help="Task ID to associate with the worktree."),
    base: str | None = typer.Option(None, "--base", help="Base branch. Defaults to the current branch."),
) -> None:
    """
    Create a tracked worktree.

    Examples:
      reins worktree create feature-lane --task 04-19-cli
      reins worktree create agent-1 task-123 --branch feat/task-123
    """
    repo_root = utils.find_repo_root()
    run_id = utils.make_run_id("worktree")
    manager = utils.hydrate_worktree_manager(repo_root, run_id)
    resolved_task_id = task if task is not None else task_id
    resolved_branch = branch or _default_branch(name, resolved_task_id)
    resolved_base = base or _current_branch(repo_root)
    worktree_base_dir = _default_worktree_base(repo_root)
    try:
        state = asyncio.run(
            manager.create_worktree_for_agent(
                agent_id=name,
                task_id=resolved_task_id,
                branch_name=resolved_branch,
                base_branch=resolved_base,
                worktree_name=name,
                worktree_base_dir=worktree_base_dir,
            )
        )
    except Exception as exc:  # pragma: no cover - exercised via CLI tests
        asyncio.run(
            utils.emit_cli_error(
                repo_root,
                run_id,
                "worktree.create",
                exc,
                {"name": name, "task_id": resolved_task_id, "branch": resolved_branch, "base": resolved_base},
            )
        )
        utils.exit_with_error(str(exc))
        return

    utils.console.print(f"[green]Created worktree[/green] [bold]{state.worktree_id}[/bold].")
    utils.console.print(f"Path: {state.worktree_path}")


@app.command("list")
def list_command(
    active_only: bool = typer.Option(False, "--active-only", help="Only show tracked active worktrees."),
    verbose: bool = typer.Option(False, "--verbose", help="Show detailed verification metadata."),
) -> None:
    """
    List tracked and orphaned worktrees.

    Examples:
      reins worktree list
      reins worktree list --verbose
    """
    repo_root = utils.find_repo_root()
    run_id = utils.make_run_id("worktree")
    manager = utils.hydrate_worktree_manager(repo_root, run_id)
    registry = utils.get_agent_registry(repo_root, run_id)
    records = {record.agent_id: record for record in asyncio.run(registry.list_all())}
    git_worktrees = _git_worktrees(repo_root)
    rows: list[dict[str, str]] = []

    for state in manager.list_worktrees():
        record = records.get(state.agent_id)
        row = {
            "worktree_id": state.worktree_id,
            "name": state.worktree_path.name,
            "agent_id": state.agent_id,
            "task_id": state.task_id or "",
            "branch": state.branch_name,
            "status": record.status if record else "unknown",
            "path": utils.relpath(state.worktree_path, repo_root),
        }
        if verbose:
            row["dirty"] = "yes" if _worktree_dirty(state.worktree_path) else "no"
            row["task_ok"] = "yes" if _task_exists(repo_root, state.task_id) else "no"
            row["git_registered"] = "yes" if state.worktree_path.resolve() in git_worktrees else "no"
        rows.append(row)

    if not active_only:
        tracked_paths = {state.worktree_path.resolve() for state in manager.list_worktrees()}
        for path, metadata in git_worktrees.items():
            if path == repo_root.resolve() or path in tracked_paths:
                continue
            row = {
                "worktree_id": "(orphan)",
                "name": path.name,
                "agent_id": "",
                "task_id": "",
                "branch": metadata.get("branch", "").removeprefix("refs/heads/"),
                "status": "orphan",
                "path": utils.relpath(path, repo_root),
            }
            if verbose:
                row["dirty"] = "yes" if _worktree_dirty(path) else "no"
                row["task_ok"] = "-"
                row["git_registered"] = "yes"
            rows.append(row)

    if not rows:
        utils.console.print("[yellow]No worktrees found.[/yellow]")
        return

    headers = ["worktree_id", "name", "agent_id", "task_id", "branch", "status", "path"]
    if verbose:
        headers.extend(["dirty", "task_ok", "git_registered"])
    utils.console.print(utils.format_table(rows, headers))


@app.command("verify")
def verify_command(name: str = typer.Argument(..., help="Worktree ID, name, or agent identifier.")) -> None:
    """
    Verify worktree configuration and cleanliness.

    Examples:
      reins worktree verify feature-lane
      reins worktree verify agent-1
    """
    repo_root = utils.find_repo_root()
    run_id = utils.make_run_id("worktree")
    manager = utils.hydrate_worktree_manager(repo_root, run_id)
    try:
        state = _resolve_state(manager, name)
        rows, failures = _verification_rows(repo_root, state)
        verify_results = asyncio.run(manager.verify_worktree(state.worktree_id)) if not failures else []
    except Exception as exc:  # pragma: no cover - exercised via CLI tests
        asyncio.run(utils.emit_cli_error(repo_root, run_id, "worktree.verify", exc, {"name": name}))
        utils.exit_with_error(str(exc))
        return

    for result in verify_results:
        rows.append(
            {
                "check": result["command"],
                "status": "pass" if result["returncode"] == 0 else "fail",
                "detail": result["stderr"].strip() or "ok",
            }
        )

    utils.console.print(utils.format_table(rows, ["check", "status", "detail"]))
    if failures:
        raise typer.Exit(code=1)


@app.command("cleanup")
def cleanup_command(
    name: str = typer.Argument(..., help="Worktree ID, name, or agent identifier."),
    force: bool = typer.Option(False, "--force", help="Force cleanup and discard changes."),
) -> None:
    """
    Remove a tracked worktree and delete its branch.

    Examples:
      reins worktree cleanup feature-lane
      reins worktree cleanup agent-1 --force
    """
    repo_root = utils.find_repo_root()
    run_id = utils.make_run_id("worktree")
    manager = utils.hydrate_worktree_manager(repo_root, run_id)
    try:
        state = _resolve_state(manager, name)
        if _worktree_dirty(state.worktree_path) and not force:
            raise utils.CLIError(
                f"Worktree {state.worktree_path.name} has uncommitted changes. Use --force to remove it."
            )
        asyncio.run(
            manager.cleanup_agent_worktree(
                state.worktree_id,
                force=force,
                removed_by="cli",
                delete_branch=True,
            )
        )
    except Exception as exc:  # pragma: no cover - exercised via CLI tests
        asyncio.run(utils.emit_cli_error(repo_root, run_id, "worktree.cleanup", exc, {"name": name}))
        utils.exit_with_error(str(exc))
        return
    utils.console.print(f"[green]Removed worktree[/green] [bold]{name}[/bold].")


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


@app.command("prune")
def prune_command(
    all: bool = typer.Option(False, "--all", help="Force prune all stale worktrees."),
) -> None:
    """
    Remove stale worktrees with invalid git references.

    Examples:
      reins worktree prune
      reins worktree prune --all
    """
    cleanup_orphans_command(force=all)
