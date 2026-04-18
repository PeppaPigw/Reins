"""Core platform types for the Reins platform abstraction layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class PlatformType(str, Enum):
    """Supported AI coding platforms."""

    CLAUDE_CODE = "claude-code"
    CURSOR = "cursor"
    CODEX = "codex"
    WINDSURF = "windsurf"
    AIDER = "aider"
    CONTINUE = "continue"
    CLINE = "cline"
    ZED_AI = "zed-ai"
    GITHUB_COPILOT = "github-copilot"
    SUPERMAVEN = "supermaven"
    CODY = "cody"
    TABNINE = "tabnine"
    AMAZON_Q = "amazon-q"
    PIECES = "pieces"
    CUSTOM = "custom"


class HookType(str, Enum):
    """Types of hooks that platforms can support."""

    SESSION_START = "session_start"
    SESSION_END = "session_end"
    SUBAGENT_SPAWN = "subagent_spawn"
    SUBAGENT_COMPLETE = "subagent_complete"
    TASK_START = "task_start"
    TASK_COMPLETE = "task_complete"
    CONTEXT_INJECT = "context_inject"
    TOOL_CALL = "tool_call"


class ContextFormat(str, Enum):
    """Format used for context injection or project guidance."""

    JSONL = "jsonl"
    MARKDOWN = "markdown"
    YAML = "yaml"
    JSON = "json"
    PLAIN_TEXT = "plain_text"


@dataclass(frozen=True)
class PlatformCapabilities:
    """Capabilities supported by a platform."""

    supports_hooks: bool = False
    supports_agents: bool = False
    supports_worktrees: bool = False
    supports_mcp: bool = False
    supports_tools: bool = False
    supports_streaming: bool = False
    supports_context_injection: bool = False
    max_context_tokens: int = 200_000
    supported_hooks: list[HookType] = field(default_factory=list)
    supports_jsonl_context: bool = False
    preferred_context_format: ContextFormat = ContextFormat.MARKDOWN


@dataclass(frozen=True)
class PlatformConfig:
    """Configuration metadata for a specific platform."""

    platform_type: PlatformType
    name: str
    config_dir: str
    template_dirs: tuple[str, ...]
    capabilities: PlatformCapabilities
    cli_flag: str | None = None
    hook_dir: str | None = None
    agent_dir: str | None = None
    command_dir: str | None = None
    settings_file: str | None = None
    detection_markers: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def slug(self) -> str:
        """Return the canonical platform slug."""
        return self.platform_type.value

    @property
    def hook_path(self) -> Path | None:
        """Get the full path to the hook directory."""
        if self.hook_dir is None:
            return None
        return Path(self.config_dir) / self.hook_dir

    @property
    def agent_path(self) -> Path | None:
        """Get the full path to the agent directory."""
        if self.agent_dir is None:
            return None
        return Path(self.config_dir) / self.agent_dir

    @property
    def command_path(self) -> Path | None:
        """Get the full path to the command directory."""
        if self.command_dir is None:
            return None
        return Path(self.config_dir) / self.command_dir

    @property
    def settings_path(self) -> Path | None:
        """Get the full path to the settings file."""
        if self.settings_file is None:
            return None
        return Path(self.config_dir) / self.settings_file

    @property
    def all_detection_paths(self) -> tuple[Path, ...]:
        """Return all config and detection paths used for platform discovery."""
        config_path = Path(self.config_dir)
        markers = tuple(Path(marker) for marker in self.detection_markers)
        if config_path in markers:
            return markers
        return (config_path, *markers)
