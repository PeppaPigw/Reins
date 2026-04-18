"""Platform types and enums for multi-tool support."""

from __future__ import annotations

from enum import Enum


class PlatformType(str, Enum):
    """Supported AI coding platforms."""

    CLAUDE_CODE = "claude-code"
    """Claude Code CLI and desktop app"""

    CODEX = "codex"
    """OpenAI Codex CLI"""

    CURSOR = "cursor"
    """Cursor IDE"""

    AIDER = "aider"
    """Aider CLI"""

    CONTINUE = "continue"
    """Continue VS Code extension"""

    CODY = "cody"
    """Sourcegraph Cody"""

    GITHUB_COPILOT = "github-copilot"
    """GitHub Copilot"""

    TABNINE = "tabnine"
    """Tabnine"""

    REPLIT_GHOSTWRITER = "replit-ghostwriter"
    """Replit Ghostwriter"""

    AMAZON_Q = "amazon-q"
    """Amazon Q Developer"""

    WINDSURF = "windsurf"
    """Windsurf IDE"""

    CUSTOM = "custom"
    """Custom platform integration"""


class HookType(str, Enum):
    """Types of hooks that platforms can support."""

    SESSION_START = "session_start"
    """Hook executed at session start"""

    SESSION_END = "session_end"
    """Hook executed at session end"""

    SUBAGENT_SPAWN = "subagent_spawn"
    """Hook executed before spawning a subagent"""

    SUBAGENT_COMPLETE = "subagent_complete"
    """Hook executed after subagent completes"""

    TASK_START = "task_start"
    """Hook executed when a task starts"""

    TASK_COMPLETE = "task_complete"
    """Hook executed when a task completes"""

    CONTEXT_INJECT = "context_inject"
    """Hook for injecting context into prompts"""

    TOOL_CALL = "tool_call"
    """Hook executed before/after tool calls"""


class ContextFormat(str, Enum):
    """Format for context injection."""

    JSONL = "jsonl"
    """JSONL format (one JSON object per line)"""

    MARKDOWN = "markdown"
    """Markdown format"""

    YAML = "yaml"
    """YAML format"""

    JSON = "json"
    """JSON format"""

    PLAIN_TEXT = "plain_text"
    """Plain text format"""
