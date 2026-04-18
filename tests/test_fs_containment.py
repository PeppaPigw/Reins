"""Tests for filesystem adapter path containment security."""

import pytest
from pathlib import Path

from reins.execution.adapters.fs import FilesystemAdapter


@pytest.mark.asyncio
async def test_path_escape_blocked(tmp_path):
    """Path escape attempts should be blocked."""
    adapter = FilesystemAdapter()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Create a file outside workspace
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")

    handle = await adapter.open({"root": str(workspace)})

    # Try to read outside workspace using ../
    result = await adapter.exec(handle, {"op": "read", "path": "../outside.txt"})
    assert result.exit_code != 0
    assert "path escape" in result.stderr

    # Try absolute path
    result = await adapter.exec(handle, {"op": "read", "path": str(outside)})
    assert result.exit_code != 0
    assert "path escape" in result.stderr

    await adapter.close(handle)


@pytest.mark.asyncio
async def test_valid_paths_allowed(tmp_path):
    """Valid paths within workspace should work."""
    adapter = FilesystemAdapter()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    handle = await adapter.open({"root": str(workspace)})

    # Write to valid path
    result = await adapter.exec(
        handle, {"op": "write", "path": "test.txt", "content": "hello"}
    )
    assert result.exit_code == 0

    # Read from valid path
    result = await adapter.exec(handle, {"op": "read", "path": "test.txt"})
    assert result.exit_code == 0
    assert result.stdout == "hello"

    # Subdirectory is OK
    result = await adapter.exec(
        handle, {"op": "write", "path": "sub/file.txt", "content": "world"}
    )
    assert result.exit_code == 0

    await adapter.close(handle)


@pytest.mark.asyncio
async def test_move_path_escape_blocked(tmp_path):
    """Move operation should also check destination path."""
    adapter = FilesystemAdapter()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    handle = await adapter.open({"root": str(workspace)})

    # Create a file in workspace
    result = await adapter.exec(
        handle, {"op": "write", "path": "test.txt", "content": "data"}
    )
    assert result.exit_code == 0

    # Try to move outside workspace
    result = await adapter.exec(
        handle, {"op": "move", "path": "test.txt", "dest": "../outside.txt"}
    )
    assert result.exit_code != 0
    assert "path escape" in result.stderr

    await adapter.close(handle)
