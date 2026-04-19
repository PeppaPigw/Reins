from __future__ import annotations

from pathlib import Path

import pytest

from reins.orchestration.pipeline import (
    Pipeline,
    PipelineStage,
    StageType,
    load_pipeline_from_yaml,
    validate_pipeline,
)


def test_load_pipeline_from_yaml(tmp_path: Path) -> None:
    pipeline_path = tmp_path / "pipeline.yaml"
    pipeline_path.write_text(
        """
name: example
description: Example pipeline
metadata:
  owner: orchestration
stages:
  - name: research
    type: research
    agent_type: research
    prompt_template: "Research {task_goal}"
    timeout_seconds: 100
""".strip()
        + "\n",
        encoding="utf-8",
    )

    pipeline = load_pipeline_from_yaml(pipeline_path)

    assert pipeline.name == "example"
    assert pipeline.metadata == {"owner": "orchestration"}
    assert len(pipeline.stages) == 1
    assert pipeline.stages[0].type is StageType.RESEARCH
    assert pipeline.stages[0].timeout_seconds == 100


def test_pipeline_stage_render_prompt_requires_known_variables() -> None:
    stage = PipelineStage(
        name="research",
        type=StageType.RESEARCH,
        agent_type="research",
        prompt_template="Investigate {task_goal}",
    )

    assert stage.render_prompt({"task_goal": "auth"}) == "Investigate auth"

    with pytest.raises(KeyError, match="task_goal"):
        stage.render_prompt({})


def test_validate_pipeline_detects_duplicate_unknown_and_self_dependency() -> None:
    pipeline = Pipeline(
        name="bad",
        description="Broken pipeline",
        stages=[
            PipelineStage(
                name="research",
                type=StageType.RESEARCH,
                agent_type="research",
                prompt_template="one",
            ),
            PipelineStage(
                name="research",
                type=StageType.CHECK,
                agent_type="check",
                prompt_template="two",
                depends_on=["research", "missing"],
            ),
        ],
    )

    errors = validate_pipeline(pipeline)

    assert "Duplicate stage name: research" in errors
    assert "Stage 'research' cannot depend on itself." in errors
    assert "Stage 'research' depends on unknown stage 'missing'." in errors


def test_validate_pipeline_detects_cycle() -> None:
    pipeline = Pipeline(
        name="cycle",
        description="Cycle pipeline",
        stages=[
            PipelineStage(
                name="research",
                type=StageType.RESEARCH,
                agent_type="research",
                prompt_template="research",
                depends_on=["verify"],
            ),
            PipelineStage(
                name="verify",
                type=StageType.VERIFY,
                agent_type="verify",
                prompt_template="verify",
                depends_on=["research"],
            ),
        ],
    )

    errors = validate_pipeline(pipeline)

    assert errors == ["Circular dependency detected: research -> verify -> research"]


def test_bundled_pipeline_templates_load_and_validate() -> None:
    pipeline_dir = Path(__file__).resolve().parents[2] / ".reins" / "pipelines"
    expected = {"standard.yaml", "research-heavy.yaml", "test-driven.yaml", "debug.yaml"}

    discovered = {path.name for path in pipeline_dir.glob("*.yaml")}
    assert expected.issubset(discovered)

    for name in sorted(expected):
        pipeline = load_pipeline_from_yaml(pipeline_dir / name)
        assert validate_pipeline(pipeline) == []
