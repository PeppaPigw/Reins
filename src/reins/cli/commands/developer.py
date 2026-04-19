from __future__ import annotations

import asyncio

import typer

from reins.cli import utils
from reins.workspace.manager import WorkspaceManager

app = typer.Typer(
    help=(
        "Developer identity and workspace commands.\n\n"
        "Examples:\n"
        "  reins developer init peppa\n"
        "  reins developer workspace-info\n"
    )
)


@app.command("init")
def init_command(name: str = typer.Argument(..., help="Developer name.")) -> None:
    """
    Initialize `.reins/.developer` and the developer workspace.
    """
    repo_root = utils.find_repo_root()
    run_id = utils.make_run_id("developer")
    identity = utils.read_developer_identity(repo_root)
    if identity and identity.get("name") != name:
        utils.exit_with_error(
            f"Developer already initialized as {identity['name']}. Remove .reins/.developer to switch."
        )

    utils.ensure_reins_layout(repo_root)
    dev_path = utils.write_developer_identity(repo_root, name)
    manager = WorkspaceManager(
        repo_root / ".reins",
        journal=utils.get_journal(repo_root),
        run_id=run_id,
    )
    ws_dir = manager.initialize_workspace(name)

    asyncio.run(
        utils.emit_cli_event(
            repo_root,
            run_id,
            "developer.initialized",
            {"name": name, "workspace_dir": utils.relpath(ws_dir, repo_root)},
        )
    )
    utils.console.print(f"[green]Initialized developer[/green] [bold]{name}[/bold].")
    utils.console.print(f"Identity: {utils.relpath(dev_path, repo_root)}")
    utils.console.print(f"Workspace: {utils.relpath(ws_dir, repo_root)}")


@app.command("show")
def show_command() -> None:
    """
    Show the current developer identity.
    """
    repo_root = utils.find_repo_root()
    identity = utils.read_developer_identity(repo_root)
    if identity is None:
        utils.exit_with_error("Developer is not initialized.")

    utils.console.print(f"Developer: [bold]{identity['name']}[/bold]")
    if "initialized_at" in identity:
        utils.console.print(f"Initialized: {identity['initialized_at']}")
    utils.console.print(
        f"Workspace: {utils.relpath(utils.workspace_dir(repo_root, identity['name']), repo_root)}"
    )


@app.command("workspace-info")
def workspace_info_command() -> None:
    """
    Show workspace journal summary for the current developer.
    """
    repo_root = utils.find_repo_root()
    info = utils.collect_workspace_info(repo_root)
    if info.developer is None or info.workspace_dir is None:
        utils.exit_with_error("Developer is not initialized.")

    rows = [
        {"field": "developer", "value": info.developer},
        {"field": "workspace", "value": utils.relpath(info.workspace_dir, repo_root)},
        {"field": "journal_files", "value": str(len(info.journal_files))},
        {"field": "active_journal", "value": info.active_journal.name if info.active_journal else "-"},
        {"field": "total_lines", "value": str(info.total_lines)},
    ]
    utils.console.print(utils.format_table(rows, ["field", "value"]))
