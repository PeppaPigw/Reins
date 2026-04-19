"""Shell completion helpers for the Reins CLI."""

from __future__ import annotations

from click.shell_completion import get_completion_class
from typer.main import get_command


def render_completion_script(typer_app, shell: str, *, prog_name: str = "reins") -> str:
    """Render a shell completion script for a Typer application."""

    completion_class = get_completion_class(shell)
    if completion_class is None:  # pragma: no cover - guarded by CLI choice
        raise ValueError(f"Unsupported shell: {shell}")
    complete_var = f"_{prog_name.upper().replace('-', '_')}_COMPLETE"
    command = get_command(typer_app)
    return completion_class(command, {}, prog_name, complete_var).source()
