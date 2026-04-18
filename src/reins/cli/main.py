from __future__ import annotations

import typer

from reins.cli.commands import developer, init, journal, migrate, spec, status, task, worktree

app = typer.Typer(
    add_completion=False,
    help=(
        "Reins command line interface.\n\n"
        "Examples:\n"
        "  reins init --platform codex --project-type backend\n"
        "  reins task create \"Implement JWT auth\" --type backend --priority P0\n"
        "  reins spec init --package cli --layers commands,workflow\n"
        "  reins worktree create agent-1 task-123 --branch feat/task-123\n"
        "  reins journal stats\n"
    ),
)

app.add_typer(task.app, name="task")
app.add_typer(spec.app, name="spec")
app.add_typer(developer.app, name="developer")
app.add_typer(migrate.app, name="migrate")
app.add_typer(worktree.app, name="worktree")
app.add_typer(journal.app, name="journal")
app.command(name="init")(init.init_command)
app.command(name="status")(status.status_command)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
