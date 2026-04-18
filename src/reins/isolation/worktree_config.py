"""Declarative worktree configuration loader for agent worktrees."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from reins.isolation.types import WorktreeConfig

DEFAULT_WORKTREE_PATHS = (
    Path(".reins/worktree.yaml"),
    Path(".trellis/worktree.yaml"),
)


class WorktreeConfigError(ValueError):
    """Raised when worktree YAML configuration is invalid."""


@dataclass(frozen=True)
class WorktreeTemplateConfig:
    """Repository-level worktree defaults loaded from YAML."""

    worktree_dir: Path
    copy: list[str] = field(default_factory=list)
    post_create: list[str] = field(default_factory=list)
    verify: list[str] = field(default_factory=list)
    source_path: Path | None = None

    @classmethod
    def default(cls, repo_root: Path) -> WorktreeTemplateConfig:
        """Return the default config when no YAML file exists."""
        return cls(
            worktree_dir=(repo_root / "../reins-worktrees").resolve(),
            copy=[".reins/.developer"],
            post_create=[],
            verify=[],
            source_path=None,
        )

    def build_runtime_config(
        self,
        *,
        worktree_name: str,
        branch_name: str,
        base_branch: str,
        create_branch: bool = True,
        cleanup_on_success: bool = True,
        cleanup_on_failure: bool = False,
        extra_copy_files: list[str] | None = None,
    ) -> WorktreeConfig:
        """Convert repo-level YAML defaults into a runtime worktree config."""
        copy_files = _dedupe_strings(self.copy + list(extra_copy_files or []))
        return WorktreeConfig(
            worktree_base_dir=self.worktree_dir,
            worktree_name=worktree_name,
            branch_name=branch_name,
            base_branch=base_branch,
            create_branch=create_branch,
            copy_files=copy_files,
            post_create_commands=list(self.post_create),
            verify_commands=list(self.verify),
            cleanup_on_success=cleanup_on_success,
            cleanup_on_failure=cleanup_on_failure,
        )


def load_worktree_config(
    repo_root: Path,
    path: Path | None = None,
) -> WorktreeTemplateConfig:
    """Load worktree YAML config from the repo.

    Prefers `.reins/worktree.yaml`, then falls back to `.trellis/worktree.yaml`.
    If neither exists, returns a default config.
    """
    repo_root = repo_root.resolve()
    config_path = _resolve_config_path(repo_root, path)
    if config_path is None:
        return WorktreeTemplateConfig.default(repo_root)

    if not config_path.exists():
        raise WorktreeConfigError(f"worktree config does not exist: {config_path}")

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise WorktreeConfigError(f"invalid YAML in {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise WorktreeConfigError(
            f"worktree config must be a mapping in {config_path}"
        )

    allowed_keys = {"worktree_dir", "copy", "post_create", "verify"}
    unknown_keys = sorted(set(raw) - allowed_keys)
    if unknown_keys:
        raise WorktreeConfigError(
            f"unknown worktree config keys in {config_path}: {', '.join(unknown_keys)}"
        )

    worktree_dir_raw = raw.get("worktree_dir", "../reins-worktrees")
    if not isinstance(worktree_dir_raw, str) or not worktree_dir_raw.strip():
        raise WorktreeConfigError(
            f"worktree_dir must be a non-empty string in {config_path}"
        )

    return WorktreeTemplateConfig(
        worktree_dir=(repo_root / worktree_dir_raw).resolve(),
        copy=_validate_string_list(raw.get("copy", [".reins/.developer"]), "copy", config_path),
        post_create=_validate_string_list(
            raw.get("post_create", []),
            "post_create",
            config_path,
        ),
        verify=_validate_string_list(raw.get("verify", []), "verify", config_path),
        source_path=config_path,
    )


def save_worktree_config(
    config: WorktreeTemplateConfig,
    *,
    repo_root: Path,
    path: Path | None = None,
) -> Path:
    """Save worktree YAML config to disk."""
    repo_root = repo_root.resolve()
    target = (path or repo_root / ".reins" / "worktree.yaml").resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "worktree_dir": _display_path(config.worktree_dir, repo_root),
        "copy": list(config.copy),
        "post_create": list(config.post_create),
        "verify": list(config.verify),
    }
    target.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return target


def _resolve_config_path(repo_root: Path, path: Path | None) -> Path | None:
    if path is not None:
        return path.resolve()

    for candidate in DEFAULT_WORKTREE_PATHS:
        resolved = (repo_root / candidate).resolve()
        if resolved.exists():
            return resolved
    return None


def _validate_string_list(
    value: object,
    field_name: str,
    config_path: Path,
) -> list[str]:
    if not isinstance(value, list):
        raise WorktreeConfigError(
            f"{field_name} must be a list of strings in {config_path}"
        )
    for item in value:
        if not isinstance(item, str):
            raise WorktreeConfigError(
                f"{field_name} must contain only strings in {config_path}"
            )
    return list(value)


def _display_path(target: Path, repo_root: Path) -> str:
    try:
        return str(target.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return str(Path("..") / target.resolve().relative_to(repo_root.parent.resolve()))


def _dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        deduped.append(value)
        seen.add(value)
    return deduped
