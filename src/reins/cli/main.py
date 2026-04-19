from __future__ import annotations

from importlib import metadata

import typer

from reins.cli import completion
from reins.cli.commands import (
    config,
    developer,
    init,
    journal,
    migrate,
    pipeline,
    spec,
    status,
    task,
    workspace,
    worktree,
)


def _version() -> str:
    try:
        return metadata.version("reins")
    except metadata.PackageNotFoundError:
        return "0.1.0"


def _version_callback(value: bool) -> None:
    if not value:
        return
    typer.echo(_version())
    raise typer.Exit()


app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Reins - Multi-Agent Orchestration System\n\n"
        "Reins provides structured context injection, task-driven workflows,\n"
        "and parallel agent execution for AI coding assistants.\n\n"
        "Key Features:\n"
        "  - Event-sourced orchestration and audit trails\n"
        "  - Task, spec, and worktree lifecycle management\n"
        "  - MCP-friendly integrations and developer workspace support\n"
        "  - Timeline and journal inspection for automation debugging\n\n"
        "Common Commands:\n"
        "  reins init\n"
        "  reins task create \"Implement JWT auth\"\n"
        "  reins spec validate\n"
        "  reins worktree create feature-lane --task 04-19-cli\n"
        "  reins completion zsh\n\n"
        "Examples:\n"
        "  reins init --platform codex --project-type backend\n"
        "  reins task create \"Implement JWT auth\" --type backend --priority P0\n"
        "  reins spec init --package cli\n"
        "  reins worktree create feature-lane --task 04-19-cli\n"
        "  reins journal stats\n"
    ),
)

app.add_typer(task.app, name="task")
app.add_typer(config.app, name="config")
app.add_typer(spec.app, name="spec")
app.add_typer(developer.app, name="developer")
app.add_typer(workspace.app, name="workspace")
app.add_typer(migrate.app, name="migrate")
app.add_typer(worktree.app, name="worktree")
app.add_typer(journal.app, name="journal")
app.add_typer(pipeline.app, name="pipeline")
app.command(name="init")(init.init_command)
app.command(name="status")(status.status_command)


@app.callback()
def main_callback(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed Reins version and exit.",
    ),
) -> None:
    """Root CLI callback for shared options."""
    del version


@app.command("completion")
def completion_command(
    shell: str = typer.Argument(..., help="Target shell: bash, zsh, or fish."),
) -> None:
    """
    Generate a shell completion script.

    Examples:
      reins completion bash > ~/.reins-completion.bash
      reins completion zsh > ~/.reins-completion.zsh
      reins completion fish > ~/.config/fish/completions/reins.fish
    """
    typer.echo(completion.render_completion_script(app, shell))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
