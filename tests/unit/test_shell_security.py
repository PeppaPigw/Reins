"""Tests for shell adapter security: exec-style invocation prevents shell injection."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from reins.execution.adapters.shell import (
    NetworkShellAdapter,
    SandboxedShellAdapter,
)


@pytest.fixture
def sandboxed_adapter():
    return SandboxedShellAdapter()


@pytest.fixture
def network_adapter():
    return NetworkShellAdapter()


@pytest.mark.asyncio
async def test_sandboxed_adapter_uses_create_subprocess_exec(sandboxed_adapter):
    """SandboxedShellAdapter.exec() must call create_subprocess_exec, not shell."""
    handle = await sandboxed_adapter.open({"cwd": "/tmp"})

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"out", b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        obs = await sandboxed_adapter.exec(handle, {"cmd": "echo hello"})
        mock_exec.assert_called_once()
        # First positional args should be the split command
        call_args = mock_exec.call_args
        assert call_args[0] == ("echo", "hello")


@pytest.mark.asyncio
async def test_network_adapter_uses_create_subprocess_exec(network_adapter):
    """NetworkShellAdapter.exec() must call create_subprocess_exec, not shell."""
    handle = await network_adapter.open({"cwd": "/tmp"})

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"out", b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        obs = await network_adapter.exec(handle, {"cmd": "ls -la /tmp"})
        mock_exec.assert_called_once()
        call_args = mock_exec.call_args
        assert call_args[0] == ("ls", "-la", "/tmp")


@pytest.mark.asyncio
async def test_shlex_split_for_string_commands(sandboxed_adapter):
    """String commands are split via shlex before exec."""
    handle = await sandboxed_adapter.open({"cwd": "/tmp"})

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await sandboxed_adapter.exec(handle, {"cmd": "git commit -m 'hello world'"})
        call_args = mock_exec.call_args
        # shlex.split handles quoted strings correctly
        assert call_args[0] == ("git", "commit", "-m", "hello world")


@pytest.mark.asyncio
async def test_list_commands_pass_through_unchanged(sandboxed_adapter):
    """List commands bypass shlex.split and pass through directly."""
    handle = await sandboxed_adapter.open({"cwd": "/tmp"})

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await sandboxed_adapter.exec(handle, {"cmd": ["git", "log", "--oneline"]})
        call_args = mock_exec.call_args
        assert call_args[0] == ("git", "log", "--oneline")


@pytest.mark.asyncio
async def test_effect_descriptor_includes_exec_style(sandboxed_adapter):
    """Effect descriptor must include exec_style: True."""
    handle = await sandboxed_adapter.open({"cwd": "/tmp"})

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"out", b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        obs = await sandboxed_adapter.exec(handle, {"cmd": "echo hi"})
        assert obs.effect_descriptor["exec_style"] is True


@pytest.mark.asyncio
async def test_network_effect_descriptor_includes_exec_style(network_adapter):
    """NetworkShellAdapter effect descriptor must include exec_style: True."""
    handle = await network_adapter.open({"cwd": "/tmp"})

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"out", b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        obs = await network_adapter.exec(handle, {"cmd": "curl http://example.com"})
        assert obs.effect_descriptor["exec_style"] is True


def test_no_create_subprocess_shell_in_shell_adapter():
    """Grep-based: shell.py must not contain create_subprocess_shell."""
    shell_path = Path(__file__).parent.parent.parent / "src" / "reins" / "execution" / "adapters" / "shell.py"
    content = shell_path.read_text()
    assert "create_subprocess_shell" not in content, (
        "shell.py still contains create_subprocess_shell — shell injection risk"
    )


def test_no_create_subprocess_shell_in_worktree_manager():
    """Grep-based: worktree_manager.py must not contain create_subprocess_shell."""
    wt_path = Path(__file__).parent.parent.parent / "src" / "reins" / "isolation" / "worktree_manager.py"
    content = wt_path.read_text()
    assert "create_subprocess_shell" not in content, (
        "worktree_manager.py still contains create_subprocess_shell — shell injection risk"
    )
