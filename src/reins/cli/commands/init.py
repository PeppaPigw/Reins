from __future__ import annotations

import asyncio
import getpass
import sys
from pathlib import Path

import typer

from reins.cli import utils
from reins.cli.commands.spec import migrate_spec_layout
from reins.platform import (
    ProjectDetector,
    ProjectType,
    TemplateApplyResult,
    get_configurator,
    list_platforms,
)
from reins.platform.registry import detect_platform
from reins.platform.types import PlatformConfig


def _resolve_platform(
    platform_value: str | None,
    *,
    repo_root: Path,
) -> PlatformConfig:
    if platform_value:
        normalized = platform_value.strip().lower()
        for platform in list_platforms():
            aliases = {
                platform.platform_type.value,
                platform.name.lower(),
                (platform.cli_flag or "").lower(),
            }
            if normalized in aliases:
                return platform
        raise utils.CLIError(f"Unknown platform: {platform_value}")

    detected = detect_platform(repo_root)
    if detected is not None:
        return detected

    platforms = list_platforms()
    utils.console.print("Select a platform:")
    for index, platform in enumerate(platforms, start=1):
        utils.console.print(f"  {index}. {platform.name} [{platform.cli_flag}]")

    selection = typer.prompt("Platform", default=platforms[0].cli_flag or platforms[0].slug)
    if selection.isdigit():
        position = int(selection) - 1
        if 0 <= position < len(platforms):
            return platforms[position]
        raise utils.CLIError(f"Invalid platform selection: {selection}")

    for platform in platforms:
        aliases = {
            platform.platform_type.value,
            platform.name.lower(),
            (platform.cli_flag or "").lower(),
        }
        if selection.strip().lower() in aliases:
            return platform

    raise utils.CLIError(f"Unknown platform selection: {selection}")


def _resolve_developer(repo_root: Path, developer: str | None) -> str:
    if developer:
        return developer

    identity = utils.read_developer_identity(repo_root)
    if identity and identity.get("name"):
        return identity["name"]

    try:
        return getpass.getuser()
    except (OSError, KeyError):
        return "unknown"


def _create_reins_layout(repo_root: Path) -> list[Path]:
    utils.ensure_reins_layout(repo_root)
    created_paths = [
        repo_root / ".reins" / "tasks",
        repo_root / ".reins" / "workspace",
        repo_root / ".reins" / "spec",
    ]
    for path in created_paths:
        path.mkdir(parents=True, exist_ok=True)

    files_to_touch = [
        repo_root / ".reins" / "journal.jsonl",
        repo_root / ".reins" / ".current-task",
    ]
    for path in files_to_touch:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)

    return [*created_paths, *files_to_touch]


def _resolve_package(
    detector: ProjectDetector,
    repo_root: Path,
    package: str | None,
) -> str | None:
    if package:
        return package

    detected_packages = detector.detect_packages(repo_root)
    if len(detected_packages) == 1:
        return detected_packages[0]

    if detected_packages and sys.stdin.isatty():
        selection = typer.prompt(
            "Package (optional)",
            default="",
        ).strip()
        return selection or None

    return None


def _summarize_templates(results: list[TemplateApplyResult], repo_root: Path) -> list[str]:
    lines: list[str] = []
    for result in results:
        lines.append(f"{result.action}: {utils.relpath(result.target_path, repo_root)}")
    return lines


def init_command(
    platform: str | None = typer.Option(
        None,
        "--platform",
        help="Platform CLI flag or name. If omitted, Reins auto-detects or prompts.",
    ),
    project_type: ProjectType | None = typer.Option(
        None,
        "--project-type",
        help="Override project type detection.",
        case_sensitive=False,
    ),
    developer: str | None = typer.Option(
        None,
        "--developer",
        help="Developer name for template rendering.",
    ),
    package: str | None = typer.Option(
        None,
        "--package",
        help="Optional package name for package-local spec scaffolding.",
    ),
) -> None:
    """Initialize Reins in the current repository."""
    repo_root = utils.find_repo_root_for_init()
    run_id = utils.make_run_id("init")
    detector = ProjectDetector()

    try:
        selected_platform = _resolve_platform(platform, repo_root=repo_root)
        resolved_project_type = project_type or detector.detect(repo_root)
        developer_name = _resolve_developer(repo_root, developer)
        resolved_package = _resolve_package(detector, repo_root, package)

        created_paths = _create_reins_layout(repo_root)
        created_paths.extend(
            migrate_spec_layout(
                repo_root,
                project_type=resolved_project_type.value,
                package=resolved_package,
            )
        )
        configurator = get_configurator(selected_platform, repo_root)
        template_results = configurator.configure(
            variables={
                "repo_root": str(repo_root),
                "developer": developer_name,
                "project_type": resolved_project_type.value,
                "platform": selected_platform.slug,
                "package": resolved_package or "",
            }
        )

        asyncio.run(
            utils.emit_cli_event(
                repo_root,
                run_id,
                "project.initialized",
                {
                    "platform": selected_platform.slug,
                    "project_type": resolved_project_type.value,
                    "developer": developer_name,
                    "package": resolved_package,
                    "created_paths": [utils.relpath(path, repo_root) for path in created_paths],
                    "template_results": [
                        {
                            "path": utils.relpath(result.target_path, repo_root),
                            "action": result.action,
                        }
                        for result in template_results
                    ],
                },
            )
        )

        utils.console.print(
            f"[green]Initialized Reins[/green] for [bold]{selected_platform.name}[/bold]"
        )
        utils.console.print(f"Project type: [bold]{resolved_project_type.value}[/bold]")
        utils.console.print(f"Developer: [bold]{developer_name}[/bold]")
        if resolved_package:
            utils.console.print(f"Package: [bold]{resolved_package}[/bold]")
        for line in _summarize_templates(template_results, repo_root):
            utils.console.print(f"  - {line}")
    except Exception as exc:  # pragma: no cover - exercised in CLI tests
        asyncio.run(
            utils.emit_cli_error(
                repo_root,
                run_id,
                "init",
                exc,
                {"platform": platform or "auto"},
            )
        )
        utils.exit_with_error(str(exc))
