"""CLI command for updating platform configuration files."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from reins.platform.engine import DescriptorEngine
from reins.platform.registry import detect_platform, get_platform
from reins.platform.types import PlatformConfig

console = Console()


def _find_reins_root() -> Path | None:
    """Walk up from cwd looking for a .reins/ directory."""
    current = Path.cwd().resolve()
    for path in [current, *current.parents]:
        if (path / ".reins").is_dir():
            return path
    return None


def _resolve_platform_config(
    platform_name: str | None,
    repo_root: Path,
) -> PlatformConfig | None:
    """Resolve a platform config from name or auto-detection."""
    if platform_name:
        return get_platform(platform_name)
    return detect_platform(repo_root)


def update(
    platform: str | None = typer.Option(
        None, "--platform", help="Platform to update."
    ),
    force: bool = typer.Option(
        False, "--force", help="Update without prompting."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would change."
    ),
) -> None:
    """Detect stale platform configs and regenerate from templates."""
    repo_root = _find_reins_root()
    if repo_root is None:
        console.print(
            "[red]Error:[/red] No .reins/ directory found. "
            "Run 'reins init' first."
        )
        raise typer.Exit(1)

    config = _resolve_platform_config(platform, repo_root)
    if config is None:
        console.print(
            "[red]Error:[/red] No platform detected. "
            "Use --platform to specify one."
        )
        raise typer.Exit(1)

    engine = DescriptorEngine(repo_root)
    stale_files = engine.check_staleness(config)

    if not stale_files:
        console.print("All platform configs are up to date.")
        return

    table = Table(title="Stale Platform Configs")
    table.add_column("File", style="cyan")
    table.add_column("Status", style="yellow")
    for file_path, status in stale_files:
        table.add_row(file_path, status)
    console.print(table)

    if dry_run:
        return

    if not force:
        proceed = typer.confirm("Update these files?")
        if not proceed:
            console.print("Aborted.")
            return

    results = engine.generate(config)
    console.print(
        f"[green]Updated {len(results)} file(s)[/green] "
        f"for [bold]{config.name}[/bold]."
    )
