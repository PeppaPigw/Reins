"""Doctor command: diagnose common setup issues and suggest fixes."""

from __future__ import annotations

from pathlib import Path

import typer

from reins.dx.diagnostics import CheckStatus, DiagnosticSuite


def _find_repo_root_optional() -> Path | None:
    """Find .reins directory walking up from cwd, returning None if not found."""
    current = Path.cwd().resolve()
    for path in [current, *current.parents]:
        if (path / ".reins").is_dir():
            return path
    return None


def doctor_command(
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show all checks including passed"
    ),
) -> None:
    """
    Diagnose common setup issues and suggest fixes.

    Checks Python version, git availability, initialization state,
    dependencies, configuration, journal access, and platform configs.
    """
    from rich.console import Console

    console = Console()

    repo_root = _find_repo_root_optional()
    suite = DiagnosticSuite(repo_root)
    results = suite.run_all()

    console.print("\n[bold]Reins Doctor[/bold]\n")

    if verbose:
        display_results = results
    else:
        display_results = [
            r for r in results if r.status != CheckStatus.passed
        ]

    if not display_results and not verbose:
        console.print("  [green]All checks passed.[/green]\n")
    else:
        console.print(suite.format_results(display_results))
        console.print()

    passed = sum(1 for r in results if r.status == CheckStatus.passed)
    warnings = sum(1 for r in results if r.status == CheckStatus.warning)
    failures = sum(1 for r in results if r.status == CheckStatus.failed)

    console.print(
        f"  Summary: {passed} passed, {warnings} warnings, {failures} failures"
    )

    if failures > 0:
        raise typer.Exit(code=1)
