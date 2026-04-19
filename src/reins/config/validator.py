"""Validation helpers for `.reins` configuration."""

from __future__ import annotations

from pathlib import Path

from reins.config.types import ReinsConfig
from reins.isolation.worktree_config import WorktreeTemplateConfig

VALID_PACKAGE_TYPES = {"package", "submodule"}


def validate_config(
    config: ReinsConfig,
    *,
    repo_root: Path | None = None,
) -> list[str]:
    """Validate configuration and return error strings."""
    errors: list[str] = []
    base_dir = (repo_root or Path.cwd()).resolve()

    if config.max_journal_lines < 100:
        errors.append("max_journal_lines must be >= 100")

    for name, package in config.packages.items():
        if package.type not in VALID_PACKAGE_TYPES:
            errors.append(
                f"Package '{name}' has invalid type '{package.type}'"
            )
        package_path = Path(package.path)
        if not package_path.is_absolute():
            package_path = base_dir / package_path
        if not package_path.exists():
            errors.append(
                f"Package path does not exist for '{name}': {package.path}"
            )

    if config.default_package and config.default_package not in config.packages:
        errors.append(
            f"default_package '{config.default_package}' not in packages"
        )

    return errors


def validate_worktree_config(
    config: WorktreeTemplateConfig,
    *,
    repo_root: Path | None = None,
) -> list[str]:
    """Validate repository-level worktree configuration."""
    del config
    del repo_root
    return []
