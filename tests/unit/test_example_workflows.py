from __future__ import annotations

from pathlib import Path

from reins.orchestration.pipeline import load_pipeline_from_yaml, validate_pipeline


def test_example_workflows_load_and_validate() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    workflows_dir = repo_root / "examples" / "workflows"
    expected = {
        "code-review.yaml",
        "docs-generation.yaml",
        "refactoring.yaml",
        "migration.yaml",
    }

    discovered = {path.name for path in workflows_dir.glob("*.yaml")}
    assert expected == discovered

    for name in sorted(expected):
        pipeline = load_pipeline_from_yaml(workflows_dir / name)
        assert validate_pipeline(pipeline) == []
        assert any(stage.model for stage in pipeline.stages)


def test_migration_workflow_has_parallel_batches() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    migration = load_pipeline_from_yaml(repo_root / "examples" / "workflows" / "migration.yaml")
    dependency_map = {stage.name: tuple(stage.depends_on) for stage in migration.stages}

    assert dependency_map["migrate-batch-1"] == ("mapping",)
    assert dependency_map["migrate-batch-2"] == ("mapping",)
    assert set(dependency_map["verify"]) == {"migrate-batch-1", "migrate-batch-2"}
