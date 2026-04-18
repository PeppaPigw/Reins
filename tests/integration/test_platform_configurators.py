"""Integration tests for platform configurators."""

from __future__ import annotations

from pathlib import Path

from reins.platform import (
    ClaudeCodeConfigurator,
    CodexConfigurator,
    CursorConfigurator,
    PlatformType,
    get_configurator,
    get_platform,
)


def test_claude_configurator_renders_templates_with_variables(tmp_path: Path) -> None:
    config = get_platform(PlatformType.CLAUDE_CODE)
    assert config is not None

    configurator = ClaudeCodeConfigurator(config, tmp_path)
    results = configurator.configure(
        variables={"developer": "peppa", "project_type": "backend"}
    )

    settings = (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8")
    assert '"developer": "peppa"' in settings
    assert '"project_type": "backend"' in settings
    assert {result.action for result in results} == {"created"}
    assert configurator.validate() is True


def test_cursor_configurator_creates_rules_and_settings(tmp_path: Path) -> None:
    config = get_platform(PlatformType.CURSOR)
    assert config is not None

    configurator = CursorConfigurator(config, tmp_path)
    configurator.configure(variables={"developer": "peppa", "project_type": "frontend"})

    rules = (tmp_path / ".cursorrules").read_text(encoding="utf-8")
    settings = (tmp_path / ".cursor" / "settings.json").read_text(encoding="utf-8")
    assert "Developer: `peppa`" in rules
    assert '"project_type": "frontend"' in settings
    assert configurator.validate() is True


def test_codex_configurator_creates_mcp_configuration(tmp_path: Path) -> None:
    config = get_platform(PlatformType.CODEX)
    assert config is not None

    configurator = CodexConfigurator(config, tmp_path)
    configurator.configure(variables={"developer": "peppa"})

    config_yaml = (tmp_path / ".codex" / "config.yaml").read_text(encoding="utf-8")
    mcp_json = (tmp_path / ".codex" / "mcp.json").read_text(encoding="utf-8")
    assert 'developer: "peppa"' in config_yaml
    assert '"reins-local"' in mcp_json
    assert configurator.validate() is True


def test_configurator_factory_dispatches_to_specialized_classes(tmp_path: Path) -> None:
    assert isinstance(get_configurator("claude", tmp_path), ClaudeCodeConfigurator)
    assert isinstance(get_configurator("cursor", tmp_path), CursorConfigurator)
    assert isinstance(get_configurator("codex", tmp_path), CodexConfigurator)
