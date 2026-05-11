"""Tests for version management module."""

from __future__ import annotations

from pathlib import Path

from reins.packaging.version import BumpType, VersionInfo, VersionManager


SAMPLE_PYPROJECT = """\
[project]
name = "test-project"
version = "1.2.3"
description = "A test project"
"""


def test_version_info_parse_simple():
    v = VersionInfo.parse("1.2.3")
    assert v.major == 1
    assert v.minor == 2
    assert v.patch == 3
    assert v.prerelease is None
    assert v.build_metadata is None


def test_version_info_parse_prerelease():
    v = VersionInfo.parse("2.0.0-alpha.1")
    assert v.major == 2
    assert v.minor == 0
    assert v.patch == 0
    assert v.prerelease == "alpha.1"


def test_version_info_parse_with_build_metadata():
    v = VersionInfo.parse("1.0.0+build.42")
    assert v.major == 1
    assert v.build_metadata == "build.42"


def test_version_info_str_roundtrip():
    cases = ["1.2.3", "0.0.1", "2.0.0-beta.1", "3.1.4-rc.2+build.99"]
    for case in cases:
        assert str(VersionInfo.parse(case)) == case


def test_version_info_parse_with_v_prefix():
    v = VersionInfo.parse("v1.5.0")
    assert v.major == 1
    assert v.minor == 5
    assert v.patch == 0


def test_bump_major():
    v = VersionInfo(major=1, minor=2, patch=3)
    bumped = v.bump(BumpType.major)
    assert bumped == VersionInfo(major=2, minor=0, patch=0)


def test_bump_minor():
    v = VersionInfo(major=1, minor=2, patch=3)
    bumped = v.bump(BumpType.minor)
    assert bumped == VersionInfo(major=1, minor=3, patch=0)


def test_bump_patch():
    v = VersionInfo(major=1, minor=2, patch=3)
    bumped = v.bump(BumpType.patch)
    assert bumped == VersionInfo(major=1, minor=2, patch=4)


def test_version_comparison_operators():
    v1 = VersionInfo.parse("1.0.0")
    v2 = VersionInfo.parse("1.1.0")
    v3 = VersionInfo.parse("2.0.0")
    v4 = VersionInfo.parse("1.0.0-alpha.1")

    assert v1 < v2
    assert v2 < v3
    assert v1 <= v1
    assert v3 > v2
    assert v3 >= v3
    assert v1 == VersionInfo.parse("1.0.0")
    # Prerelease has lower precedence than release
    assert v4 < v1


def test_version_manager_get_current(tmp_path: Path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(SAMPLE_PYPROJECT)
    manager = VersionManager(pyproject)
    version = manager.get_current_version()
    assert version == VersionInfo(major=1, minor=2, patch=3)


def test_version_manager_set_version(tmp_path: Path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(SAMPLE_PYPROJECT)
    manager = VersionManager(pyproject)
    new_version = VersionInfo(major=2, minor=0, patch=0)
    manager.set_version(new_version)
    content = pyproject.read_text()
    assert 'version = "2.0.0"' in content


def test_version_manager_bump(tmp_path: Path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(SAMPLE_PYPROJECT)
    manager = VersionManager(pyproject)
    new_version = manager.bump_version(BumpType.minor)
    assert new_version == VersionInfo(major=1, minor=3, patch=0)
    # Verify it was persisted
    assert manager.get_current_version() == new_version


def test_get_version_tag(tmp_path: Path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(SAMPLE_PYPROJECT)
    manager = VersionManager(pyproject)
    assert manager.get_version_tag() == "v1.2.3"
    custom = VersionInfo(major=3, minor=0, patch=0, prerelease="rc.1")
    assert manager.get_version_tag(custom) == "v3.0.0-rc.1"
