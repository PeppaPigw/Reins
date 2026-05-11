"""CLI command for uninstalling Reins-generated files."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from reins.packaging.cleanup import CleanupEngine
from reins.packaging.manifest import InstallManifest

console = Console()


def _find_repo_root() -> Path | None:
    """Walk up from cwd looking for a .reins/ directory."""
    current = Path.cwd().resolve()
    for path in [current, *current.parents]:
        if (path / ".reins").is_dir():
            return path
    return None


def uninstall_command(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be removed without removing."
    ),
    force: bool = typer.Option(
        False, "--force", help="Remove even user-modified files."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip confirmation prompt."
    ),
) -> None:
    """Remove all Reins-generated files tracked by the install manifest."""
    repo_root = _find_repo_root()
    if repo_root is None:
        console.print(
            "[red]Error:[/red] No .reins/ directory found. Nothing to uninstall."
        )
        raise typer.Exit(1)

    manifest = InstallManifest(repo_root)
    manifest.load()

    if not manifest.get_entries():
        console.print("Nothing to uninstall — no tracked files in manifest.")
        return

    engine = CleanupEngine(repo_root, manifest)

    if dry_run:
        result = engine.plan_cleanup(force=force)
        _display_plan(result)
        return

    # Show what will happen
    result = engine.plan_cleanup(force=force)
    _display_plan(result)

    if not yes:
        proceed = typer.confirm("\nProceed with uninstall?")
        if not proceed:
            console.print("Aborted.")
            return

    result = engine.execute_cleanup(force=force)
    _display_summary(result)


def _display_plan(result) -> None:
    """Display what would be removed."""
    if result.removed_files or result.removed_dirs:
        table = Table(title="Files to Remove")
        table.add_column("Path", style="cyan")
        table.add_column("Type", style="green")
        for f in result.removed_files:
            table.add_row(f, "file")
        for d in result.removed_dirs:
            table.add_row(d, "directory")
        console.print(table)

    if result.skipped_modified:
        console.print(
            f"\n[yellow]Skipped {len(result.skipped_modified)} modified file(s)[/yellow]"
            " (use --force to remove):"
        )
        for f in result.skipped_modified:
            console.print(f"  {f}")

    if result.skipped_missing:
        console.print(
            f"\n[dim]Skipped {len(result.skipped_missing)} missing file(s)[/dim]"
        )


def _display_summary(result) -> None:
    """Display cleanup summary after execution."""
    total_removed = len(result.removed_files) + len(result.removed_dirs)
    console.print(
        f"\n[green]Removed {total_removed} item(s)[/green] "
        f"({len(result.removed_files)} files, {len(result.removed_dirs)} directories)."
    )
    if result.skipped_modified:
        console.print(
            f"[yellow]Skipped {len(result.skipped_modified)} modified file(s).[/yellow]"
        )
    if result.errors:
        console.print(f"[red]Errors: {len(result.errors)}[/red]")
        for err in result.errors:
            console.print(f"  {err}")
