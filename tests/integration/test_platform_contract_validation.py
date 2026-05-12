"""Integration tests for platform contract validation across all 14 platforms."""

from __future__ import annotations

from pathlib import Path

import pytest

from reins.platform.configurator import get_configurator
from reins.platform.contracts import (
    PLATFORM_CONTRACTS,
    ContractViolation,
    validate_all,
    validate_platform,
)
from reins.platform.descriptors import PLATFORM_DESCRIPTORS
from reins.platform.engine import DescriptorEngine
from reins.platform.registry import get_platform
from reins.platform.types import PlatformType

ALL_REAL_PLATFORMS = [pt for pt in PlatformType if pt != PlatformType.CUSTOM]


class TestAllPlatformContracts:
    """Verify every non-CUSTOM platform passes contract after configure()."""

    @pytest.mark.parametrize("platform_type", ALL_REAL_PLATFORMS)
    def test_platform_passes_contract_after_configure(
        self, platform_type: PlatformType, tmp_path: Path
    ) -> None:
        config = get_platform(platform_type)
        assert config is not None, f"No config for {platform_type.value}"
        configurator = get_configurator(platform_type, tmp_path)
        configurator.configure(
            variables={"developer": "test", "project_type": "backend"}
        )
        violations = validate_platform(config, tmp_path)
        assert violations == [], (
            f"Violations for {platform_type.value}: "
            f"{[(v.path, v.rule, v.detail) for v in violations]}"
        )

    def test_all_platforms_have_contracts(self) -> None:
        for pt in ALL_REAL_PLATFORMS:
            assert pt in PLATFORM_CONTRACTS, (
                f"Missing contract for {pt.value}"
            )

    def test_all_platforms_have_descriptors(self) -> None:
        for pt in ALL_REAL_PLATFORMS:
            assert pt in PLATFORM_DESCRIPTORS, (
                f"Missing descriptor for {pt.value}"
            )

class TestContractViolationDetection:
    """Verify that contract validation detects actual violations."""

    def test_missing_config_dir_detected(self, tmp_path: Path) -> None:
        config = get_platform(PlatformType.CLAUDE_CODE)
        assert config is not None
        # Don't create anything — config dir is missing
        violations = validate_platform(config, tmp_path)
        assert len(violations) > 0
        assert any(v.rule == "config_dir_exists" for v in violations)

    def test_missing_required_path_detected(self, tmp_path: Path) -> None:
        config = get_platform(PlatformType.CLAUDE_CODE)
        assert config is not None
        config_path = tmp_path / config.config_dir
        config_path.mkdir(parents=True)
        # Create settings.json but skip hooks/, agents/, commands/
        (config_path / "settings.json").write_text(
            '{"hooks": {}}', encoding="utf-8"
        )
        violations = validate_platform(config, tmp_path)
        assert len(violations) > 0
        assert any(
            v.rule == "required_path_exists" for v in violations
        )

    def test_missing_required_content_detected(self, tmp_path: Path) -> None:
        config = get_platform(PlatformType.CLAUDE_CODE)
        assert config is not None
        config_path = tmp_path / config.config_dir
        config_path.mkdir(parents=True)
        (config_path / "hooks").mkdir()
        (config_path / "agents").mkdir()
        (config_path / "commands").mkdir()
        # settings.json without "hooks" content
        (config_path / "settings.json").write_text(
            '{"other": true}', encoding="utf-8"
        )
        violations = validate_platform(config, tmp_path)
        assert len(violations) > 0
        assert any(v.rule == "required_content" for v in violations)

    def test_no_violations_for_valid_setup(self, tmp_path: Path) -> None:
        config = get_platform(PlatformType.CLAUDE_CODE)
        assert config is not None
        configurator = get_configurator(PlatformType.CLAUDE_CODE, tmp_path)
        configurator.configure(
            variables={"developer": "test", "project_type": "backend"}
        )
        violations = validate_platform(config, tmp_path)
        assert violations == []


class TestDescriptorEngineIntegration:
    """Verify DescriptorEngine generates valid configs that pass contracts."""

    def test_engine_generates_valid_claude_config(
        self, tmp_path: Path
    ) -> None:
        config = get_platform(PlatformType.CLAUDE_CODE)
        assert config is not None
        engine = DescriptorEngine(tmp_path)
        engine.generate(
            config,
            variables={"developer": "test", "project_type": "backend"},
        )
        violations = validate_platform(config, tmp_path)
        assert violations == []

    def test_engine_generates_valid_generic_platform(
        self, tmp_path: Path
    ) -> None:
        config = get_platform(PlatformType.WINDSURF)
        assert config is not None
        engine = DescriptorEngine(tmp_path)
        engine.generate(config)
        violations = validate_platform(config, tmp_path)
        assert violations == []

    def test_validate_all_does_not_crash(self, tmp_path: Path) -> None:
        # Configure Claude and Cursor in tmp_path
        configurator = get_configurator(PlatformType.CLAUDE_CODE, tmp_path)
        configurator.configure(
            variables={"developer": "test", "project_type": "backend"}
        )
        results = validate_all(tmp_path)
        # validate_all should return a dict and not crash
        assert isinstance(results, dict)

