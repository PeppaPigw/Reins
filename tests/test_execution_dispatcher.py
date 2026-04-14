from __future__ import annotations

import pytest

from reins.execution.dispatcher import ExecutionDispatcher
from reins.kernel.intent.envelope import CommandEnvelope
from reins.kernel.types import RiskTier


async def _build_command(kind: str, args: dict) -> CommandEnvelope:
    return CommandEnvelope(
        run_id="run-dispatch",
        normalized_kind=kind,
        args=args,
        policy_scope={},
        risk_tier=RiskTier.T1,
    )


@pytest.mark.asyncio
async def test_dispatcher_routes_fs_read_through_filesystem_adapter(tmp_path):
    dispatcher = ExecutionDispatcher()
    target = tmp_path / "demo.txt"
    target.write_text("dispatcher\n", encoding="utf-8")

    first = await dispatcher.dispatch(
        "run-dispatch",
        await _build_command(
            "fs.read",
            {"root": str(tmp_path), "path": "demo.txt"},
        ),
    )
    second = await dispatcher.dispatch(
        "run-dispatch",
        await _build_command(
            "fs.read",
            {"root": str(tmp_path), "path": "demo.txt"},
        ),
    )

    assert first.observation.stdout == "dispatcher\n"
    assert first.handle_ref.adapter_kind == "fs"
    assert first.opened_new_handle is True
    assert second.opened_new_handle is False
    assert second.handle_ref.handle_id == first.handle_ref.handle_id


@pytest.mark.asyncio
async def test_dispatcher_routes_test_run_through_test_runner(tmp_path):
    dispatcher = ExecutionDispatcher()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_sample.py").write_text(
        "def test_sample():\n    assert 1 + 1 == 2\n",
        encoding="utf-8",
    )

    result = await dispatcher.dispatch(
        "run-dispatch",
        await _build_command(
            "test.run",
            {"root": str(tmp_path), "target": "tests"},
        ),
    )

    assert result.handle_ref.adapter_kind == "test"
    assert result.observation.exit_code == 0
    assert "1 passed" in result.observation.stdout
