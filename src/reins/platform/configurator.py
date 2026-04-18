"""Platform configurator interface for setting up platform-specific environments.

Configurators handle platform-specific initialization, template rendering,
and environment setup.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from reins.platform.registry import PlatformConfig


class PlatformConfigurator(ABC):
    """Base class for platform-specific configurators.

    Each platform (Claude Code, Codex, Cursor, etc.) has a configurator
    that knows how to set up the platform-specific directory structure,
    render templates, and configure hooks.
    """

    def __init__(self, config: PlatformConfig, repo_root: Path) -> None:
        """Initialize configurator.

        Args:
            config: Platform configuration
            repo_root: Root directory of the repository
        """
        self.config = config
        self.repo_root = repo_root
        self.config_path = repo_root / config.config_dir

    @abstractmethod
    def initialize(self, options: dict[str, Any] | None = None) -> None:
        """Initialize platform-specific directory structure.

        Args:
            options: Optional configuration options
        """
        pass

    @abstractmethod
    def setup_hooks(self) -> None:
        """Set up platform-specific hooks."""
        pass

    @abstractmethod
    def setup_agents(self) -> None:
        """Set up platform-specific agents."""
        pass

    @abstractmethod
    def setup_commands(self) -> None:
        """Set up platform-specific commands."""
        pass

    @abstractmethod
    def validate_setup(self) -> bool:
        """Validate that the platform is correctly set up.

        Returns:
            True if setup is valid, False otherwise
        """
        pass

    def get_template_dirs(self) -> list[Path]:
        """Get template directories for this platform.

        Returns:
            List of template directory paths
        """
        template_base = Path(__file__).parent.parent.parent / "templates"
        return [template_base / dir_name for dir_name in self.config.template_dirs]

    def ensure_config_dir(self) -> None:
        """Ensure platform config directory exists."""
        self.config_path.mkdir(parents=True, exist_ok=True)

    def get_hook_path(self, hook_name: str) -> Path | None:
        """Get path to a specific hook file.

        Args:
            hook_name: Name of the hook (e.g., 'session-start')

        Returns:
            Path to hook file or None if hooks not supported
        """
        if not self.config.hook_path:
            return None
        return self.repo_root / self.config.hook_path / f"{hook_name}.py"

    def get_agent_path(self, agent_name: str) -> Path | None:
        """Get path to a specific agent file.

        Args:
            agent_name: Name of the agent (e.g., 'implement')

        Returns:
            Path to agent file or None if agents not supported
        """
        if not self.config.agent_path:
            return None
        return self.repo_root / self.config.agent_path / f"{agent_name}.md"

    def get_command_path(self, command_name: str) -> Path | None:
        """Get path to a specific command file.

        Args:
            command_name: Name of the command (e.g., 'start')

        Returns:
            Path to command file or None if commands not supported
        """
        if not self.config.command_path:
            return None
        return self.repo_root / self.config.command_path / command_name


class ClaudeCodeConfigurator(PlatformConfigurator):
    """Configurator for Claude Code platform."""

    def initialize(self, options: dict[str, Any] | None = None) -> None:
        """Initialize Claude Code directory structure."""
        self.ensure_config_dir()

        # Create subdirectories
        if self.config.hook_dir:
            (self.config_path / self.config.hook_dir).mkdir(exist_ok=True)
        if self.config.agent_dir:
            (self.config_path / self.config.agent_dir).mkdir(exist_ok=True)
        if self.config.command_dir:
            (self.config_path / self.config.command_dir).mkdir(exist_ok=True)

    def setup_hooks(self) -> None:
        """Set up Claude Code hooks."""
        if not self.config.capabilities.supports_hooks:
            return

        # Hook setup will be implemented when we create hook templates
        pass

    def setup_agents(self) -> None:
        """Set up Claude Code agents."""
        if not self.config.capabilities.supports_agents:
            return

        # Agent setup will be implemented when we create agent templates
        pass

    def setup_commands(self) -> None:
        """Set up Claude Code commands."""
        # Command setup will be implemented when we create command templates
        pass

    def validate_setup(self) -> bool:
        """Validate Claude Code setup."""
        # Check that config directory exists
        if not self.config_path.exists():
            return False

        # Check that required subdirectories exist
        if self.config.hook_dir and not (self.config_path / self.config.hook_dir).exists():
            return False
        if self.config.agent_dir and not (self.config_path / self.config.agent_dir).exists():
            return False
        if self.config.command_dir and not (self.config_path / self.config.command_dir).exists():
            return False

        return True


class CodexConfigurator(PlatformConfigurator):
    """Configurator for Codex platform."""

    def initialize(self, options: dict[str, Any] | None = None) -> None:
        """Initialize Codex directory structure."""
        self.ensure_config_dir()

        # Create subdirectories
        if self.config.hook_dir:
            (self.config_path / self.config.hook_dir).mkdir(exist_ok=True)
        if self.config.agent_dir:
            (self.config_path / self.config.agent_dir).mkdir(exist_ok=True)

    def setup_hooks(self) -> None:
        """Set up Codex hooks."""
        if not self.config.capabilities.supports_hooks:
            return

        # Hook setup will be implemented when we create hook templates
        pass

    def setup_agents(self) -> None:
        """Set up Codex agents."""
        if not self.config.capabilities.supports_agents:
            return

        # Agent setup will be implemented when we create agent templates
        pass

    def setup_commands(self) -> None:
        """Set up Codex commands."""
        # Codex doesn't have custom commands
        pass

    def validate_setup(self) -> bool:
        """Validate Codex setup."""
        if not self.config_path.exists():
            return False

        if self.config.hook_dir and not (self.config_path / self.config.hook_dir).exists():
            return False
        if self.config.agent_dir and not (self.config_path / self.config.agent_dir).exists():
            return False

        return True


class GenericConfigurator(PlatformConfigurator):
    """Generic configurator for platforms without special requirements."""

    def initialize(self, options: dict[str, Any] | None = None) -> None:
        """Initialize generic platform directory structure."""
        self.ensure_config_dir()

    def setup_hooks(self) -> None:
        """Set up hooks (if supported)."""
        pass

    def setup_agents(self) -> None:
        """Set up agents (if supported)."""
        pass

    def setup_commands(self) -> None:
        """Set up commands (if supported)."""
        pass

    def validate_setup(self) -> bool:
        """Validate generic setup."""
        return self.config_path.exists()


# Configurator registry
_CONFIGURATORS: dict[str, type[PlatformConfigurator]] = {
    "claude-code": ClaudeCodeConfigurator,
    "codex": CodexConfigurator,
}


def get_configurator(
    config: PlatformConfig, repo_root: Path
) -> PlatformConfigurator:
    """Get configurator for a platform.

    Args:
        config: Platform configuration
        repo_root: Root directory of the repository

    Returns:
        Platform configurator instance
    """
    configurator_class = _CONFIGURATORS.get(
        config.platform_type, GenericConfigurator
    )
    return configurator_class(config, repo_root)
