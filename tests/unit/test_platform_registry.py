"""Tests for the platform registry and detection logic."""

from __future__ import annotations

from pathlib import Path

import pytest

from reins.platform import (
    ContextFormat,
    HookType,
    PlatformCapabilities,
    PlatformConfig,
    PlatformRegistry,
    PlatformType,
    detect_platform,
    detect_platforms,
    get_platform,
    list_platforms,
)


EXPECTED_BUILTINS = {
    PlatformType.CLAUDE_CODE,
    PlatformType.CURSOR,
    PlatformType.CODEX,
    PlatformType.WINDSURF,
    PlatformType.AIDER,
    PlatformType.CONTINUE,
    PlatformType.CLINE,
    PlatformType.ZED_AI,
    PlatformType.GITHUB_COPILOT,
    PlatformType.SUPERMAVEN,
    PlatformType.CODY,
    PlatformType.TABNINE,
    PlatformType.AMAZON_Q,
    PlatformType.PIECES,
}


def test_platform_capabilities_defaults() -> None:
    caps = PlatformCapabilities()

    assert caps.supports_hooks is False
    assert caps.supports_agents is False
    assert caps.supports_worktrees is False
    assert caps.supports_mcp is False
    assert caps.supported_hooks == []
    assert caps.preferred_context_format == ContextFormat.MARKDOWN


def test_platform_config_paths() -> None:
    config = PlatformConfig(
        platform_type=PlatformType.CLAUDE_CODE,
        name="Claude Code",
        config_dir=".claude",
        template_dirs=("claude",),
        capabilities=PlatformCapabilities(),
        hook_dir="hooks",
        agent_dir="agents",
        command_dir="commands",
        settings_file="settings.json",
        detection_markers=(".claude/settings.json",),
    )

    assert config.slug == "claude-code"
    assert config.hook_path == Path(".claude/hooks")
    assert config.agent_path == Path(".claude/agents")
    assert config.command_path == Path(".claude/commands")
    assert config.settings_path == Path(".claude/settings.json")
    assert config.all_detection_paths == (
        Path(".claude"),
        Path(".claude/settings.json"),
    )


def test_registry_contains_all_builtin_platforms() -> None:
    registry = PlatformRegistry()

    platform_types = {platform.platform_type for platform in registry.list_all()}
    assert platform_types == EXPECTED_BUILTINS


@pytest.mark.parametrize(
    ("platform_name", "config_dir", "cli_flag", "supports_hooks", "supports_agents", "supports_mcp"),
    [
        ("claude-code", ".claude", "claude", True, True, True),
        ("cursor", ".cursor", "cursor", False, False, False),
        ("codex", ".codex", "codex", True, True, True),
        ("windsurf", ".windsurf", "windsurf", False, False, False),
        ("aider", ".aider", "aider", True, False, False),
        ("continue", ".continue", "continue", False, False, True),
        ("cline", ".cline", "cline", False, True, True),
        ("zed-ai", ".zed", "zed", False, False, False),
        ("github-copilot", ".github", "copilot", False, False, False),
        ("supermaven", ".supermaven", "supermaven", False, False, False),
        ("cody", ".cody", "cody", False, False, False),
        ("tabnine", ".tabnine", "tabnine", False, False, False),
        ("amazon-q", ".amazonq", "amazon-q", False, False, False),
        ("pieces", ".pieces", "pieces", False, False, True),
    ],
)
def test_builtin_platform_metadata(
    platform_name: str,
    config_dir: str,
    cli_flag: str,
    supports_hooks: bool,
    supports_agents: bool,
    supports_mcp: bool,
) -> None:
    registry = PlatformRegistry()

    platform = registry.get(platform_name)
    assert platform is not None
    assert platform.config_dir == config_dir
    assert platform.cli_flag == cli_flag
    assert platform.template_dirs
    assert platform.capabilities.supports_hooks is supports_hooks
    assert platform.capabilities.supports_agents is supports_agents
    assert platform.capabilities.supports_mcp is supports_mcp


def test_registry_lookup_by_name_and_cli_flag() -> None:
    registry = PlatformRegistry()

    assert registry.get("claude") == registry.get(PlatformType.CLAUDE_CODE)
    assert registry.get("Claude Code") == registry.get(PlatformType.CLAUDE_CODE)
    assert registry.get_by_cli_flag("codex") == registry.get(PlatformType.CODEX)
    assert registry.get("unknown-platform") is None


def test_registry_filtering_helpers() -> None:
    registry = PlatformRegistry()

    hook_platforms = registry.list_with_capability("supports_hooks")
    assert hook_platforms
    assert all(platform.capabilities.supports_hooks for platform in hook_platforms)

    jsonl_platforms = registry.list_with_jsonl_support()
    assert any(platform.platform_type is PlatformType.CLAUDE_CODE for platform in jsonl_platforms)
    assert all(platform.capabilities.supports_jsonl_context for platform in jsonl_platforms)

    session_start_platforms = registry.list_with_hook(HookType.SESSION_START)
    assert session_start_platforms
    assert all(
        HookType.SESSION_START in platform.capabilities.supported_hooks
        for platform in session_start_platforms
    )


@pytest.mark.parametrize(
    ("platform_name", "marker"),
    [
        ("claude", ".claude/settings.json"),
        ("cursor", ".cursorrules"),
        ("codex", ".codex/config.yaml"),
        ("windsurf", ".windsurf/settings.json"),
        ("aider", ".aider.conf.yml"),
        ("continue", ".continue/config.json"),
        ("cline", ".cline/config.json"),
        ("zed", ".zed/settings.json"),
        ("copilot", ".github/copilot-instructions.md"),
        ("supermaven", ".supermaven/config.json"),
        ("cody", ".cody/config.json"),
        ("tabnine", ".tabnine/config.json"),
        ("amazon-q", ".amazonq/settings.json"),
        ("pieces", ".pieces/config.json"),
    ],
)
def test_platform_detection_by_marker(tmp_path: Path, platform_name: str, marker: str) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    marker_path = repo_root / marker
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text("configured\n", encoding="utf-8")

    detected = detect_platform(repo_root)
    assert detected is not None
    assert detected == get_platform(platform_name)

    detected_all = detect_platforms(repo_root)
    assert detected_all
    assert detected_all[0] == detected


def test_detect_platform_prefers_higher_signal_match(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    (repo_root / ".cursor").mkdir()
    (repo_root / ".claude" / "hooks").mkdir(parents=True)
    (repo_root / ".claude" / "settings.json").write_text("{}", encoding="utf-8")

    detected = detect_platform(repo_root)
    assert detected is not None
    assert detected.platform_type is PlatformType.CLAUDE_CODE

    detected_all = detect_platforms(repo_root)
    assert [platform.platform_type for platform in detected_all[:2]] == [
        PlatformType.CLAUDE_CODE,
        PlatformType.CURSOR,
    ]


def test_detect_platform_returns_none_when_no_markers_exist(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    assert detect_platform(repo_root) is None
    assert detect_platforms(repo_root) == []


def test_local_and_global_registry_helpers_remain_usable() -> None:
    registry = PlatformRegistry()
    custom = PlatformConfig(
        platform_type=PlatformType.CUSTOM,
        name="Custom Platform",
        config_dir=".custom",
        template_dirs=("custom",),
        capabilities=PlatformCapabilities(supports_hooks=True),
        cli_flag="custom",
    )
    registry.register(custom)

    assert registry.get("custom") == custom
    assert any(platform.platform_type is PlatformType.CUSTOM for platform in registry.list_all())
    assert get_platform("claude") is not None
    assert len(list_platforms()) >= len(EXPECTED_BUILTINS)
