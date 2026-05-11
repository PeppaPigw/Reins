"""Integration tests for CI matrix validation.

Validates Python version compatibility, platform compatibility,
and dependency availability to ensure CI matrix correctness.
"""

from __future__ import annotations

import asyncio
import os
import platform
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# TestPythonVersionCompatibility
# ---------------------------------------------------------------------------


class TestPythonVersionCompatibility:
    """Verify Python 3.11+ features are available."""

    def test_python_version_at_least_311(self):
        assert sys.version_info >= (3, 11)

    def test_async_features_available(self):
        """TaskGroup is available (3.11+)."""
        assert hasattr(asyncio, "TaskGroup")

    def test_tomllib_available(self):
        """tomllib is in stdlib since 3.11."""
        import tomllib  # noqa: F401

    def test_exception_groups_available(self):
        """ExceptionGroup works (3.11+)."""
        try:
            raise ExceptionGroup("test", [ValueError("a"), TypeError("b")])
        except ExceptionGroup as eg:
            assert len(eg.exceptions) == 2

    def test_type_union_syntax(self):
        """int | str annotation works at runtime."""
        union = int | str
        assert int in union.__args__
        assert str in union.__args__


# ---------------------------------------------------------------------------
# TestPlatformCompatibility
# ---------------------------------------------------------------------------


class TestPlatformCompatibility:
    """Verify cross-platform operations work correctly."""

    def test_path_operations_cross_platform(self, tmp_path: Path):
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        assert nested.exists()
        assert nested.is_dir()

    def test_subprocess_execution(self):
        """git --version succeeds via subprocess."""
        result = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "git version" in result.stdout

    def test_temp_directory_creation(self):
        with tempfile.TemporaryDirectory(prefix="reins_ci_") as tmpdir:
            p = Path(tmpdir) / "test.txt"
            p.write_text("hello", encoding="utf-8")
            assert p.read_text(encoding="utf-8") == "hello"

    def test_file_permissions(self, tmp_path: Path):
        f = tmp_path / "perm_test.txt"
        f.write_text("data", encoding="utf-8")
        if platform.system() != "Windows":
            st = f.stat()
            # Owner should have read/write
            assert st.st_mode & stat.S_IRUSR
            assert st.st_mode & stat.S_IWUSR

    @pytest.mark.asyncio
    async def test_async_subprocess(self):
        """asyncio.create_subprocess_exec works on current platform."""
        proc = await asyncio.create_subprocess_exec(
            "git", "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        assert proc.returncode == 0
        assert b"git version" in stdout


# ---------------------------------------------------------------------------
# TestDependencyAvailability
# ---------------------------------------------------------------------------


class TestDependencyAvailability:
    """Verify all required packages are importable."""

    def test_all_required_packages_importable(self):
        import pydantic  # noqa: F401
        import aiohttp  # noqa: F401
        import typer  # noqa: F401
        import structlog  # noqa: F401
        import yaml  # noqa: F401
        import aiofiles  # noqa: F401
        import rich  # noqa: F401

    def test_hypothesis_available(self):
        import hypothesis
        version_parts = hypothesis.__version__.split(".")
        major = int(version_parts[0])
        assert major >= 6

    def test_pytest_plugins_loaded(self):
        import pytest_asyncio  # noqa: F401
