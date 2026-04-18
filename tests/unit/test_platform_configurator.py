"""Unit tests for platform configurators."""

from __future__ import annotations

from pathlib import Path

from reins.platform import (
    ClaudeCodeConfigurator,
    CodexConfigurator,
    CursorConfigurator,
    GenericConfigurator,
    PlatformType,
    get_configurator,
    get_platform,
)


def test_claude_code_configurator_initialize(tmp_path: Path) -> None:
    config = get_platform(PlatformType.CLAUDE_CODE)
    assert config is not None

    configurator = ClaudeCodeConfigurator(config, tmp_path)
    configurator.initialize()

    assert (tmp_path / ".claude").exists()
    assert (tmp_path / ".claude" / "hooks" / "session-start.py").exists()
    assert (tmp_path / ".claude" / "hooks" / "inject-subagent-context.py").exists()
    assert (tmp_path / ".claude" / "agents" / "README.md").exists()
    assert (tmp_path / ".claude" / "commands").exists()
    assert configurator.validate_setup() is True


def test_cursor_configurator_initialize(tmp_path: Path) -> None:
    config = get_platform(PlatformType.CURSOR)
    assert config is not None

    configurator = CursorConfigurator(config, tmp_path)
    configurator.initialize({"developer": "peppa"})

    assert (tmp_path / ".cursor" / "settings.json").exists()
    assert (tmp_path / ".cursorrules").exists()
    assert configurator.validate_setup() is True


def test_codex_configurator_initialize(tmp_path: Path) -> None:
    config = get_platform(PlatformType.CODEX)
    assert config is not None

    configurator = CodexConfigurator(config, tmp_path)
    configurator.initialize({"developer": "peppa"})

    assert (tmp_path / ".codex" / "config.yaml").exists()
    assert (tmp_path / ".codex" / "mcp.json").exists()
    assert (tmp_path / ".codex" / "agents" / "README.md").exists()
    assert configurator.validate_setup() is True


def test_generic_configurator_initialize(tmp_path: Path) -> None:
    config = get_platform(PlatformType.TABNINE)
    assert config is not None

    configurator = GenericConfigurator(config, tmp_path)
    configurator.initialize()

    assert (tmp_path / ".tabnine").exists()
    assert configurator.validate_setup() is True


def test_get_configurator_returns_specialized_configurators(tmp_path: Path) -> None:
    assert isinstance(
        get_configurator(PlatformType.CLAUDE_CODE, tmp_path),
        ClaudeCodeConfigurator,
    )
    assert isinstance(
        get_configurator(PlatformType.CURSOR, tmp_path),
        CursorConfigurator,
    )
    assert isinstance(
        get_configurator(PlatformType.CODEX, tmp_path),
        CodexConfigurator,
    )
    assert isinstance(
        get_configurator(PlatformType.TABNINE, tmp_path),
        GenericConfigurator,
    )


def test_configurator_path_helpers(tmp_path: Path) -> None:
    config = get_platform(PlatformType.CLAUDE_CODE)
    assert config is not None

    configurator = ClaudeCodeConfigurator(config, tmp_path)

    assert configurator.get_hook_path("session-start") == (
        tmp_path / ".claude" / "hooks" / "session-start.py"
    )
    assert configurator.get_agent_path("implement") == (
        tmp_path / ".claude" / "agents" / "implement.md"
    )
    assert configurator.get_command_path("start") == (
        tmp_path / ".claude" / "commands" / "start"
    )


def test_configurator_template_dirs_include_platform_directory(tmp_path: Path) -> None:
    config = get_platform(PlatformType.CLAUDE_CODE)
    assert config is not None

    configurator = ClaudeCodeConfigurator(config, tmp_path)
    template_dirs = configurator.get_template_dirs()

    assert any(path.name == "common" for path in template_dirs)
    assert any(path.name == "claude" for path in template_dirs)
