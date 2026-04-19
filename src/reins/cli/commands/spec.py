from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Iterable

import typer
import yaml

from reins.cli import utils
from reins.context.checklist import ChecklistParser, create_checklist_template
from reins.context.compiler import ContextCompiler
from reins.context.validator import SpecValidationIssue, SpecValidator
from reins.platform import ProjectDetector, detect_platform, list_platforms
from reins.platform.remote_registry import (
    RemoteRegistryError,
    RemoteSpecAsset,
    RemoteSpecRegistry,
    copy_assets_to_directory,
)
from reins.platform.template_fetcher import ConflictAction
from reins.platform.template_hash import TemplateHashStore, sha256_path, sha256_text
from reins.context.types import SpecLayer

app = typer.Typer(
    help=(
        "Spec management commands.\n\n"
        "Examples:\n"
        "  reins spec init --type backend --package cli\n"
        "  reins spec update\n"
        "  reins spec fetch starter --remote ./shared-specs\n"
        "  reins spec checklist --validate\n"
        "  reins spec validate\n"
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


def _managed_template_id(layer_name: str, *, package: str | None = None) -> str:
    if package:
        return f"spec:{package}:{layer_name}:index"
    return f"spec:{layer_name}:index"


def _template_identifier_path(layer_name: str, *, package: str | None = None) -> Path:
    template_path = _template_root() / layer_name / "index.md"
    if template_path.exists():
        return template_path
    return Path(".reins/.managed-spec-templates") / _managed_template_id(layer_name, package=package)


def _hash_store(repo_root: Path) -> TemplateHashStore:
    return TemplateHashStore(repo_root)


def _record_managed_spec_file(
    repo_root: Path,
    *,
    target_path: Path,
    template_path: Path,
    content: str,
) -> None:
    template_hash = sha256_path(template_path) if template_path.exists() else sha256_text(
        f"{template_path.as_posix()}\n{content}"
    )
    _hash_store(repo_root).update(
        target_path=target_path,
        template_path=template_path,
        template_hash=template_hash,
        rendered_hash=sha256_text(content),
    )


def _resolve_project_type(
    repo_root: Path,
    *,
    project_type: str | None,
) -> str:
    detector = ProjectDetector()
    return detector.resolve(repo_root, project_type).value


def _resolve_platform_slug(
    repo_root: Path,
    *,
    platform: str | None,
) -> str | None:
    if platform:
        normalized = platform.strip().lower()
        for candidate in list_platforms():
            aliases = {
                candidate.slug,
                candidate.name.lower(),
                (candidate.cli_flag or "").lower(),
            }
            if normalized in aliases:
                return candidate.slug
        raise utils.CLIError(f"Unknown platform: {platform}")

    detected = detect_platform(repo_root)
    return detected.slug if detected is not None else None


def _package_layers_for_project_type(project_type: str, layers: str | None = None) -> list[str]:
    if layers:
        return [item.strip() for item in layers.split(",") if item.strip()]
    return [
        layer.value
        for layer in SpecLayer.default_layers_for_project_type(project_type)
        if layer != SpecLayer.GUIDES
    ]


def _iter_package_dirs(spec_root: Path) -> Iterable[Path]:
    standard = {layer.value for layer in SpecLayer.standard_layers()}
    for path in sorted(spec_root.iterdir()) if spec_root.exists() else []:
        if path.is_dir() and path.name not in standard and not path.name.startswith("."):
            yield path


def _refresh_managed_hashes(
    repo_root: Path,
    *,
    project_type: str,
    package: str | None = None,
    package_layers: list[str] | None = None,
) -> None:
    spec_root = _spec_root(repo_root)
    for layer in (layer.value for layer in SpecLayer.standard_layers()):
        index_path = spec_root / layer / "index.md"
        content = _render_layer_index(layer, layer_dir=spec_root / layer)
        if index_path.exists() and index_path.read_text(encoding="utf-8") == content:
            _record_managed_spec_file(
                repo_root,
                target_path=index_path,
                template_path=_template_identifier_path(layer),
                content=content,
            )

    if package:
        package_dir = spec_root / package
        layers = package_layers or _package_layers_for_project_type(project_type)
        package_index = package_dir / "index.md"
        package_content = _package_index_content(package, layers)
        if package_index.exists() and package_index.read_text(encoding="utf-8") == package_content:
            _record_managed_spec_file(
                repo_root,
                target_path=package_index,
                template_path=Path(".reins/.managed-spec-templates") / f"spec:{package}:package-index",
                content=package_content,
            )
        for layer in layers:
            index_path = package_dir / layer / "index.md"
            content = _render_layer_index(layer, package=package, layer_dir=package_dir / layer)
            if index_path.exists() and index_path.read_text(encoding="utf-8") == content:
                _record_managed_spec_file(
                    repo_root,
                    target_path=index_path,
                    template_path=_template_identifier_path(layer, package=package),
                    content=content,
                )


def _resolve_conflict_action(target_path: Path, *, force: bool) -> ConflictAction:
    if force:
        return ConflictAction.OVERWRITE
    if not sys.stdin.isatty():
        return ConflictAction.KEEP

    utils.console.print(f"[yellow]Customization detected[/yellow] for {target_path}")
    response = typer.prompt("Choose keep / overwrite / merge", default="keep").strip().lower()
    try:
        return ConflictAction(response)
    except ValueError:
        return ConflictAction.KEEP


def _apply_managed_content(
    repo_root: Path,
    *,
    target_path: Path,
    content: str,
    template_path: Path,
    force: bool = False,
) -> str:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    store = _hash_store(repo_root)
    current_hash = sha256_text(content)

    if not target_path.exists():
        target_path.write_text(content, encoding="utf-8")
        _record_managed_spec_file(
            repo_root,
            target_path=target_path,
            template_path=template_path,
            content=content,
        )
        return "created"

    existing_content = target_path.read_text(encoding="utf-8")
    if existing_content == content and not force:
        _record_managed_spec_file(
            repo_root,
            target_path=target_path,
            template_path=template_path,
            content=content,
        )
        return "unchanged"

    record = store.get(target_path)
    has_customization = record is not None and sha256_text(existing_content) != record.rendered_hash
    if record is None and existing_content != content:
        has_customization = True

    if has_customization:
        action = _resolve_conflict_action(target_path, force=force)
        if action is ConflictAction.KEEP:
            return "kept"
        if action is ConflictAction.MERGE:
            merge_path = target_path.with_name(f"{target_path.name}.reins-merge")
            merge_path.write_text(content, encoding="utf-8")
            return "merged"

    target_path.write_text(content, encoding="utf-8")
    _record_managed_spec_file(
        repo_root,
        target_path=target_path,
        template_path=template_path,
        content=content,
    )
    if existing_content == content and force:
        return "refreshed"
    if sha256_text(existing_content) == current_hash:
        return "unchanged"
    return "updated"


def _append_index_entry(index_path: Path, relative_target: str) -> None:
    if not index_path.exists():
        return
    content = index_path.read_text(encoding="utf-8")
    if relative_target in content:
        return
    line = f"- [ ] [{Path(relative_target).stem.replace('-', ' ').title()}]({relative_target}) - Review fetched guidance"
    if "## Files in This Layer" in content:
        content = content.replace("## Files in This Layer", f"## Files in This Layer\n\n{line}", 1)
    else:
        content = content.rstrip() + f"\n\n## Files in This Layer\n\n{line}\n"
    index_path.write_text(content, encoding="utf-8")


def _install_fetched_assets(
    repo_root: Path,
    *,
    assets: list[RemoteSpecAsset],
    output_dir: Path,
) -> list[Path]:
    written = copy_assets_to_directory(assets, output_dir=output_dir)
    spec_root = _spec_root(repo_root).resolve()
    for path in written:
        try:
            relative = path.resolve().relative_to(spec_root)
        except ValueError:
            continue
        if path.name == "index.md" or not relative.parts:
            continue
        if relative.parts[0] in {layer.value for layer in SpecLayer.standard_layers()}:
            layer_dir = spec_root / relative.parts[0]
            _append_index_entry(layer_dir / "index.md", Path(*relative.parts[1:]).as_posix())
        elif len(relative.parts) >= 2:
            layer_dir = spec_root / relative.parts[0] / relative.parts[1]
            _append_index_entry(layer_dir / "index.md", Path(*relative.parts[2:]).as_posix())
    return written


def _fix_validation_issues(
    repo_root: Path,
    *,
    report: list[SpecValidationIssue],
    project_type: str,
) -> list[Path]:
    touched: list[Path] = []
    touched.extend(ensure_standard_spec_layout(repo_root, project_type=project_type))

    for issue in report:
        if issue.code != "missing-checklist":
            continue
        index_path = issue.path
        layer_dir = index_path.parent
        package = None
        layer_name = layer_dir.name
        if layer_dir.parent != _spec_root(repo_root):
            package = layer_dir.parent.name
        if index_path.exists():
            existing = index_path.read_text(encoding="utf-8")
            checklist = _render_layer_index(layer_name, package=package, layer_dir=layer_dir)
            header = checklist.split("## Files in This Layer", 1)[0].rstrip()
            if "## Pre-Development Checklist" not in existing:
                index_path.write_text(f"{existing.rstrip()}\n\n{header}\n", encoding="utf-8")
                touched.append(index_path)
        else:
            content = _render_layer_index(layer_name, package=package, layer_dir=layer_dir)
            index_path.parent.mkdir(parents=True, exist_ok=True)
            index_path.write_text(content, encoding="utf-8")
            touched.append(index_path)
    return touched


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
    platform: str | None = typer.Option(
        None,
        "--platform",
        help="Target platform. Defaults to detected platform when available.",
    ),
    project_type: str | None = typer.Option(
        None,
        "--type",
        "--project-type",
        help="Project type: frontend, backend, or fullstack.",
    ),
    package: str | None = typer.Option(
        None,
        "--package",
        help="Optional package name under .reins/spec/ for monorepo guidance.",
    ),
    layers: str | None = typer.Option(None, "--layers", help="Comma-separated layer names."),
) -> None:
    """
    Initialize spec structure for a project.

    Examples:
      reins spec init
      reins spec init --type fullstack --platform codex
      reins spec init --package auth --layers backend,unit-test
    """
    repo_root = utils.find_repo_root()
    run_id = utils.make_run_id("spec")
    resolved_project_type = _resolve_project_type(repo_root, project_type=project_type)
    resolved_platform = _resolve_platform_slug(repo_root, platform=platform)
    detector = ProjectDetector()
    config_default_package = utils.load_config(repo_root).default_package
    resolved_package = package or config_default_package or detector.resolve_package(repo_root)
    package_layers = _package_layers_for_project_type(resolved_project_type, layers)

    if layers is None:
        created_paths = ensure_standard_spec_layout(
            repo_root,
            project_type=resolved_project_type,
            package=resolved_package,
        )
        _refresh_managed_hashes(
            repo_root,
            project_type=resolved_project_type,
            package=resolved_package,
            package_layers=package_layers,
        )
    else:
        created_paths = []

    if resolved_package and package_layers:
        package_dir = _spec_root(repo_root) / resolved_package
        package_dir.mkdir(parents=True, exist_ok=True)
        for layer in package_layers:
            layer_dir = package_dir / layer
            layer_dir.mkdir(parents=True, exist_ok=True)
            index_path = layer_dir / "index.md"
            action = _apply_managed_content(
                repo_root,
                target_path=index_path,
                content=_render_layer_index(layer, package=resolved_package, layer_dir=layer_dir),
                template_path=_template_identifier_path(layer, package=resolved_package),
            )
            if action == "created":
                created_paths.append(index_path)
        package_action = _apply_managed_content(
            repo_root,
            target_path=package_dir / "index.md",
            content=_package_index_content(resolved_package, package_layers),
            template_path=Path(".reins/.managed-spec-templates") / f"spec:{resolved_package}:package-index",
        )
        if package_action == "created":
            created_paths.append(package_dir / "index.md")

    asyncio.run(
        utils.emit_cli_event(
            repo_root,
            run_id,
            "spec.initialized",
            {
                "platform": resolved_platform,
                "project_type": resolved_project_type,
                "package": resolved_package,
                "layers": package_layers,
                "created_paths": [utils.relpath(path, repo_root) for path in created_paths],
            },
        )
    )
    utils.console.print("[green]Initialized spec layout[/green].")
    utils.console.print(f"Project type: [bold]{resolved_project_type}[/bold]")
    if resolved_platform:
        utils.console.print(f"Platform: [bold]{resolved_platform}[/bold]")
    if resolved_package:
        utils.console.print(f"Package: [bold]{resolved_package}[/bold]")


@app.command("update")
def update_command(
    remote: str | None = typer.Option(None, "--remote", help="Remote registry URL or local path."),
    force: bool = typer.Option(False, "--force", help="Overwrite managed files when conflicts are detected."),
) -> None:
    """
    Update managed specs from local templates or a remote registry.

    Examples:
      reins spec update
      reins spec update --remote ./shared-specs
      reins spec update --remote github:owner/repo/specs@main
    """
    repo_root = utils.find_repo_root()
    run_id = utils.make_run_id("spec")
    changed: list[str] = []
    spec_root = _spec_root(repo_root)

    if remote:
        registry = RemoteSpecRegistry()
        response = registry.fetch(".", remote=remote)
        for path in _install_fetched_assets(repo_root, assets=response.assets, output_dir=spec_root):
            changed.append(utils.relpath(path, repo_root))
    else:
        for layer in (layer.value for layer in SpecLayer.standard_layers()):
            layer_dir = spec_root / layer
            layer_dir.mkdir(parents=True, exist_ok=True)
            target_path = layer_dir / "index.md"
            action = _apply_managed_content(
                repo_root,
                target_path=target_path,
                content=_render_layer_index(layer, layer_dir=layer_dir),
                template_path=_template_identifier_path(layer),
                force=force,
            )
            if action not in {"unchanged", "kept"}:
                changed.append(utils.relpath(target_path, repo_root))

        for package_dir in _iter_package_dirs(spec_root):
            package_layers = sorted(
                path.name for path in package_dir.iterdir() if path.is_dir() and not path.name.startswith(".")
            )
            package_index = package_dir / "index.md"
            action = _apply_managed_content(
                repo_root,
                target_path=package_index,
                content=_package_index_content(package_dir.name, package_layers),
                template_path=Path(".reins/.managed-spec-templates") / f"spec:{package_dir.name}:package-index",
                force=force,
            )
            if action not in {"unchanged", "kept"}:
                changed.append(utils.relpath(package_index, repo_root))
            for layer in package_layers:
                layer_dir = package_dir / layer
                target_path = layer_dir / "index.md"
                action = _apply_managed_content(
                    repo_root,
                    target_path=target_path,
                    content=_render_layer_index(layer, package=package_dir.name, layer_dir=layer_dir),
                    template_path=_template_identifier_path(layer, package=package_dir.name),
                    force=force,
                )
                if action not in {"unchanged", "kept"}:
                    changed.append(utils.relpath(target_path, repo_root))

    asyncio.run(
        utils.emit_cli_event(
            repo_root,
            run_id,
            "spec.updated",
            {"remote": remote, "force": force, "paths": changed},
        )
    )
    if not changed:
        utils.console.print("[yellow]No spec updates applied.[/yellow]")
        return
    utils.console.print("[green]Updated spec files[/green]:")
    for changed_path in changed:
        utils.console.print(f"  - {changed_path}")


@app.command("fetch")
def fetch_command(
    spec_name: str = typer.Argument(..., help="Spec name or path to fetch."),
    remote: str | None = typer.Option(None, "--remote", help="Remote registry URL or local path."),
    output: Path | None = typer.Option(None, "--output", help="Output directory."),
) -> None:
    """
    Fetch remote or local specs into the current repository.

    Examples:
      reins spec fetch starter --remote ./shared-specs
      reins spec fetch github:owner/repo/specs/backend/index.md
      reins spec fetch ./templates/specs --output .reins/spec
    """
    repo_root = utils.find_repo_root()
    run_id = utils.make_run_id("spec")
    registry = RemoteSpecRegistry()
    try:
        response = registry.fetch(spec_name, remote=remote)
    except RemoteRegistryError as exc:
        utils.exit_with_error(str(exc))
        return

    output_dir = output
    if output_dir is None:
        output_dir = _spec_root(repo_root)
        if remote:
            remote_path = Path(remote)
            if remote_path.exists():
                candidate = remote_path / spec_name
                if candidate.exists() and candidate.is_dir():
                    output_dir = output_dir / spec_name
    written = _install_fetched_assets(repo_root, assets=response.assets, output_dir=output_dir)
    asyncio.run(
        utils.emit_cli_event(
            repo_root,
            run_id,
            "spec.fetched",
            {
                "spec_name": spec_name,
                "remote": remote,
                "output": str(output_dir),
                "paths": [utils.relpath(path, repo_root) for path in written],
            },
        )
    )
    utils.console.print(f"[green]Fetched[/green] {len(written)} spec file(s).")


@app.command("list")
def list_command(
    layer: str | None = typer.Argument(None, help="Optional layer name to filter on."),
    package: str | None = typer.Option(None, "--package", help="Filter to a single package."),
) -> None:
    """
    List spec packages, layers, and manifests on disk.

    Examples:
      reins spec list
      reins spec list backend
      reins spec list --package auth
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
        if layer and path.parent.name != layer and path.name != layer:
            continue
        rows.append({"kind": kind, "path": utils.relpath(path, repo_root)})

    if not rows:
        utils.console.print("[yellow]No specs found.[/yellow]")
        return
    utils.console.print(utils.format_table(rows, ["kind", "path"]))


@app.command("validate")
def validate_command(
    spec_path: str | None = typer.Argument(None, help="Optional spec file or directory path."),
    fix: bool = typer.Option(False, "--fix", help="Auto-fix missing layout and checklist issues."),
    project_type: str | None = typer.Option(
        None,
        "--type",
        "--project-type",
        help="Project type override for required layer checks.",
    ),
) -> None:
    """
    Validate spec structure, markdown links, and YAML metadata.

    Examples:
      reins spec validate
      reins spec validate .reins/spec/backend
      reins spec validate --fix
    """
    repo_root = utils.find_repo_root()
    run_id = utils.make_run_id("spec")
    target = Path(spec_path).resolve() if spec_path else _spec_root(repo_root)
    resolved_project_type = _resolve_project_type(repo_root, project_type=project_type)

    if not target.exists():
        utils.exit_with_error(f"Spec path not found: {target}")
        return

    yaml_paths: list[Path]
    if target.is_dir():
        yaml_paths = sorted([*target.rglob("*.yaml"), *target.rglob("*.yml")])
    else:
        yaml_paths = [target] if target.suffix in {".yaml", ".yml"} else []

    issues: list[str] = []
    is_spec_root = target.is_dir() and target.resolve() == _spec_root(repo_root).resolve()
    if is_spec_root:
        validator = SpecValidator(target)
        report = validator.validate(project_type=resolved_project_type)
        if fix and report.issues:
            _fix_validation_issues(repo_root, report=report.issues, project_type=resolved_project_type)
            report = validator.validate(project_type=resolved_project_type)
        issues.extend(issue.display(repo_root) for issue in report.issues)
    elif not yaml_paths:
        utils.console.print("[yellow]No YAML spec files found to validate.[/yellow]")
        return

    for path in yaml_paths:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            line = getattr(getattr(exc, "problem_mark", None), "line", None)
            location = f"{utils.relpath(path, repo_root)}:{line + 1}" if line is not None else utils.relpath(path, repo_root)
            issues.append(f"{location}: YAML parse error: {exc}")
            continue
        if not isinstance(data, dict):
            issues.append(f"{utils.relpath(path, repo_root)}: YAML root must be a mapping")
            continue
        issues.extend(
            error.replace(str(path), utils.relpath(path, repo_root))
            for error in _validate_spec_data(data, path)
        )

    asyncio.run(
        utils.emit_cli_event(
            repo_root,
            run_id,
            "spec.validated",
            {"path": str(target), "fix": fix, "valid": not issues},
        )
    )

    if issues:
        for issue in issues:
            utils.console.print(f"[red]{issue}[/red]")
        raise typer.Exit(code=1)

    utils.console.print(f"[green]Validated[/green] {len(yaml_paths)} YAML file(s) and spec structure.")


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
