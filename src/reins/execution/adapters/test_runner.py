"""Test runner adapter — runs tests through the handle-based lifecycle.

Supports running pytest (default), arbitrary test commands, and
collecting structured pass/fail/skip results for the evaluator.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ulid

from reins.execution.adapter import Adapter, Handle, Observation
from reins.kernel.types import ArtifactRef


class TestRunnerAdapter(Adapter):
    """Runs test suites and returns structured results."""

    async def open(self, spec: dict) -> Handle:
        root = spec.get("root", ".")
        return Handle(
            adapter_kind="test",
            adapter_id="pytest",
            metadata={"root": str(root), "framework": spec.get("framework", "pytest")},
        )

    async def exec(self, handle: Handle, command: dict) -> Observation:
        op = command.get("op", "run")
        if op == "run":
            return await self._run_tests(handle, command)
        if op == "list":
            return await self._list_tests(handle, command)
        return Observation(stdout="", stderr=f"unknown op: {op}", exit_code=1)

    async def _run_tests(self, handle: Handle, command: dict) -> Observation:
        root = handle.metadata.get("root", ".")
        target = command.get("target", "tests/")
        extra_args = command.get("args", [])
        framework = handle.metadata.get("framework", "pytest")

        if framework == "pytest":
            cmd = ["python", "-m", "pytest", target, "-v", "--tb=short"]
            cmd.extend(extra_args)
        else:
            cmd = command.get("cmd", ["python", "-m", "pytest", target, "-v"])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=root,
        )
        stdout_b, stderr_b = await proc.communicate()
        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")

        return Observation(
            stdout=stdout,
            stderr=stderr,
            exit_code=proc.returncode or 0,
            effect_descriptor={"op": "test.run", "target": target},
        )

    async def _list_tests(self, handle: Handle, command: dict) -> Observation:
        root = handle.metadata.get("root", ".")
        target = command.get("target", "tests/")
        proc = await asyncio.create_subprocess_exec(
            "python", "-m", "pytest", target, "--collect-only", "-q",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=root,
        )
        stdout_b, stderr_b = await proc.communicate()
        return Observation(
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
            exit_code=proc.returncode or 0,
        )

    async def snapshot(self, handle: Handle) -> str:
        return f"test-runner:{handle.metadata.get('framework')}@{handle.metadata.get('root')}"

    async def freeze(self, handle: Handle) -> dict:
        return {"adapter_kind": "test", "metadata": handle.metadata}

    async def thaw(self, frozen: dict) -> Handle:
        return Handle(
            adapter_kind="test",
            adapter_id="pytest",
            metadata=frozen.get("metadata", {}),
        )

    async def reset(self, handle: Handle) -> Handle:
        return handle  # stateless — nothing to reset

    async def close(self, handle: Handle) -> None:
        pass  # stateless
