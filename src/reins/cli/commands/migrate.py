from __future__ import annotations

import asyncio
import json
from pathlib import Path

import jsonschema  # type: ignore[import-untyped]
import typer

from reins.cli import utils
from reins.migration.engine import MigrationEngine
from reins.migration.types import MigrationManifest
from reins.migration.version import SemanticVersion

app = typer.Typer(
    help=(
        "Migration commands.\n\n"
        "Examples:\n"
        "  reins migrate list\n"
        "  reins migrate run --from 0.0.0 --to 0.1.0 --dry-run\n"
    )
)


def _engine(repo_root: Path, run_id: str, manifest_dir: Path | None = None) -> MigrationEngine:
    return MigrationEngine(
        repo_root=repo_root,
        journal=utils.get_journal(repo_root),
        run_id=run_id,
        manifest_dir=manifest_dir,
    )


@app.command("run")
def run_command(
    from_version: str = typer.Option(..., "--from", help="Starting version."),
    to_version: str = typer.Option(..., "--to", help="Target version."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without changing files."),
) -> None:
    """
    Run declarative migrations between two versions.
    """
    repo_root = utils.find_repo_root()
    run_id = utils.make_run_id("migrate")
    try:
        engine = _engine(repo_root, run_id)
        results = asyncio.run(
            engine.migrate(
                from_version=from_version,
                to_version=to_version,
                dry_run=dry_run,
            )
        )
    except Exception as exc:  # pragma: no cover - exercised via CLI tests
        asyncio.run(
            utils.emit_cli_error(
                repo_root,
                run_id,
                "migrate.run",
                exc,
                {"from_version": from_version, "to_version": to_version},
            )
        )
        utils.exit_with_error(str(exc))
        return

    rows = [
        {
            "version": result.version,
            "type": result.migration_type,
            "status": result.status,
            "from": result.from_path or "",
            "to": result.to_path or "",
            "reason": result.reason or "",
        }
        for result in results
    ]
    utils.console.print(utils.format_table(rows, ["version", "type", "status", "from", "to", "reason"]))


@app.command("list")
def list_command() -> None:
    """
    List migration manifests available in the repository.
    """
    repo_root = utils.find_repo_root()
    engine = _engine(repo_root, utils.make_run_id("migrate"))
    manifests = engine.load_manifests()
    rows = [{"version": manifest.version, "migrations": str(len(manifest.migrations))} for manifest in manifests]
    if not rows:
        utils.console.print("[yellow]No migration manifests found.[/yellow]")
        return
    utils.console.print(utils.format_table(rows, ["version", "migrations"]))


@app.command("validate")
def validate_command(manifest_file: Path = typer.Argument(..., exists=True, resolve_path=True)) -> None:
    """
    Validate a migration manifest against the schema.
    """
    repo_root = utils.find_repo_root()
    schema_path = repo_root / "migrations" / "manifests" / "schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    jsonschema.validate(data, schema)
    MigrationManifest.from_dict(data)
    utils.console.print(f"[green]Validated migration manifest[/green] {manifest_file}.")


@app.command("create")
def create_command(version: str = typer.Argument(..., help="Version number, e.g. 0.2.0")) -> None:
    """
    Scaffold a new migration manifest file.
    """
    repo_root = utils.find_repo_root()
    run_id = utils.make_run_id("migrate")
    SemanticVersion.parse(version)
    manifest_dir = repo_root / "migrations" / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{version}.json"
    if manifest_path.exists():
        utils.exit_with_error(f"Manifest already exists: {manifest_path}")
    manifest_path.write_text(
        json.dumps({"version": version, "migrations": []}, indent=2) + "\n",
        encoding="utf-8",
    )
    asyncio.run(
        utils.emit_cli_event(
            repo_root,
            run_id,
            "migration.manifest_created",
            {"version": version, "path": utils.relpath(manifest_path, repo_root)},
        )
    )
    utils.console.print(f"[green]Created migration manifest[/green] {manifest_path}.")
