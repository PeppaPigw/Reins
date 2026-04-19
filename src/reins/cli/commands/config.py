from __future__ import annotations

from typing import Any

import typer
import yaml

from reins.cli import utils
from reins.config import ConfigLoader, validate_config
from reins.config.validator import validate_worktree_config
from reins.isolation.worktree_config import (
    WorktreeConfigError,
    load_worktree_config,
)

app = typer.Typer(
    help=(
        "Configuration management commands.\n\n"
        "Examples:\n"
        "  reins config init\n"
        "  reins config get max_journal_lines\n"
        "  reins config set default_package cli\n"
        "  reins config validate\n"
    )
)

DEFAULT_WORKTREE_TEMPLATE = """# Worktree Configuration

# Worktree storage directory (relative to project root)
worktree_dir: ../reins-worktrees

# Files to copy to each worktree
copy:
  - .reins/.developer
  # - .env
  # - .env.local

# Commands to run after creating worktree
post_create: []
  # - npm install
  # - pip install -r requirements.txt

# Commands to verify code quality
verify: []
  # - pytest tests/
  # - mypy src/
  # - ruff check src/
"""


@app.command("get")
def get_command(key: str = typer.Argument(..., help="Dot-delimited config key.")) -> None:
    """Get a configuration value."""
    repo_root = utils.find_repo_root()
    config = ConfigLoader(repo_root / ".reins").load().to_dict()
    value = _get_nested_value(config, key)
    if isinstance(value, (dict, list)):
        typer.echo(yaml.safe_dump(value, sort_keys=False).strip())
        return
    typer.echo("null" if value is None else str(value))


@app.command("set")
def set_command(
    key: str = typer.Argument(..., help="Dot-delimited config key."),
    value: str = typer.Argument(..., help="Value to set. YAML scalars are supported."),
) -> None:
    """Set a configuration value and save `.reins/config.yaml`."""
    repo_root = utils.find_repo_root()
    loader = ConfigLoader(repo_root / ".reins")
    payload = loader.load().to_dict()
    _set_nested_value(payload, key, yaml.safe_load(value))
    parsed = loader.parse_data(payload)
    errors = validate_config(parsed, repo_root=repo_root)
    if errors:
        utils.exit_with_error("\n".join(errors))
    loader.save(parsed)
    typer.echo(f"Set {key}")


@app.command("show")
def show_command() -> None:
    """Show the full project configuration."""
    repo_root = utils.find_repo_root()
    payload = ConfigLoader(repo_root / ".reins").load().to_dict()
    typer.echo(yaml.safe_dump(payload, sort_keys=False).strip())


@app.command("validate")
def validate_command() -> None:
    """Validate project and worktree configuration files."""
    repo_root = utils.find_repo_root()
    errors: list[str] = []

    try:
        config = ConfigLoader(repo_root / ".reins").load()
        errors.extend(validate_config(config, repo_root=repo_root))
    except ValueError as exc:
        errors.append(str(exc))

    try:
        worktree_config = load_worktree_config(repo_root)
        errors.extend(validate_worktree_config(worktree_config, repo_root=repo_root))
    except WorktreeConfigError as exc:
        errors.append(str(exc))

    if errors:
        utils.exit_with_error("\n".join(errors))
    typer.echo("Configuration is valid.")


@app.command("init")
def init_command() -> None:
    """Initialize default configuration files."""
    repo_root = utils.find_repo_root_for_init()
    utils.ensure_reins_layout(repo_root)
    loader = ConfigLoader(repo_root / ".reins")
    config_path = loader.write_default_template()
    worktree_path = repo_root / ".reins" / "worktree.yaml"
    if not worktree_path.exists():
        worktree_path.write_text(DEFAULT_WORKTREE_TEMPLATE, encoding="utf-8")
    typer.echo(f"Initialized {utils.relpath(config_path, repo_root)}")
    typer.echo(f"Initialized {utils.relpath(worktree_path, repo_root)}")


def _get_nested_value(payload: dict[str, Any], key: str) -> Any:
    current: Any = payload
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            raise utils.CLIError(f"Unknown config key: {key}")
        current = current[part]
    return current


def _set_nested_value(payload: dict[str, Any], key: str, value: Any) -> None:
    parts = key.split(".")
    current: dict[str, Any] = payload
    for part in parts[:-1]:
        next_value = current.get(part)
        if next_value is None:
            next_value = {}
            current[part] = next_value
        if not isinstance(next_value, dict):
            raise utils.CLIError(f"Cannot set nested key below scalar field: {part}")
        current = next_value
    current[parts[-1]] = value
