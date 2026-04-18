"""Platform registry for multi-platform AI tooling support."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from reins.platform.types import (
    ContextFormat,
    HookType,
    PlatformCapabilities,
    PlatformConfig,
    PlatformType,
)


def _platform(
    *,
    platform_type: PlatformType,
    name: str,
    config_dir: str,
    cli_flag: str,
    template_dirs: tuple[str, ...],
    detection_markers: tuple[str, ...] = (),
    hook_dir: str | None = None,
    agent_dir: str | None = None,
    command_dir: str | None = None,
    settings_file: str | None = None,
    metadata: dict[str, object] | None = None,
    **capabilities: Any,
) -> PlatformConfig:
    """Create a platform configuration with consistent defaults."""
    return PlatformConfig(
        platform_type=platform_type,
        name=name,
        config_dir=config_dir,
        template_dirs=template_dirs,
        cli_flag=cli_flag,
        hook_dir=hook_dir,
        agent_dir=agent_dir,
        command_dir=command_dir,
        settings_file=settings_file,
        detection_markers=detection_markers,
        capabilities=PlatformCapabilities(**capabilities),
        metadata=dict(metadata or {}),
    )


BUILTIN_PLATFORMS: tuple[PlatformConfig, ...] = (
    _platform(
        platform_type=PlatformType.CLAUDE_CODE,
        name="Claude Code",
        config_dir=".claude",
        cli_flag="claude",
        template_dirs=("common", "claude"),
        hook_dir="hooks",
        agent_dir="agents",
        command_dir="commands",
        settings_file="settings.json",
        detection_markers=(
            ".claude/settings.json",
            ".claude/hooks",
            ".claude/agents",
        ),
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
            HookType.SUBAGENT_SPAWN,
            HookType.CONTEXT_INJECT,
            HookType.TOOL_CALL,
        ],
        supports_jsonl_context=True,
        preferred_context_format=ContextFormat.JSONL,
    ),
    _platform(
        platform_type=PlatformType.CURSOR,
        name="Cursor",
        config_dir=".cursor",
        cli_flag="cursor",
        template_dirs=("common", "cursor"),
        settings_file="settings.json",
        detection_markers=(
            ".cursor/settings.json",
            ".cursorrules",
        ),
        supports_hooks=False,
        supports_agents=False,
        supports_worktrees=False,
        supports_mcp=False,
        supports_tools=True,
        supports_streaming=True,
        supports_context_injection=False,
        max_context_tokens=128_000,
        preferred_context_format=ContextFormat.MARKDOWN,
    ),
    _platform(
        platform_type=PlatformType.CODEX,
        name="Codex",
        config_dir=".codex",
        cli_flag="codex",
        template_dirs=("common", "codex"),
        hook_dir="hooks",
        agent_dir="agents",
        settings_file="config.yaml",
        detection_markers=(
            ".codex/config.yaml",
            ".codex/mcp.json",
            ".codex/agents",
        ),
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
    _platform(
        platform_type=PlatformType.WINDSURF,
        name="Windsurf",
        config_dir=".windsurf",
        cli_flag="windsurf",
        template_dirs=("common", "windsurf"),
        settings_file="settings.json",
        detection_markers=(
            ".windsurf/settings.json",
            ".windsurf/rules",
        ),
        supports_hooks=False,
        supports_agents=False,
        supports_worktrees=False,
        supports_mcp=False,
        supports_tools=True,
        supports_streaming=True,
        supports_context_injection=True,
        max_context_tokens=128_000,
        preferred_context_format=ContextFormat.MARKDOWN,
    ),
    _platform(
        platform_type=PlatformType.AIDER,
        name="Aider",
        config_dir=".aider",
        cli_flag="aider",
        template_dirs=("common", "aider"),
        settings_file="config.yml",
        detection_markers=(
            ".aider",
            ".aider.conf.yml",
            ".aider.conf.json",
        ),
        supports_hooks=True,
        supports_agents=False,
        supports_worktrees=True,
        supports_mcp=False,
        supports_tools=True,
        supports_streaming=True,
        supports_context_injection=True,
        max_context_tokens=128_000,
        supported_hooks=[HookType.SESSION_START, HookType.CONTEXT_INJECT],
        preferred_context_format=ContextFormat.MARKDOWN,
    ),
    _platform(
        platform_type=PlatformType.CONTINUE,
        name="Continue",
        config_dir=".continue",
        cli_flag="continue",
        template_dirs=("common", "continue"),
        settings_file="config.json",
        detection_markers=(
            ".continue/config.json",
            ".continue/config.yaml",
        ),
        supports_hooks=False,
        supports_agents=False,
        supports_worktrees=False,
        supports_mcp=True,
        supports_tools=True,
        supports_streaming=True,
        supports_context_injection=False,
        max_context_tokens=128_000,
        preferred_context_format=ContextFormat.MARKDOWN,
    ),
    _platform(
        platform_type=PlatformType.CLINE,
        name="Cline",
        config_dir=".cline",
        cli_flag="cline",
        template_dirs=("common", "cline"),
        settings_file="config.json",
        detection_markers=(
            ".cline/config.json",
            ".cline/rules",
        ),
        supports_hooks=False,
        supports_agents=True,
        supports_worktrees=True,
        supports_mcp=True,
        supports_tools=True,
        supports_streaming=True,
        supports_context_injection=True,
        max_context_tokens=200_000,
        preferred_context_format=ContextFormat.MARKDOWN,
    ),
    _platform(
        platform_type=PlatformType.ZED_AI,
        name="Zed AI",
        config_dir=".zed",
        cli_flag="zed",
        template_dirs=("common", "zed-ai"),
        settings_file="settings.json",
        detection_markers=(
            ".zed/settings.json",
            ".zed/tasks.json",
        ),
        supports_hooks=False,
        supports_agents=False,
        supports_worktrees=False,
        supports_mcp=False,
        supports_tools=True,
        supports_streaming=True,
        supports_context_injection=False,
        max_context_tokens=128_000,
        preferred_context_format=ContextFormat.MARKDOWN,
    ),
    _platform(
        platform_type=PlatformType.GITHUB_COPILOT,
        name="GitHub Copilot",
        config_dir=".github",
        cli_flag="copilot",
        template_dirs=("common", "github-copilot"),
        settings_file="copilot-instructions.md",
        detection_markers=(
            ".github/copilot-instructions.md",
            ".github/instructions",
        ),
        supports_hooks=False,
        supports_agents=False,
        supports_worktrees=False,
        supports_mcp=False,
        supports_tools=True,
        supports_streaming=True,
        supports_context_injection=True,
        max_context_tokens=128_000,
        preferred_context_format=ContextFormat.MARKDOWN,
    ),
    _platform(
        platform_type=PlatformType.SUPERMAVEN,
        name="Supermaven",
        config_dir=".supermaven",
        cli_flag="supermaven",
        template_dirs=("common", "supermaven"),
        settings_file="config.json",
        detection_markers=(
            ".supermaven/config.json",
            ".supermaven/rules",
        ),
        supports_hooks=False,
        supports_agents=False,
        supports_worktrees=False,
        supports_mcp=False,
        supports_tools=True,
        supports_streaming=True,
        supports_context_injection=False,
        max_context_tokens=128_000,
        preferred_context_format=ContextFormat.MARKDOWN,
    ),
    _platform(
        platform_type=PlatformType.CODY,
        name="Cody",
        config_dir=".cody",
        cli_flag="cody",
        template_dirs=("common", "cody"),
        settings_file="config.json",
        detection_markers=(
            ".cody/config.json",
            ".sourcegraph/cody.json",
        ),
        supports_hooks=False,
        supports_agents=False,
        supports_worktrees=False,
        supports_mcp=False,
        supports_tools=True,
        supports_streaming=True,
        supports_context_injection=False,
        max_context_tokens=100_000,
        preferred_context_format=ContextFormat.MARKDOWN,
    ),
    _platform(
        platform_type=PlatformType.TABNINE,
        name="Tabnine",
        config_dir=".tabnine",
        cli_flag="tabnine",
        template_dirs=("common", "tabnine"),
        settings_file="config.json",
        detection_markers=(
            ".tabnine/config.json",
            ".tabnine/rules",
        ),
        supports_hooks=False,
        supports_agents=False,
        supports_worktrees=False,
        supports_mcp=False,
        supports_tools=True,
        supports_streaming=True,
        supports_context_injection=False,
        max_context_tokens=64_000,
        preferred_context_format=ContextFormat.MARKDOWN,
    ),
    _platform(
        platform_type=PlatformType.AMAZON_Q,
        name="Amazon Q",
        config_dir=".amazonq",
        cli_flag="amazon-q",
        template_dirs=("common", "amazon-q"),
        settings_file="settings.json",
        detection_markers=(
            ".amazonq/settings.json",
            ".amazonq/rules",
        ),
        supports_hooks=False,
        supports_agents=False,
        supports_worktrees=False,
        supports_mcp=False,
        supports_tools=True,
        supports_streaming=True,
        supports_context_injection=True,
        max_context_tokens=128_000,
        preferred_context_format=ContextFormat.MARKDOWN,
    ),
    _platform(
        platform_type=PlatformType.PIECES,
        name="Pieces",
        config_dir=".pieces",
        cli_flag="pieces",
        template_dirs=("common", "pieces"),
        settings_file="config.json",
        detection_markers=(
            ".pieces/config.json",
            ".pieces/workflows",
        ),
        supports_hooks=False,
        supports_agents=False,
        supports_worktrees=False,
        supports_mcp=True,
        supports_tools=True,
        supports_streaming=True,
        supports_context_injection=True,
        max_context_tokens=128_000,
        preferred_context_format=ContextFormat.MARKDOWN,
    ),
)


class PlatformRegistry:
    """Registry of supported AI coding platforms."""

    def __init__(self, platforms: Iterable[PlatformConfig] | None = None) -> None:
        self._platforms: dict[PlatformType, PlatformConfig] = {}
        for config in platforms or BUILTIN_PLATFORMS:
            self.register(config)

    def register(self, config: PlatformConfig) -> None:
        """Register a platform configuration."""
        self._platforms[config.platform_type] = config

    def get(self, platform: PlatformType | str) -> PlatformConfig | None:
        """Get a platform by enum, slug, CLI flag, or name."""
        if isinstance(platform, PlatformType):
            return self._platforms.get(platform)

        normalized = platform.strip().lower()
        for config in self._platforms.values():
            aliases = {
                config.platform_type.value,
                config.name.lower(),
                (config.cli_flag or "").lower(),
            }
            if normalized in aliases:
                return config
        return None

    def list_all(self) -> list[PlatformConfig]:
        """List all registered platforms."""
        return list(self._platforms.values())

    def list_with_capability(self, capability: str) -> list[PlatformConfig]:
        """List platforms that support a specific capability."""
        return [
            config
            for config in self._platforms.values()
            if getattr(config.capabilities, capability, False)
        ]

    def list_with_hook(self, hook_type: HookType) -> list[PlatformConfig]:
        """List platforms that support a specific hook type."""
        return [
            config
            for config in self._platforms.values()
            if hook_type in config.capabilities.supported_hooks
        ]

    def get_by_cli_flag(self, cli_flag: str) -> PlatformConfig | None:
        """Get a platform configuration by CLI flag."""
        return self.get(cli_flag)

    def list_with_jsonl_support(self) -> list[PlatformConfig]:
        """List platforms that support JSONL context injection."""
        return [
            config
            for config in self._platforms.values()
            if config.capabilities.supports_jsonl_context
        ]

    def detect_platforms(self, repo_root: Path) -> list[PlatformConfig]:
        """Detect platform configurations present in a repository."""
        scored: list[tuple[int, PlatformConfig]] = []
        for config in self._platforms.values():
            score = 0
            for marker in config.all_detection_paths:
                if (repo_root / marker).exists():
                    score += 2 if marker == Path(config.config_dir) else 1
            if score:
                scored.append((score, config))

        scored.sort(key=lambda item: (-item[0], item[1].name.lower()))
        return [config for _, config in scored]

    def detect_platform(self, repo_root: Path) -> PlatformConfig | None:
        """Detect the most likely active platform in a repository."""
        matches = self.detect_platforms(repo_root)
        if not matches:
            return None
        return matches[0]


_registry = PlatformRegistry()


def get_platform(platform: PlatformType | str) -> PlatformConfig | None:
    """Get a platform configuration from the global registry."""
    return _registry.get(platform)


def list_platforms() -> list[PlatformConfig]:
    """List all registered platforms from the global registry."""
    return _registry.list_all()


def register_platform(config: PlatformConfig) -> None:
    """Register a custom platform in the global registry."""
    _registry.register(config)


def detect_platforms(repo_root: Path) -> list[PlatformConfig]:
    """Detect all configured platforms present in a repository."""
    return _registry.detect_platforms(repo_root)


def detect_platform(repo_root: Path) -> PlatformConfig | None:
    """Detect the most likely active platform present in a repository."""
    return _registry.detect_platform(repo_root)
