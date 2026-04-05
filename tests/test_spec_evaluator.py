"""Tests for the spec evaluator — structural compliance checker."""

import pytest

from reins.evaluation.evaluators.spec import SpecEvaluator


@pytest.mark.asyncio
async def test_spec_evaluator_passes_on_valid_codebase():
    """Run spec evaluator against the live Reins codebase."""
    evaluator = SpecEvaluator()
    result = await evaluator.evaluate({
        "cwd": ".",
        "run_id": "spec-test-1",
    })
    assert result.passed, f"Spec violations: {result.details}"
    assert result.evaluator_kind == "spec"
    assert result.score == 1.0


@pytest.mark.asyncio
async def test_spec_evaluator_detects_missing_modules(tmp_path):
    """Spec evaluator should fail when required modules are absent."""
    evaluator = SpecEvaluator()
    result = await evaluator.evaluate({
        "cwd": str(tmp_path),
        "run_id": "spec-test-2",
    })
    assert not result.passed
    assert "missing required module" in result.details


@pytest.mark.asyncio
async def test_spec_evaluator_detects_impure_reducer(tmp_path):
    """Spec evaluator should flag a reducer that imports I/O modules."""
    # Create a fake reducer with I/O import
    reducer_dir = tmp_path / "src" / "reins" / "kernel" / "reducer"
    reducer_dir.mkdir(parents=True)
    (reducer_dir / "reducer.py").write_text(
        "import asyncio\ndef reduce(s, e): return s\n"
    )
    # Also create required files to avoid masking the reducer violation
    (tmp_path / "src" / "reins" / "kernel" / "types.py").touch()
    (tmp_path / "src" / "reins" / "kernel" / "event").mkdir(parents=True)
    (tmp_path / "src" / "reins" / "kernel" / "event" / "envelope.py").touch()
    (tmp_path / "src" / "reins" / "kernel" / "event" / "journal.py").touch()
    (tmp_path / "src" / "reins" / "kernel" / "routing").mkdir(parents=True)
    (tmp_path / "src" / "reins" / "kernel" / "routing" / "router.py").touch()
    (tmp_path / "src" / "reins" / "policy").mkdir(parents=True)
    (tmp_path / "src" / "reins" / "policy" / "engine.py").touch()
    state = reducer_dir / "state.py"
    state.touch()

    evaluator = SpecEvaluator()
    result = await evaluator.evaluate({
        "cwd": str(tmp_path),
        "run_id": "spec-test-3",
    })
    assert not result.passed
    assert "reducer imports I/O module" in result.details
