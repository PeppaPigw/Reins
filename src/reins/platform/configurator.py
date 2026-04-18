"""Platform configurator base classes and configurator registry."""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Mapping

from reins.platform.registry import get_platform
from reins.platform.template_fetcher import (
    ConflictResolver,
    TemplateApplyResult,
    TemplateFetcher,
)
from reins.platform.template_hash import TemplateHashStore
from reins.platform.types import PlatformConfig, PlatformType


class PlatformConfigurator(ABC):
    """Base class for platform-specific configurators."""

    def __init__(
        self,
        config: PlatformConfig,
        repo_root: Path,
        *,
        template_fetcher: TemplateFetcher | None = None,
    ) -> None:
        self.config = config
        self.repo_root = repo_root
        self.config_path = repo_root / config.config_dir
        self.hash_store = TemplateHashStore(repo_root)
        self.template_fetcher = template_fetcher or TemplateFetcher(
            hash_store=self.hash_store
        )

    @abstractmethod
    def configure(
        self,
        *,
        variables: Mapping[str, str] | None = None,
        conflict_resolver: ConflictResolver | None = None,
    ) -> list[TemplateApplyResult]:
        """Configure the repository for the platform."""

    @abstractmethod
    def validate(self) -> bool:
        """Validate that the platform-specific files are installed."""

    @abstractmethod
    def cleanup(self) -> None:
        """Remove platform-specific files created by the configurator."""

    def initialize(self, options: dict[str, str] | None = None) -> None:
        """Compatibility wrapper for earlier tests and callers."""
        self.configure(variables=options or None)

    def validate_setup(self) -> bool:
        """Compatibility wrapper for earlier tests and callers."""
        return self.validate()

    def setup_hooks(self) -> None:
        """Compatibility no-op for earlier tests and callers."""

    def setup_agents(self) -> None:
        """Compatibility no-op for earlier tests and callers."""

    def setup_commands(self) -> None:
        """Compatibility no-op for earlier tests and callers."""

    def get_template_dirs(self) -> list[Path]:
        """Return the template directories associated with this platform."""
        template_root = self.template_fetcher.template_root
        return [template_root / name for name in self.config.template_dirs]

    def ensure_config_dir(self) -> None:
        """Ensure the platform config directory exists."""
        self.config_path.mkdir(parents=True, exist_ok=True)

    def ensure_dir(self, path: Path) -> None:
        """Ensure a directory exists."""
        path.mkdir(parents=True, exist_ok=True)

    def get_hook_path(self, hook_name: str) -> Path | None:
        """Return the full path to a hook file if hooks are supported."""
        if self.config.hook_dir is None:
            return None
        return self.config_path / self.config.hook_dir / f"{hook_name}.py"

    def get_agent_path(self, agent_name: str) -> Path | None:
        """Return the full path to an agent file if agents are supported."""
        if self.config.agent_dir is None:
            return None
        return self.config_path / self.config.agent_dir / f"{agent_name}.md"

    def get_command_path(self, command_name: str) -> Path | None:
        """Return the full path to a command file if commands are supported."""
        if self.config.command_dir is None:
            return None
        return self.config_path / self.config.command_dir / command_name

    def default_variables(
        self,
        variables: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        """Build the default template variable set."""
        resolved = {
            "repo_root": str(self.repo_root),
            "developer": "unknown",
            "project_type": "backend",
            "platform": self.config.slug,
        }
        if variables:
            resolved.update(dict(variables))
        return resolved

    def apply_templates(
        self,
        mapping: Mapping[str, str],
        *,
        variables: Mapping[str, str] | None = None,
        conflict_resolver: ConflictResolver | None = None,
    ) -> list[TemplateApplyResult]:
        """Apply platform templates to the repository."""
        return self.template_fetcher.install_templates(
            platform=self.config,
            repo_root=self.repo_root,
            file_mapping=mapping,
            variables=self.default_variables(variables),
            conflict_resolver=conflict_resolver,
        )

    def remove_paths(self, relative_paths: list[str]) -> None:
        """Remove files or directories relative to the repository root."""
        for relative_path in relative_paths:
            target_path = self.repo_root / relative_path
            if target_path.is_dir():
                shutil.rmtree(target_path, ignore_errors=True)
            elif target_path.exists():
                target_path.unlink()


class GenericConfigurator(PlatformConfigurator):
    """Fallback configurator for platforms without special behavior."""

    def configure(
        self,
        *,
        variables: Mapping[str, str] | None = None,
        conflict_resolver: ConflictResolver | None = None,
    ) -> list[TemplateApplyResult]:
        del variables, conflict_resolver
        self.ensure_config_dir()
        return []

    def validate(self) -> bool:
        """Validate the generic platform setup."""
        return self.config_path.exists()

    def cleanup(self) -> None:
        """Remove the generic platform directory."""
        self.remove_paths([self.config.config_dir])


def _resolve_config(
    platform: PlatformConfig | PlatformType | str,
) -> PlatformConfig:
    if isinstance(platform, PlatformConfig):
        return platform
    config = get_platform(platform)
    if config is None:
        raise ValueError(f"Unknown platform: {platform}")
    return config


def _configurator_registry() -> dict[PlatformType, type[PlatformConfigurator]]:
    from reins.platform.configurators.claude import ClaudeCodeConfigurator
    from reins.platform.configurators.codex import CodexConfigurator
    from reins.platform.configurators.cursor import CursorConfigurator

    return {
        PlatformType.CLAUDE_CODE: ClaudeCodeConfigurator,
        PlatformType.CURSOR: CursorConfigurator,
        PlatformType.CODEX: CodexConfigurator,
    }


def get_configurator(
    platform: PlatformConfig | PlatformType | str,
    repo_root: Path,
) -> PlatformConfigurator:
    """Return the configurator for a platform."""
    config = _resolve_config(platform)
    configurator_type = _configurator_registry().get(
        config.platform_type,
        GenericConfigurator,
    )
    return configurator_type(config, repo_root)
