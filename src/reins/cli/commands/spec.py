from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer
import yaml

from reins.cli import utils
from reins.context.checklist import ChecklistParser, create_checklist_template
from reins.context.compiler import ContextCompiler
from reins.context.types import SpecLayer

app = typer.Typer(
    help=(
        "Spec management commands.\n\n"
        "Examples:\n"
        "  reins spec init --package cli --layers commands,workflow\n"
        "  reins spec checklist --validate\n"
        "  reins spec validate .reins/spec/backend/error-handling.yaml\n"
    )
)

VALID_SPEC_TYPES = {"standing_law", "task_contract", "spec_shard"}
DEFAULT_LAYER_FILES: dict[str, list[str]] = {
    SpecLayer.BACKEND.value: ["error-handling.yaml"],
    SpecLayer.FRONTEND.value: [],
    SpecLayer.UNIT_TEST.value: [],
    SpecLayer.INTEGRATION_TEST.value: [],
    SpecLayer.GUIDES.value: ["code-review.yaml"],
}


def _spec_root(repo_root: Path) -> Path:
    root = repo_root / ".reins" / "spec"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _template_root() -> Path:
    return Path(__file__).resolve().parents[2] / "platform" / "templates" / "common" / "spec"


def _layer_dir(spec_root: Path, layer_name: str, package: str | None = None) -> Path:
    if package:
        return spec_root / package / layer_name
    return spec_root / layer_name


def _layer_files(layer_dir: Path, layer_name: str) -> list[str]:
    files = sorted(
        path.name
        for path in layer_dir.iterdir()
        if path.is_file() and path.name != "index.md" and not path.name.startswith(".")
    ) if layer_dir.exists() else []
    return files or DEFAULT_LAYER_FILES.get(layer_name, [])


def _render_layer_index(layer_name: str, *, package: str | None = None, layer_dir: Path | None = None) -> str:
    if layer_dir is None:
        raise ValueError("layer_dir is required")

    template_path = _template_root() / layer_name / "index.md"
    if template_path.exists():
        template = template_path.read_text(encoding="utf-8")
        title = (
            f"{package.title()} / {layer_name.replace('-', ' ').title()}"
            if package
            else f"{layer_name.replace('-', ' ').title()} Specifications"
        )
        return template.replace("{{TITLE}}", title)

    spec_files = _layer_files(layer_dir, layer_name)
    return create_checklist_template(layer_name, spec_files)


def _package_index_content(package: str, layers: list[str]) -> str:
    lines = [
        f"# {package.title()} Specifications",
        "",
        "## Pre-Development Checklist",
        "",
        "Before starting package-specific development, ensure you have reviewed:",
        "",
    ]
    if layers:
        for layer in layers:
            lines.append(
                f"- [ ] [{layer.replace('-', ' ').title()} Layer]({layer}/index.md) - Review the {layer} conventions for this package"
            )
    else:
        lines.append("- [ ] Add package layer guidance before relying on package-local specs")
    lines.extend(["", "## Package Layers", ""])
    if layers:
        for layer in layers:
            lines.append(
                f"- [{layer.replace('-', ' ').title()} Layer]({layer}/index.md) - Package-specific {layer} guidance"
            )
    else:
        lines.append("- Add layers under this package as the project grows")
    return "\n".join(lines) + "\n"


def _write_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def ensure_standard_spec_layout(
    repo_root: Path,
    *,
    project_type: str,
    package: str | None = None,
) -> list[Path]:
    """Ensure the standard spec layer layout exists."""
    spec_root = _spec_root(repo_root)
    created_paths: list[Path] = []
    global_layers = [layer.value for layer in SpecLayer.standard_layers()]

    for layer_name in global_layers:
        layer_dir = _layer_dir(spec_root, layer_name)
        layer_dir.mkdir(parents=True, exist_ok=True)
        index_path = layer_dir / "index.md"
        content = _render_layer_index(layer_name, layer_dir=layer_dir)
        if _write_if_missing(index_path, content):
            created_paths.append(index_path)

    if package:
        package_dir = spec_root / package
        package_dir.mkdir(parents=True, exist_ok=True)
        package_layers = [
            layer.value
            for layer in SpecLayer.default_layers_for_project_type(project_type)
            if layer != SpecLayer.GUIDES
        ]
        if _write_if_missing(package_dir / "index.md", _package_index_content(package, package_layers)):
            created_paths.append(package_dir / "index.md")
        for layer_name in package_layers:
            layer_dir = _layer_dir(spec_root, layer_name, package)
            layer_dir.mkdir(parents=True, exist_ok=True)
            index_path = layer_dir / "index.md"
            content = _render_layer_index(layer_name, package=package, layer_dir=layer_dir)
            if _write_if_missing(index_path, content):
                created_paths.append(index_path)

    return created_paths


def migrate_spec_layout(
    repo_root: Path,
    *,
    project_type: str,
    package: str | None = None,
) -> list[Path]:
    """Create missing standard spec artifacts without overwriting user files."""
    return ensure_standard_spec_layout(repo_root, project_type=project_type, package=package)


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


def _load_task_metadata(repo_root: Path, task_id: str | None) -> tuple[str, dict[str, object]]:
    resolved_task_id = task_id or utils.get_current_task_id(repo_root)
    if not resolved_task_id:
        raise utils.CLIError("No current task found. Use --task or start a task first.")
    task_json = utils.task_dir(repo_root, resolved_task_id) / "task.json"
    if not task_json.exists():
        raise utils.CLIError(f"Task metadata not found: {task_json}")
    return resolved_task_id, utils.read_json_file(task_json)


def _checklist_sources(repo_root: Path, task_metadata: dict[str, object]) -> list[Path]:
    compiler = ContextCompiler()
    metadata = task_metadata.get("metadata", {})
    package = metadata.get("package") if isinstance(metadata, dict) else None
    task_type = task_metadata.get("task_type", "backend")
    if not isinstance(task_type, str):
        task_type = "backend"
    if not isinstance(package, str):
        package = None
    sources = compiler.resolve_spec_sources(
        repo_root / ".reins" / "spec",
        task_type=task_type,
        package=package,
    )
    paths: list[Path] = []
    for source in sources:
        if not source.path:
            continue
        source_path = Path(source.path)
        index_path = source_path / "index.md" if source_path.is_dir() else source_path
        if index_path.exists():
            paths.append(index_path)
    return paths


def _normalize_tracked_path(repo_root: Path, path: Path) -> str:
    spec_root = (repo_root / ".reins" / "spec").resolve()
    try:
        return path.resolve().relative_to(spec_root).as_posix()
    except ValueError as exc:
        raise utils.CLIError(f"Path is outside .reins/spec: {path}") from exc


def _resolve_mark_read_path(
    repo_root: Path,
    task_metadata: dict[str, object],
    raw_path: str,
) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute() and candidate.exists():
        return candidate

    repo_candidate = (repo_root / candidate).resolve()
    if repo_candidate.exists():
        return repo_candidate

    spec_candidate = (repo_root / ".reins" / "spec" / candidate).resolve()
    if spec_candidate.exists():
        return spec_candidate

    matches: list[Path] = []
    for index_path in _checklist_sources(repo_root, task_metadata):
        checklist = ChecklistParser.parse(index_path)
        if checklist is None:
            continue
        target = (checklist.spec_dir / raw_path).resolve()
        if target.exists():
            matches.append(target)

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise utils.CLIError(f"Path is ambiguous across checklist sources: {raw_path}")
    raise utils.CLIError(f"Spec file not found: {raw_path}")


def _render_checklist_summary(
    repo_root: Path,
    task_metadata: dict[str, object],
) -> tuple[list[str], bool]:
    metadata = task_metadata.get("metadata", {})
    tracked = metadata.get("checklist", {}) if isinstance(metadata, dict) else {}
    read_specs = tracked.get("read_specs", []) if isinstance(tracked, dict) else []
    normalized_reads = {item for item in read_specs if isinstance(item, str)}

    lines: list[str] = []
    all_complete = True
    for index_path in _checklist_sources(repo_root, task_metadata):
        checklist = ChecklistParser.parse(index_path)
        if checklist is None:
            continue
        relative_reads = {
            (repo_root / ".reins" / "spec" / read_spec).resolve().relative_to(checklist.spec_dir.resolve()).as_posix()
            for read_spec in normalized_reads
            if (repo_root / ".reins" / "spec" / read_spec).resolve().is_relative_to(checklist.spec_dir.resolve())
        }
        validation = checklist.validate_completion(relative_reads)
        all_complete = all_complete and validation.is_complete
        lines.append(f"{utils.relpath(index_path, repo_root)}: {'complete' if validation.is_complete else 'incomplete'}")
        for item in checklist.iter_items():
            complete = checklist._is_item_completed(item, relative_reads)
            prefix = "x" if complete else " "
            label = item.target or item.text
            description = f" - {item.description}" if item.description else ""
            lines.append(f"  - [{prefix}] {label}{description}")
        if validation.missing_files:
            lines.append(f"  Missing files: {', '.join(validation.missing_files)}")
    return lines, all_complete


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
        (layer_dir / "index.md").write_text(
            _render_layer_index(layer, package=package, layer_dir=layer_dir),
            encoding="utf-8",
        )

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
        index_path.write_text(
            _render_layer_index(layer_name, package=package, layer_dir=layer_dir),
            encoding="utf-8",
        )

    package_index = package_dir / "index.md"
    if package_index.exists():
        content = package_index.read_text(encoding="utf-8")
    else:
        content = _package_index_content(package, [])
    checklist_entry = (
        f"- [ ] [{layer_name.replace('-', ' ').title()} Layer]({layer_name}/index.md) - "
        f"Review the {layer_name} conventions for this package"
    )
    if checklist_entry not in content:
        if "## Package Layers" in content:
            content = content.replace("## Package Layers", f"{checklist_entry}\n\n## Package Layers", 1)
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


@app.command("checklist")
def checklist_command(
    task_id: str | None = typer.Option(None, "--task", help="Task ID. Defaults to current task."),
    validate: bool = typer.Option(False, "--validate", help="Exit non-zero when checklist is incomplete."),
    mark_read: str | None = typer.Option(None, "--mark-read", help="Mark a spec file as read."),
) -> None:
    """
    Show or validate the checklist for the current task.
    """
    repo_root = utils.find_repo_root()
    run_id = utils.make_run_id("spec")
    resolved_task_id, task_metadata = _load_task_metadata(repo_root, task_id)

    metadata = task_metadata.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}

    if mark_read:
        target_path = _resolve_mark_read_path(repo_root, task_metadata, mark_read)
        normalized = _normalize_tracked_path(repo_root, target_path)
        checklist_state = metadata.get("checklist", {})
        if not isinstance(checklist_state, dict):
            checklist_state = {}
        read_specs = checklist_state.get("read_specs", [])
        if not isinstance(read_specs, list):
            read_specs = []
        if normalized not in read_specs:
            read_specs.append(normalized)
        checklist_state["read_specs"] = sorted(read_specs)
        metadata["checklist"] = checklist_state
        task_metadata["metadata"] = metadata
        task_json = utils.task_dir(repo_root, resolved_task_id) / "task.json"
        task_json.write_text(json.dumps(task_metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        asyncio.run(
            utils.emit_cli_event(
                repo_root,
                run_id,
                "spec.checklist_marked_read",
                {"task_id": resolved_task_id, "path": normalized},
            )
        )

    lines, complete = _render_checklist_summary(repo_root, task_metadata)
    if not lines:
        utils.console.print("[yellow]No checklist sources found for this task.[/yellow]")
        if validate:
            raise typer.Exit(code=1)
        return

    utils.console.print(f"[bold]Checklist for {resolved_task_id}[/bold]")
    for line in lines:
        utils.console.print(line)

    if validate and not complete:
        raise typer.Exit(code=1)
