"""Dataclasses for `.reins` configuration files."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PackageConfig:
    """Monorepo package configuration."""

    path: str
    type: str = "package"


@dataclass
class HooksConfig:
    """Task lifecycle hook commands."""

    after_create: list[str] = field(default_factory=list)
    after_start: list[str] = field(default_factory=list)
    after_archive: list[str] = field(default_factory=list)


@dataclass
class UpdateConfig:
    """Update-time skip configuration."""

    skip: list[str] = field(default_factory=list)


@dataclass
class WorktreeConfig:
    """Repository-level worktree YAML configuration."""

    worktree_dir: str = "../reins-worktrees"
    copy: list[str] = field(default_factory=lambda: [".reins/.developer"])
    post_create: list[str] = field(default_factory=list)
    verify: list[str] = field(default_factory=list)


@dataclass
class ReinsConfig:
    """Project-level `.reins/config.yaml` settings."""

    session_commit_message: str = "chore: record journal"
    max_journal_lines: int = 2000
    packages: dict[str, PackageConfig] = field(default_factory=dict)
    default_package: str | None = None
    hooks: HooksConfig = field(default_factory=HooksConfig)
    update: UpdateConfig = field(default_factory=UpdateConfig)

    def to_dict(self) -> dict[str, Any]:
        """Return a YAML-serializable mapping."""
        return asdict(self)
