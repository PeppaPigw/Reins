from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import typer

from reins.cli import utils

app = typer.Typer(
    help=(
        "Developer identity and workspace commands.\n\n"
        "Examples:\n"
        "  reins developer init peppa\n"
        "  reins developer workspace-info\n"
    )
)


def _workspace_index_content(name: str) -> str:
    return f"""# Workspace Index - {name}

## Current Status

- Active File: `journal-1.md`
- Total Sessions: 0
- Last Active: -

## Active Documents

| File | Lines | Status |
|------|-------|--------|
| `journal-1.md` | ~0 | Active |
"""


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
    ws_dir = utils.workspace_dir(repo_root, name)
    ws_dir.mkdir(parents=True, exist_ok=True)
    journal_file = ws_dir / "journal-1.md"
    if not journal_file.exists():
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        journal_file.write_text(
            f"# Journal - {name} (Part 1)\n\n> Started: {today}\n\n---\n",
            encoding="utf-8",
        )
    index_file = ws_dir / "index.md"
    if not index_file.exists():
        index_file.write_text(_workspace_index_content(name), encoding="utf-8")

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
