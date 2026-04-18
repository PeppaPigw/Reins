"""Platform registry for multi-tool support.

Provides a single source of truth for platform metadata, capabilities,
and configuration across different AI coding tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reins.platform.types import ContextFormat, HookType, PlatformType


@dataclass(frozen=True)
class PlatformCapabilities:
    """Capabilities supported by a platform."""

    supports_hooks: bool = False
    """Whether the platform supports hook execution"""

    supports_agents: bool = False
    """Whether the platform supports multi-agent workflows"""

    supports_worktrees: bool = False
    """Whether the platform supports git worktree isolation"""

    supports_mcp: bool = False
    """Whether the platform supports Model Context Protocol"""

    supports_tools: bool = False
    """Whether the platform supports tool/function calling"""

    supports_streaming: bool = False
    """Whether the platform supports streaming responses"""

    supports_context_injection: bool = False
    """Whether the platform supports context injection via hooks"""

    max_context_tokens: int = 200_000
    """Maximum context window size in tokens"""

    supported_hooks: list[HookType] = field(default_factory=list)
    """List of hook types supported by this platform"""

    supports_jsonl_context: bool = False
    """Whether the platform supports JSONL context format"""

    preferred_context_format: ContextFormat = ContextFormat.MARKDOWN
    """Preferred format for context injection"""


@dataclass(frozen=True)
class PlatformConfig:
    """Configuration for a specific platform."""

    platform_type: PlatformType
    """Type of platform"""

    name: str
    """Human-readable platform name"""

    config_dir: str
    """Configuration directory (e.g., '.claude', '.cursor')"""

    capabilities: PlatformCapabilities
    """Platform capabilities"""

    hook_dir: str | None = None
    """Directory for hook scripts (relative to config_dir)"""

    agent_dir: str | None = None
    """Directory for agent definitions (relative to config_dir)"""

    command_dir: str | None = None
    """Directory for custom commands (relative to config_dir)"""

    settings_file: str | None = None
    """Settings file name (relative to config_dir)"""

    template_dirs: list[str] = field(default_factory=list)
    """Template directories for initialization"""

    cli_flag: str | None = None
    """CLI flag for platform selection (e.g., 'claude', 'codex')"""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional platform-specific metadata"""

    @property
    def hook_path(self) -> Path | None:
        """Get full path to hook directory."""
        if self.hook_dir:
            return Path(self.config_dir) / self.hook_dir
        return None

    @property
    def agent_path(self) -> Path | None:
        """Get full path to agent directory."""
        if self.agent_dir:
            return Path(self.config_dir) / self.agent_dir
        return None

    @property
    def command_path(self) -> Path | None:
        """Get full path to command directory."""
        if self.command_dir:
            return Path(self.config_dir) / self.command_dir
        return None

    @property
    def settings_path(self) -> Path | None:
        """Get full path to settings file."""
        if self.settings_file:
            return Path(self.config_dir) / self.settings_file
        return None


class PlatformRegistry:
    """Registry of supported platforms.

    Provides a single source of truth for platform metadata and capabilities.
    """

    def __init__(self) -> None:
        self._platforms: dict[PlatformType, PlatformConfig] = {}
        self._register_builtin_platforms()

    def _register_builtin_platforms(self) -> None:
        """Register built-in platform configurations."""

        # Claude Code
        self.register(
            PlatformConfig(
                platform_type=PlatformType.CLAUDE_CODE,
                name="Claude Code",
                config_dir=".claude",
                capabilities=PlatformCapabilities(
                    supports_hooks=True,
                    supports_agents=True,
                    supports_worktrees=True,
                    supports_mcp=True,
                    supports_tools=True,
                    supports_streaming=True,
                    supports_context_injection=True,
                    max_context_tokens=200_000,
                    supported_hooks=[
                        HookType.SESSION_START,
                        HookType.SESSION_END,
                        HookType.SUBAGENT_SPAWN,
                        HookType.CONTEXT_INJECT,
                        HookType.TOOL_CALL,
                    ],
                    supports_jsonl_context=True,
                    preferred_context_format=ContextFormat.JSONL,
                ),
                hook_dir="hooks",
                agent_dir="agents",
                command_dir="commands",
                settings_file="settings.json",
                template_dirs=["common", "claude"],
                cli_flag="claude",
                metadata={
                    "cli_flag": "claude",
                    "has_python_hooks": True,
                    "supports_slash_commands": True,
                },
            )
        )

        # Codex
        self.register(
            PlatformConfig(
                platform_type=PlatformType.CODEX,
                name="OpenAI Codex",
                config_dir=".codex",
                capabilities=PlatformCapabilities(
                    supports_hooks=True,
                    supports_agents=True,
                    supports_worktrees=True,
                    supports_mcp=True,
                    supports_tools=True,
                    supports_streaming=True,
                    supports_context_injection=True,
                    max_context_tokens=128_000,
                    supported_hooks=[
                        HookType.SESSION_START,
                        HookType.SUBAGENT_SPAWN,
                        HookType.CONTEXT_INJECT,
                    ],
                    supports_jsonl_context=True,
                    preferred_context_format=ContextFormat.JSONL,
                ),
                hook_dir="hooks",
                agent_dir="agents",
                settings_file="config.json",
                template_dirs=["common", "codex"],
                cli_flag="codex",
                metadata={
                    "cli_flag": "codex",
                    "has_python_hooks": True,
                },
            )
        )

        # Cursor
        self.register(
            PlatformConfig(
                platform_type=PlatformType.CURSOR,
                name="Cursor IDE",
                config_dir=".cursor",
                capabilities=PlatformCapabilities(
                    supports_hooks=False,
                    supports_agents=False,
                    supports_worktrees=False,
                    supports_mcp=False,
                    supports_tools=True,
                    supports_streaming=True,
                    supports_context_injection=False,
                    max_context_tokens=100_000,
                    supported_hooks=[],
                    supports_jsonl_context=False,
                    preferred_context_format=ContextFormat.MARKDOWN,
                ),
                settings_file="settings.json",
                template_dirs=["common", "cursor"],
                cli_flag="cursor",
                metadata={
                    "cli_flag": "cursor",
                    "ide_integration": True,
                },
            )
        )

        # Aider
        self.register(
            PlatformConfig(
                platform_type=PlatformType.AIDER,
                name="Aider",
                config_dir=".aider",
                capabilities=PlatformCapabilities(
                    supports_hooks=True,
                    supports_agents=False,
                    supports_worktrees=True,
                    supports_mcp=False,
                    supports_tools=True,
                    supports_streaming=True,
                    supports_context_injection=True,
                    max_context_tokens=128_000,
                    supported_hooks=[
                        HookType.SESSION_START,
                        HookType.CONTEXT_INJECT,
                    ],
                    supports_jsonl_context=False,
                    preferred_context_format=ContextFormat.MARKDOWN,
                ),
                hook_dir="hooks",
                settings_file="config.yml",
                template_dirs=["common", "aider"],
                cli_flag="aider",
                metadata={
                    "cli_flag": "aider",
                    "has_python_hooks": True,
                },
            )
        )

        # Continue
        self.register(
            PlatformConfig(
                platform_type=PlatformType.CONTINUE,
                name="Continue",
                config_dir=".continue",
                capabilities=PlatformCapabilities(
                    supports_hooks=False,
                    supports_agents=False,
                    supports_worktrees=False,
                    supports_mcp=True,
                    supports_tools=True,
                    supports_streaming=True,
                    supports_context_injection=False,
                    max_context_tokens=100_000,
                    supported_hooks=[],
                    supports_jsonl_context=False,
                    preferred_context_format=ContextFormat.MARKDOWN,
                ),
                settings_file="config.json",
                template_dirs=["common", "continue"],
                cli_flag="continue",
                metadata={
                    "cli_flag": "continue",
                    "vscode_extension": True,
                },
            )
        )

        # Cody
        self.register(
            PlatformConfig(
                platform_type=PlatformType.CODY,
                name="Sourcegraph Cody",
                config_dir=".cody",
                capabilities=PlatformCapabilities(
                    supports_hooks=False,
                    supports_agents=False,
                    supports_worktrees=False,
                    supports_mcp=False,
                    supports_tools=True,
                    supports_streaming=True,
                    supports_context_injection=False,
                    max_context_tokens=100_000,
                    supported_hooks=[],
                    supports_jsonl_context=False,
                    preferred_context_format=ContextFormat.MARKDOWN,
                ),
                settings_file="config.json",
                template_dirs=["common", "cody"],
                cli_flag="cody",
                metadata={
                    "cli_flag": "cody",
                    "vscode_extension": True,
                },
            )
        )

    def register(self, config: PlatformConfig) -> None:
        """Register a platform configuration.

        Args:
            config: Platform configuration to register
        """
        self._platforms[config.platform_type] = config

    def get(self, platform_type: PlatformType) -> PlatformConfig | None:
        """Get platform configuration by type.

        Args:
            platform_type: Type of platform to get

        Returns:
            Platform configuration or None if not found
        """
        return self._platforms.get(platform_type)

    def list_all(self) -> list[PlatformConfig]:
        """List all registered platforms.

        Returns:
            List of all platform configurations
        """
        return list(self._platforms.values())

    def list_with_capability(self, capability: str) -> list[PlatformConfig]:
        """List platforms that support a specific capability.

        Args:
            capability: Capability name (e.g., 'supports_hooks')

        Returns:
            List of platforms with the capability
        """
        return [
            config
            for config in self._platforms.values()
            if getattr(config.capabilities, capability, False)
        ]

    def list_with_hook(self, hook_type: HookType) -> list[PlatformConfig]:
        """List platforms that support a specific hook type.

        Args:
            hook_type: Type of hook

        Returns:
            List of platforms supporting the hook
        """
        return [
            config
            for config in self._platforms.values()
            if hook_type in config.capabilities.supported_hooks
        ]

    def get_by_cli_flag(self, cli_flag: str) -> PlatformConfig | None:
        """Get platform configuration by CLI flag.

        Args:
            cli_flag: CLI flag (e.g., 'claude', 'codex')

        Returns:
            Platform configuration or None if not found
        """
        for config in self._platforms.values():
            if config.cli_flag == cli_flag:
                return config
        return None

    def list_with_jsonl_support(self) -> list[PlatformConfig]:
        """List platforms that support JSONL context format.

        Returns:
            List of platforms with JSONL support
        """
        return [
            config
            for config in self._platforms.values()
            if config.capabilities.supports_jsonl_context
        ]


# Global registry instance
_registry = PlatformRegistry()


def get_platform(platform_type: PlatformType) -> PlatformConfig | None:
    """Get platform configuration by type.

    Args:
        platform_type: Type of platform to get

    Returns:
        Platform configuration or None if not found
    """
    return _registry.get(platform_type)


def list_platforms() -> list[PlatformConfig]:
    """List all registered platforms.

    Returns:
        List of all platform configurations
    """
    return _registry.list_all()


def register_platform(config: PlatformConfig) -> None:
    """Register a custom platform configuration.

    Args:
        config: Platform configuration to register
    """
    _registry.register(config)
