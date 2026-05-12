"""Full integration tests for Tier 1 platforms (Claude, Cursor, Codex)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from reins.platform.configurator import get_configurator
from reins.platform.contracts import validate_platform
from reins.platform.engine import DescriptorEngine
from reins.platform.hooks.templates import (
    generate_all_hooks,
    get_hooks_for_platform,
)
from reins.platform.registry import get_platform
from reins.platform.template_hash import TemplateHashStore
from reins.platform.types import PlatformType


class TestClaudeCodeFullCycle:
    """Full lifecycle tests for Claude Code platform."""

    def test_init_creates_all_expected_files(self, tmp_path: Path) -> None:
        configurator = get_configurator(PlatformType.CLAUDE_CODE, tmp_path)
        configurator.configure(
            variables={"developer": "test", "project_type": "backend"}
        )
        config_path = tmp_path / ".claude"
        assert config_path.exists()
        assert (config_path / "hooks").is_dir()
        assert (config_path / "agents").is_dir()
        assert (config_path / "commands").is_dir()
        assert (config_path / "settings.json").is_file()

    def test_settings_json_is_valid(self, tmp_path: Path) -> None:
        configurator = get_configurator(PlatformType.CLAUDE_CODE, tmp_path)
        configurator.configure(
            variables={"developer": "test", "project_type": "backend"}
        )
        settings = json.loads(
            (tmp_path / ".claude" / "settings.json").read_text(
                encoding="utf-8"
            )
        )
        assert isinstance(settings, dict)
        assert "hooks" in settings
    def test_hooks_are_valid_python(self, tmp_path: Path) -> None:
        configurator = get_configurator(PlatformType.CLAUDE_CODE, tmp_path)
        configurator.configure(
            variables={"developer": "test", "project_type": "backend"}
        )
        hooks_dir = tmp_path / ".claude" / "hooks"
        assert hooks_dir.exists()
        py_files = list(hooks_dir.glob("*.py"))
        assert len(py_files) > 0
        for py_file in py_files:
            compile(py_file.read_text(encoding="utf-8"), str(py_file), "exec")

    def test_validate_passes_contract(self, tmp_path: Path) -> None:
        configurator = get_configurator(PlatformType.CLAUDE_CODE, tmp_path)
        configurator.configure(
            variables={"developer": "test", "project_type": "backend"}
        )
        config = get_platform(PlatformType.CLAUDE_CODE)
        assert config is not None
        violations = validate_platform(config, tmp_path)
        assert violations == []

    def test_staleness_detection_fresh(self, tmp_path: Path) -> None:
        configurator = get_configurator(PlatformType.CLAUDE_CODE, tmp_path)
        configurator.configure(
            variables={"developer": "test", "project_type": "backend"}
        )
        config = get_platform(PlatformType.CLAUDE_CODE)
        assert config is not None
        engine = DescriptorEngine(tmp_path)
        stale = engine.check_staleness(config)
        # Fresh install should have no stale files
        stale_only = [(p, s) for p, s in stale if s == "stale"]
        assert stale_only == []

    def test_customization_detected(self, tmp_path: Path) -> None:
        configurator = get_configurator(PlatformType.CLAUDE_CODE, tmp_path)
        configurator.configure(
            variables={"developer": "test", "project_type": "backend"}
        )
        # Modify settings.json (user customization)
        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.write_text('{"custom": true}', encoding="utf-8")
        config = get_platform(PlatformType.CLAUDE_CODE)
        assert config is not None
        engine = DescriptorEngine(tmp_path)
        stale = engine.check_staleness(config)
        customized = [(p, s) for p, s in stale if s == "customized"]
        # Should detect the customization since hash store was populated
        assert len(customized) > 0

    def test_hook_generation_produces_valid_scripts(
        self, tmp_path: Path
    ) -> None:
        hooks = generate_all_hooks(
            PlatformType.CLAUDE_CODE, {"repo_root": str(tmp_path)}
        )
        assert len(hooks) > 0
        for filename, content in hooks.items():
            assert filename.endswith(".py")
            compile(content, filename, "exec")

class TestCursorFullCycle:
    """Full lifecycle tests for Cursor platform."""

    def test_init_creates_expected_files(self, tmp_path: Path) -> None:
        configurator = get_configurator(PlatformType.CURSOR, tmp_path)
        configurator.configure(
            variables={"developer": "test", "project_type": "backend"}
        )
        config_path = tmp_path / ".cursor"
        assert config_path.exists()
        assert (config_path / "settings.json").is_file()
        # .cursorrules lives at repo root for Cursor
        assert (tmp_path / ".cursorrules").is_file()

    def test_validate_passes_contract(self, tmp_path: Path) -> None:
        configurator = get_configurator(PlatformType.CURSOR, tmp_path)
        configurator.configure(
            variables={"developer": "test", "project_type": "backend"}
        )
        config = get_platform(PlatformType.CURSOR)
        assert config is not None
        violations = validate_platform(config, tmp_path)
        assert violations == []

    def test_no_hooks_for_cursor(self, tmp_path: Path) -> None:
        hooks = get_hooks_for_platform(PlatformType.CURSOR)
        assert hooks == []

    def test_cursorrules_has_content(self, tmp_path: Path) -> None:
        configurator = get_configurator(PlatformType.CURSOR, tmp_path)
        configurator.configure(
            variables={"developer": "test", "project_type": "backend"}
        )
        rules_path = tmp_path / ".cursorrules"
        assert rules_path.exists()
        content = rules_path.read_text(encoding="utf-8")
        assert len(content) > 0
        assert "test" in content  # developer variable rendered

    def test_settings_json_is_valid(self, tmp_path: Path) -> None:
        configurator = get_configurator(PlatformType.CURSOR, tmp_path)
        configurator.configure(
            variables={"developer": "test", "project_type": "backend"}
        )
        settings = json.loads(
            (tmp_path / ".cursor" / "settings.json").read_text(
                encoding="utf-8"
            )
        )
        assert isinstance(settings, dict)

class TestCodexFullCycle:
    """Full lifecycle tests for Codex platform."""

    def test_init_creates_expected_files(self, tmp_path: Path) -> None:
        configurator = get_configurator(PlatformType.CODEX, tmp_path)
        configurator.configure(
            variables={"developer": "test", "project_type": "backend"}
        )
        config_path = tmp_path / ".codex"
        assert config_path.exists()
        assert (config_path / "config.yaml").is_file()
        assert (config_path / "agents").is_dir()
        assert (config_path / "hooks").is_dir()

    def test_config_yaml_is_valid(self, tmp_path: Path) -> None:
        configurator = get_configurator(PlatformType.CODEX, tmp_path)
        configurator.configure(
            variables={"developer": "test", "project_type": "backend"}
        )
        config_content = (
            tmp_path / ".codex" / "config.yaml"
        ).read_text(encoding="utf-8")
        parsed = yaml.safe_load(config_content)
        assert isinstance(parsed, dict)
        assert "platform" in parsed

    def test_validate_passes_contract(self, tmp_path: Path) -> None:
        configurator = get_configurator(PlatformType.CODEX, tmp_path)
        configurator.configure(
            variables={"developer": "test", "project_type": "backend"}
        )
        config = get_platform(PlatformType.CODEX)
        assert config is not None
        violations = validate_platform(config, tmp_path)
        assert violations == []

    def test_hooks_dir_exists(self, tmp_path: Path) -> None:
        configurator = get_configurator(PlatformType.CODEX, tmp_path)
        configurator.configure(
            variables={"developer": "test", "project_type": "backend"}
        )
        hooks_dir = tmp_path / ".codex" / "hooks"
        assert hooks_dir.is_dir()

    def test_mcp_json_is_valid(self, tmp_path: Path) -> None:
        configurator = get_configurator(PlatformType.CODEX, tmp_path)
        configurator.configure(
            variables={"developer": "test", "project_type": "backend"}
        )
        mcp_path = tmp_path / ".codex" / "mcp.json"
        assert mcp_path.exists()
        parsed = json.loads(mcp_path.read_text(encoding="utf-8"))
        assert isinstance(parsed, dict)

    def test_hook_generation_produces_valid_scripts(
        self, tmp_path: Path
    ) -> None:
        hooks = generate_all_hooks(
            PlatformType.CODEX, {"repo_root": str(tmp_path)}
        )
        assert len(hooks) > 0
        for filename, content in hooks.items():
            assert filename.endswith(".py")
            compile(content, filename, "exec")



