"""Declarative platform descriptors for template-driven configuration."""

from __future__ import annotations

from dataclasses import dataclass

from reins.platform.types import PlatformType


@dataclass(frozen=True)
class FileMapping:
    """Maps a template source to a target path within the platform config dir."""

    template_source: str
    target_path: str


@dataclass(frozen=True)
class HookDescriptor:
    """Describes a hook template to install for a platform."""

    name: str
    template_source: str
    language: str = "python"


@dataclass(frozen=True)
class PlatformDescriptor:
    """Declarative description of a platform's configuration layout."""

    platform_type: PlatformType
    files: tuple[FileMapping, ...]
    hooks: tuple[HookDescriptor, ...] = ()
    subdirs: tuple[str, ...] = ()
    settings_file: str | None = None


PLATFORM_DESCRIPTORS: dict[PlatformType, PlatformDescriptor] = {
    PlatformType.CLAUDE_CODE: PlatformDescriptor(
        platform_type=PlatformType.CLAUDE_CODE,
        files=(
            FileMapping("settings.json", "settings.json"),
            FileMapping("agents/README.md", "agents/README.md"),
        ),
        hooks=(
            HookDescriptor(
                "session-start", "hooks/session-start.py"
            ),
            HookDescriptor(
                "inject-subagent-context",
                "hooks/inject-subagent-context.py",
            ),
        ),
        subdirs=("hooks", "agents", "commands"),
        settings_file="settings.json",
    ),
    PlatformType.CURSOR: PlatformDescriptor(
        platform_type=PlatformType.CURSOR,
        files=(
            FileMapping(".cursorrules", ".cursorrules"),
            FileMapping("settings.json", "settings.json"),
        ),
        hooks=(),
        subdirs=(),
        settings_file="settings.json",
    ),
    PlatformType.CODEX: PlatformDescriptor(
        platform_type=PlatformType.CODEX,
        files=(
            FileMapping("config.yaml", "config.yaml"),
            FileMapping("mcp.json", "mcp.json"),
            FileMapping("agents/README.md", "agents/README.md"),
        ),
        hooks=(
            HookDescriptor("session-start", "hooks/session-start.py"),
        ),
        subdirs=("hooks", "agents"),
        settings_file="config.yaml",
    ),
    PlatformType.WINDSURF: PlatformDescriptor(
        platform_type=PlatformType.WINDSURF,
        files=(),
        hooks=(),
        subdirs=(),
    ),
    PlatformType.AIDER: PlatformDescriptor(
        platform_type=PlatformType.AIDER,
        files=(),
        hooks=(),
        subdirs=(),
    ),
    PlatformType.CONTINUE: PlatformDescriptor(
        platform_type=PlatformType.CONTINUE,
        files=(),
        hooks=(),
        subdirs=(),
    ),
    PlatformType.CLINE: PlatformDescriptor(
        platform_type=PlatformType.CLINE,
        files=(),
        hooks=(),
        subdirs=(),
    ),
    PlatformType.ZED_AI: PlatformDescriptor(
        platform_type=PlatformType.ZED_AI,
        files=(),
        hooks=(),
        subdirs=(),
    ),
    PlatformType.GITHUB_COPILOT: PlatformDescriptor(
        platform_type=PlatformType.GITHUB_COPILOT,
        files=(),
        hooks=(),
        subdirs=(),
    ),
    PlatformType.SUPERMAVEN: PlatformDescriptor(
        platform_type=PlatformType.SUPERMAVEN,
        files=(),
        hooks=(),
        subdirs=(),
    ),
    PlatformType.CODY: PlatformDescriptor(
        platform_type=PlatformType.CODY,
        files=(),
        hooks=(),
        subdirs=(),
    ),
    PlatformType.TABNINE: PlatformDescriptor(
        platform_type=PlatformType.TABNINE,
        files=(),
        hooks=(),
        subdirs=(),
    ),
    PlatformType.AMAZON_Q: PlatformDescriptor(
        platform_type=PlatformType.AMAZON_Q,
        files=(),
        hooks=(),
        subdirs=(),
    ),
    PlatformType.PIECES: PlatformDescriptor(
        platform_type=PlatformType.PIECES,
        files=(),
        hooks=(),
        subdirs=(),
    ),
}


def get_descriptor(platform_type: PlatformType) -> PlatformDescriptor | None:
    """Return the descriptor for a platform type, or None if not found."""
    return PLATFORM_DESCRIPTORS.get(platform_type)
