"""Tests for platform registry."""

import pytest

from reins.platform import (
    PlatformCapabilities,
    PlatformConfig,
    PlatformRegistry,
    PlatformType,
    HookType,
    get_platform,
    list_platforms,
    register_platform,
)


def test_platform_capabilities_defaults():
    """Test default platform capabilities."""
    caps = PlatformCapabilities()

    assert caps.supports_hooks is False
    assert caps.supports_agents is False
    assert caps.supports_worktrees is False
    assert caps.supports_mcp is False
    assert caps.supports_tools is False
    assert caps.supports_streaming is False
    assert caps.supports_context_injection is False
    assert caps.max_context_tokens == 200_000
    assert caps.supported_hooks == []


def test_platform_config_paths():
    """Test platform config path properties."""
    config = PlatformConfig(
        platform_type=PlatformType.CLAUDE_CODE,
        name="Claude Code",
        config_dir=".claude",
        capabilities=PlatformCapabilities(),
        hook_dir="hooks",
        agent_dir="agents",
        command_dir="commands",
        settings_file="settings.json",
    )

    assert config.hook_path is not None
    assert str(config.hook_path) == ".claude/hooks"

    assert config.agent_path is not None
    assert str(config.agent_path) == ".claude/agents"

    assert config.command_path is not None
    assert str(config.command_path) == ".claude/commands"

    assert config.settings_path is not None
    assert str(config.settings_path) == ".claude/settings.json"


def test_platform_config_no_paths():
    """Test platform config without optional paths."""
    config = PlatformConfig(
        platform_type=PlatformType.CURSOR,
        name="Cursor",
        config_dir=".cursor",
        capabilities=PlatformCapabilities(),
    )

    assert config.hook_path is None
    assert config.agent_path is None
    assert config.command_path is None
    assert config.settings_path is None


def test_registry_builtin_platforms():
    """Test that built-in platforms are registered."""
    registry = PlatformRegistry()

    # Check Claude Code
    claude = registry.get(PlatformType.CLAUDE_CODE)
    assert claude is not None
    assert claude.name == "Claude Code"
    assert claude.config_dir == ".claude"
    assert claude.capabilities.supports_hooks is True
    assert claude.capabilities.supports_agents is True
    assert claude.capabilities.supports_worktrees is True
    assert claude.capabilities.supports_mcp is True

    # Check Codex
    codex = registry.get(PlatformType.CODEX)
    assert codex is not None
    assert codex.name == "OpenAI Codex"
    assert codex.config_dir == ".codex"

    # Check Cursor
    cursor = registry.get(PlatformType.CURSOR)
    assert cursor is not None
    assert cursor.name == "Cursor IDE"
    assert cursor.capabilities.supports_hooks is False


def test_registry_list_all():
    """Test listing all platforms."""
    registry = PlatformRegistry()
    platforms = registry.list_all()

    assert len(platforms) >= 6  # At least 6 built-in platforms

    platform_types = {p.platform_type for p in platforms}
    assert PlatformType.CLAUDE_CODE in platform_types
    assert PlatformType.CODEX in platform_types
    assert PlatformType.CURSOR in platform_types


def test_registry_list_with_capability():
    """Test filtering platforms by capability."""
    registry = PlatformRegistry()

    # Platforms with hooks
    with_hooks = registry.list_with_capability("supports_hooks")
    assert len(with_hooks) > 0
    assert all(p.capabilities.supports_hooks for p in with_hooks)

    # Platforms with agents
    with_agents = registry.list_with_capability("supports_agents")
    assert len(with_agents) > 0
    assert all(p.capabilities.supports_agents for p in with_agents)

    # Platforms with worktrees
    with_worktrees = registry.list_with_capability("supports_worktrees")
    assert len(with_worktrees) > 0
    assert all(p.capabilities.supports_worktrees for p in with_worktrees)


def test_registry_list_with_hook():
    """Test filtering platforms by hook type."""
    registry = PlatformRegistry()

    # Platforms with session_start hook
    with_session_start = registry.list_with_hook(HookType.SESSION_START)
    assert len(with_session_start) > 0
    assert all(
        HookType.SESSION_START in p.capabilities.supported_hooks
        for p in with_session_start
    )

    # Platforms with context_inject hook
    with_context_inject = registry.list_with_hook(HookType.CONTEXT_INJECT)
    assert len(with_context_inject) > 0
    assert all(
        HookType.CONTEXT_INJECT in p.capabilities.supported_hooks
        for p in with_context_inject
    )


def test_registry_custom_platform():
    """Test registering a custom platform."""
    registry = PlatformRegistry()

    custom_config = PlatformConfig(
        platform_type=PlatformType.CUSTOM,
        name="Custom Platform",
        config_dir=".custom",
        capabilities=PlatformCapabilities(
            supports_hooks=True,
            supports_agents=True,
            max_context_tokens=50_000,
        ),
        hook_dir="hooks",
        metadata={"custom_field": "custom_value"},
    )

    registry.register(custom_config)

    retrieved = registry.get(PlatformType.CUSTOM)
    assert retrieved is not None
    assert retrieved.name == "Custom Platform"
    assert retrieved.capabilities.max_context_tokens == 50_000
    assert retrieved.metadata["custom_field"] == "custom_value"


def test_global_functions():
    """Test global registry functions."""
    # Get platform
    claude = get_platform(PlatformType.CLAUDE_CODE)
    assert claude is not None
    assert claude.name == "Claude Code"

    # List platforms
    platforms = list_platforms()
    assert len(platforms) >= 6

    # Register custom platform
    custom_config = PlatformConfig(
        platform_type=PlatformType.CUSTOM,
        name="Test Custom",
        config_dir=".test",
        capabilities=PlatformCapabilities(),
    )
    register_platform(custom_config)

    retrieved = get_platform(PlatformType.CUSTOM)
    assert retrieved is not None
    assert retrieved.name == "Test Custom"


def test_claude_code_capabilities():
    """Test Claude Code specific capabilities."""
    claude = get_platform(PlatformType.CLAUDE_CODE)
    assert claude is not None

    caps = claude.capabilities
    assert caps.supports_hooks is True
    assert caps.supports_agents is True
    assert caps.supports_worktrees is True
    assert caps.supports_mcp is True
    assert caps.supports_tools is True
    assert caps.supports_streaming is True
    assert caps.supports_context_injection is True
    assert caps.max_context_tokens == 200_000

    # Check supported hooks
    assert HookType.SESSION_START in caps.supported_hooks
    assert HookType.SESSION_END in caps.supported_hooks
    assert HookType.SUBAGENT_SPAWN in caps.supported_hooks
    assert HookType.CONTEXT_INJECT in caps.supported_hooks
    assert HookType.TOOL_CALL in caps.supported_hooks


def test_codex_capabilities():
    """Test Codex specific capabilities."""
    codex = get_platform(PlatformType.CODEX)
    assert codex is not None

    caps = codex.capabilities
    assert caps.supports_hooks is True
    assert caps.supports_agents is True
    assert caps.supports_worktrees is True
    assert caps.supports_mcp is True
    assert caps.max_context_tokens == 128_000

    # Check supported hooks
    assert HookType.SESSION_START in caps.supported_hooks
    assert HookType.SUBAGENT_SPAWN in caps.supported_hooks
    assert HookType.CONTEXT_INJECT in caps.supported_hooks


def test_cursor_capabilities():
    """Test Cursor specific capabilities."""
    cursor = get_platform(PlatformType.CURSOR)
    assert cursor is not None

    caps = cursor.capabilities
    assert caps.supports_hooks is False
    assert caps.supports_agents is False
    assert caps.supports_worktrees is False
    assert caps.supports_mcp is False
    assert caps.supports_tools is True
    assert caps.supports_streaming is True
    assert caps.max_context_tokens == 100_000

    # No hooks supported
    assert len(caps.supported_hooks) == 0


def test_platform_metadata():
    """Test platform metadata fields."""
    claude = get_platform(PlatformType.CLAUDE_CODE)
    assert claude is not None
    assert claude.metadata["cli_flag"] == "claude"
    assert claude.metadata["has_python_hooks"] is True
    assert claude.metadata["supports_slash_commands"] is True

    cursor = get_platform(PlatformType.CURSOR)
    assert cursor is not None
    assert cursor.metadata["cli_flag"] == "cursor"
    assert cursor.metadata["ide_integration"] is True
