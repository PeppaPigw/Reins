"""Tests for platform configurator."""

import pytest
from pathlib import Path

from reins.platform import (
    ClaudeCodeConfigurator,
    CodexConfigurator,
    GenericConfigurator,
    PlatformConfig,
    PlatformType,
    get_configurator,
    get_platform,
)


def test_claude_code_configurator_initialize(tmp_path):
    """Test Claude Code configurator initialization."""
    config = get_platform(PlatformType.CLAUDE_CODE)
    assert config is not None

    configurator = ClaudeCodeConfigurator(config, tmp_path)
    configurator.initialize()

    # Check that directories were created
    assert (tmp_path / ".claude").exists()
    assert (tmp_path / ".claude" / "hooks").exists()
    assert (tmp_path / ".claude" / "agents").exists()
    assert (tmp_path / ".claude" / "commands").exists()


def test_claude_code_configurator_validate(tmp_path):
    """Test Claude Code configurator validation."""
    config = get_platform(PlatformType.CLAUDE_CODE)
    assert config is not None

    configurator = ClaudeCodeConfigurator(config, tmp_path)

    # Should fail before initialization
    assert configurator.validate_setup() is False

    # Should pass after initialization
    configurator.initialize()
    assert configurator.validate_setup() is True


def test_codex_configurator_initialize(tmp_path):
    """Test Codex configurator initialization."""
    config = get_platform(PlatformType.CODEX)
    assert config is not None

    configurator = CodexConfigurator(config, tmp_path)
    configurator.initialize()

    # Check that directories were created
    assert (tmp_path / ".codex").exists()
    assert (tmp_path / ".codex" / "hooks").exists()
    assert (tmp_path / ".codex" / "agents").exists()


def test_codex_configurator_validate(tmp_path):
    """Test Codex configurator validation."""
    config = get_platform(PlatformType.CODEX)
    assert config is not None

    configurator = CodexConfigurator(config, tmp_path)

    # Should fail before initialization
    assert configurator.validate_setup() is False

    # Should pass after initialization
    configurator.initialize()
    assert configurator.validate_setup() is True


def test_generic_configurator_initialize(tmp_path):
    """Test generic configurator initialization."""
    config = get_platform(PlatformType.CURSOR)
    assert config is not None

    configurator = GenericConfigurator(config, tmp_path)
    configurator.initialize()

    # Check that config directory was created
    assert (tmp_path / ".cursor").exists()


def test_generic_configurator_validate(tmp_path):
    """Test generic configurator validation."""
    config = get_platform(PlatformType.CURSOR)
    assert config is not None

    configurator = GenericConfigurator(config, tmp_path)

    # Should fail before initialization
    assert configurator.validate_setup() is False

    # Should pass after initialization
    configurator.initialize()
    assert configurator.validate_setup() is True


def test_get_configurator_claude_code(tmp_path):
    """Test getting Claude Code configurator."""
    config = get_platform(PlatformType.CLAUDE_CODE)
    assert config is not None

    configurator = get_configurator(config, tmp_path)
    assert isinstance(configurator, ClaudeCodeConfigurator)
    assert configurator.config == config
    assert configurator.repo_root == tmp_path


def test_get_configurator_codex(tmp_path):
    """Test getting Codex configurator."""
    config = get_platform(PlatformType.CODEX)
    assert config is not None

    configurator = get_configurator(config, tmp_path)
    assert isinstance(configurator, CodexConfigurator)
    assert configurator.config == config
    assert configurator.repo_root == tmp_path


def test_get_configurator_generic(tmp_path):
    """Test getting generic configurator for unsupported platform."""
    config = get_platform(PlatformType.CURSOR)
    assert config is not None

    configurator = get_configurator(config, tmp_path)
    assert isinstance(configurator, GenericConfigurator)
    assert configurator.config == config
    assert configurator.repo_root == tmp_path


def test_configurator_get_hook_path(tmp_path):
    """Test getting hook path from configurator."""
    config = get_platform(PlatformType.CLAUDE_CODE)
    assert config is not None

    configurator = ClaudeCodeConfigurator(config, tmp_path)

    hook_path = configurator.get_hook_path("session-start")
    assert hook_path is not None
    assert hook_path == tmp_path / ".claude" / "hooks" / "session-start.py"


def test_configurator_get_agent_path(tmp_path):
    """Test getting agent path from configurator."""
    config = get_platform(PlatformType.CLAUDE_CODE)
    assert config is not None

    configurator = ClaudeCodeConfigurator(config, tmp_path)

    agent_path = configurator.get_agent_path("implement")
    assert agent_path is not None
    assert agent_path == tmp_path / ".claude" / "agents" / "implement.md"


def test_configurator_get_command_path(tmp_path):
    """Test getting command path from configurator."""
    config = get_platform(PlatformType.CLAUDE_CODE)
    assert config is not None

    configurator = ClaudeCodeConfigurator(config, tmp_path)

    command_path = configurator.get_command_path("start")
    assert command_path is not None
    assert command_path == tmp_path / ".claude" / "commands" / "start"


def test_configurator_no_hooks(tmp_path):
    """Test configurator for platform without hooks."""
    config = get_platform(PlatformType.CURSOR)
    assert config is not None

    configurator = GenericConfigurator(config, tmp_path)

    # Should return None for platforms without hooks
    hook_path = configurator.get_hook_path("session-start")
    assert hook_path is None


def test_configurator_ensure_config_dir(tmp_path):
    """Test ensuring config directory exists."""
    config = get_platform(PlatformType.CLAUDE_CODE)
    assert config is not None

    configurator = ClaudeCodeConfigurator(config, tmp_path)

    # Directory should not exist yet
    assert not (tmp_path / ".claude").exists()

    # Ensure it exists
    configurator.ensure_config_dir()
    assert (tmp_path / ".claude").exists()

    # Should be idempotent
    configurator.ensure_config_dir()
    assert (tmp_path / ".claude").exists()


def test_configurator_get_template_dirs(tmp_path):
    """Test getting template directories."""
    config = get_platform(PlatformType.CLAUDE_CODE)
    assert config is not None

    configurator = ClaudeCodeConfigurator(config, tmp_path)

    template_dirs = configurator.get_template_dirs()
    assert len(template_dirs) == 2
    assert any("common" in str(d) for d in template_dirs)
    assert any("claude" in str(d) for d in template_dirs)
