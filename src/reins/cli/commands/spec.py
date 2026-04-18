from __future__ import annotations

import asyncio
from pathlib import Path

import typer
import yaml

from reins.cli import utils

app = typer.Typer(
    help=(
        "Spec management commands.\n\n"
        "Examples:\n"
        "  reins spec init --package cli --layers commands,workflow\n"
        "  reins spec validate .reins/spec/backend/error-handling.yaml\n"
    )
)

VALID_SPEC_TYPES = {"standing_law", "task_contract", "spec_shard"}


def _spec_root(repo_root: Path) -> Path:
    root = repo_root / ".reins" / "spec"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _package_index_content(package: str, layers: list[str]) -> str:
    lines = [
        f"# {package.title()} Specifications",
        "",
        "## Pre-Development Checklist",
        "",
    ]
    if layers:
        for layer in layers:
            lines.append(f"- [ ] {layer}/index.md - Fill in the {layer} guidance.")
    else:
        lines.append("- [ ] Add package guidance and relevant layer indexes.")
    lines.extend(["", "## Notes", "", "- Add YAML manifests for machine-readable specs."])
    return "\n".join(lines) + "\n"


def _layer_index_content(package: str, layer: str) -> str:
    return (
        f"# {package.title()} / {layer.title()}\n\n"
        "## Pre-Development Checklist\n\n"
        "- [ ] Add conventions, constraints, and review criteria for this layer.\n"
    )


def _validate_spec_data(data: dict, path: Path) -> list[str]:
    errors: list[str] = []
    if "content" not in data or not isinstance(data["content"], str):
        errors.append(f"{path}: missing string field 'content'")
    spec_type = data.get("spec_type", "standing_law")
    if spec_type not in VALID_SPEC_TYPES:
        errors.append(f"{path}: invalid spec_type '{spec_type}'")
    visibility_tier = data.get("visibility_tier", 1)
    if not isinstance(visibility_tier, int) or not 0 <= visibility_tier <= 3:
        errors.append(f"{path}: visibility_tier must be an integer between 0 and 3")
    precedence = data.get("precedence", 100)
    if not isinstance(precedence, int):
        errors.append(f"{path}: precedence must be an integer")
    required_capabilities = data.get("required_capabilities", [])
    if not isinstance(required_capabilities, list):
        errors.append(f"{path}: required_capabilities must be a list")
    applicability = data.get("applicability", {})
    if not isinstance(applicability, dict):
        errors.append(f"{path}: applicability must be a mapping")
    return errors


@app.command("init")
def init_command(
    package: str = typer.Option("general", "--package", help="Package name under .reins/spec/."),
    layers: str | None = typer.Option(None, "--layers", help="Comma-separated layer names."),
) -> None:
    """
    Initialize a package spec directory with starter index files.
    """
    repo_root = utils.find_repo_root()
    run_id = utils.make_run_id("spec")
    package_layers = [item.strip() for item in (layers or "").split(",") if item.strip()]
    package_dir = _spec_root(repo_root) / package
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "index.md").write_text(
        _package_index_content(package, package_layers),
        encoding="utf-8",
    )
    for layer in package_layers:
        layer_dir = package_dir / layer
        layer_dir.mkdir(parents=True, exist_ok=True)
        (layer_dir / "index.md").write_text(_layer_index_content(package, layer), encoding="utf-8")

    asyncio.run(
        utils.emit_cli_event(
            repo_root,
            run_id,
            "spec.initialized",
            {"package": package, "layers": package_layers},
        )
    )
    utils.console.print(f"[green]Initialized spec package[/green] [bold]{package}[/bold].")


@app.command("list")
def list_command(
    package: str | None = typer.Option(None, "--package", help="Filter to a single package."),
) -> None:
    """
    List spec packages, layers, and YAML manifests on disk.
    """
    repo_root = utils.find_repo_root()
    root = _spec_root(repo_root)
    target = root / package if package else root
    if not target.exists():
        utils.exit_with_error(f"Spec path not found: {target}")

    rows: list[dict[str, str]] = []
    for path in sorted(target.rglob("*")):
        if path.name.startswith("."):
            continue
        if path.is_dir():
            kind = "dir"
        elif path.suffix in {".yaml", ".yml"}:
            kind = "yaml"
        elif path.name == "index.md":
            kind = "index"
        else:
            continue
        rows.append({"kind": kind, "path": utils.relpath(path, repo_root)})

    if not rows:
        utils.console.print("[yellow]No specs found.[/yellow]")
        return
    utils.console.print(utils.format_table(rows, ["kind", "path"]))


@app.command("validate")
def validate_command(spec_path: Path = typer.Argument(..., exists=True, resolve_path=True)) -> None:
    """
    Validate a spec YAML file or all YAML files under a directory.
    """
    paths: list[Path]
    if spec_path.is_dir():
        paths = sorted([*spec_path.rglob("*.yaml"), *spec_path.rglob("*.yml")])
    else:
        paths = [spec_path]

    if not paths:
        utils.console.print("[yellow]No YAML spec files found to validate.[/yellow]")
        return

    errors: list[str] = []
    for path in paths:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            errors.append(f"{path}: YAML parse error: {exc}")
            continue
        if not isinstance(data, dict):
            errors.append(f"{path}: YAML root must be a mapping")
            continue
        errors.extend(_validate_spec_data(data, path))

    if errors:
        for error in errors:
            utils.console.print(f"[red]{error}[/red]")
        raise typer.Exit(code=1)

    utils.console.print(f"[green]Validated[/green] {len(paths)} spec file(s).")


@app.command("add-layer")
def add_layer_command(
    package: str = typer.Argument(..., help="Package name."),
    layer_name: str = typer.Argument(..., help="Layer name."),
) -> None:
    """
    Add a layer directory and starter index under a spec package.
    """
    repo_root = utils.find_repo_root()
    run_id = utils.make_run_id("spec")
    package_dir = _spec_root(repo_root) / package
    package_dir.mkdir(parents=True, exist_ok=True)
    layer_dir = package_dir / layer_name
    layer_dir.mkdir(parents=True, exist_ok=True)
    index_path = layer_dir / "index.md"
    if not index_path.exists():
        index_path.write_text(_layer_index_content(package, layer_name), encoding="utf-8")

    package_index = package_dir / "index.md"
    if package_index.exists():
        content = package_index.read_text(encoding="utf-8")
    else:
        content = _package_index_content(package, [])
    checklist_entry = f"- [ ] {layer_name}/index.md - Fill in the {layer_name} guidance."
    if checklist_entry not in content:
        if "## Notes" in content:
            content = content.replace("## Notes", f"{checklist_entry}\n\n## Notes", 1)
        else:
            content = content.rstrip() + f"\n{checklist_entry}\n"
        package_index.write_text(content, encoding="utf-8")

    asyncio.run(
        utils.emit_cli_event(
            repo_root,
            run_id,
            "spec.layer_added",
            {"package": package, "layer": layer_name},
        )
    )
    utils.console.print(
        f"[green]Added spec layer[/green] [bold]{package}/{layer_name}[/bold]."
    )
