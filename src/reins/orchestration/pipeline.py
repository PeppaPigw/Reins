"""Pipeline definitions and YAML loading for orchestration workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from string import Formatter
from typing import Any, Mapping

import yaml


class StageType(str, Enum):
    """Supported stage categories for pipeline execution."""

    RESEARCH = "research"
    IMPLEMENT = "implement"
    CHECK = "check"
    VERIFY = "verify"
    DEBUG = "debug"
    CUSTOM = "custom"


@dataclass
class PipelineStage:
    """One executable stage in a pipeline."""

    name: str
    type: StageType
    agent_type: str
    prompt_template: str
    model: str | None = None
    depends_on: list[str] = field(default_factory=list)
    timeout_seconds: int = 3600
    retry_on_failure: bool = True
    max_retries: int = 3
    context_files: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def render_prompt(self, variables: Mapping[str, Any] | None = None) -> str:
        """Render the stage prompt with the supplied variables."""
        variables = dict(variables or {})
        required = {
            field_name
            for _, field_name, _, _ in Formatter().parse(self.prompt_template)
            if field_name
        }
        missing = sorted(name for name in required if name not in variables)
        if missing:
            joined = ", ".join(missing)
            raise KeyError(f"Missing pipeline variables for stage {self.name!r}: {joined}")
        return self.prompt_template.format(**variables)


@dataclass
class Pipeline:
    """Declarative definition of a multi-stage workflow."""

    name: str
    description: str
    stages: list[PipelineStage]
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_stage(self, stage_name: str) -> PipelineStage:
        """Return a stage by name."""
        for stage in self.stages:
            if stage.name == stage_name:
                return stage
        raise KeyError(f"Unknown stage: {stage_name}")


def load_pipeline_from_yaml(path: Path) -> Pipeline:
    """Load a pipeline definition from a YAML file."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Pipeline file must contain a mapping: {path}")

    name = _require_str(raw, "name", path)
    description = _require_str(raw, "description", path)
    metadata = _optional_mapping(raw.get("metadata"), "metadata", path)

    raw_stages = raw.get("stages")
    if not isinstance(raw_stages, list):
        raise ValueError(f"Pipeline file must define a 'stages' list: {path}")

    stages = [
        _parse_stage(stage_raw, path=path, index=index)
        for index, stage_raw in enumerate(raw_stages, start=1)
    ]

    return Pipeline(
        name=name,
        description=description,
        stages=stages,
        metadata=metadata,
    )


class PipelineParser:
    """Compatibility wrapper for loading pipeline files."""

    def parse_file(self, path: Path) -> Pipeline:
        """Parse a pipeline definition from a YAML file."""
        return load_pipeline_from_yaml(path)


def validate_pipeline(pipeline: Pipeline) -> list[str]:
    """Validate pipeline structure and dependency relationships."""
    errors: list[str] = []
    if not pipeline.name.strip():
        errors.append("Pipeline name must not be empty.")
    if not pipeline.description.strip():
        errors.append("Pipeline description must not be empty.")
    if not pipeline.stages:
        errors.append("Pipeline must define at least one stage.")
        return errors

    stage_names = [stage.name for stage in pipeline.stages]
    known_names = set(stage_names)

    duplicates = sorted({name for name in stage_names if stage_names.count(name) > 1})
    for name in duplicates:
        errors.append(f"Duplicate stage name: {name}")

    for stage in pipeline.stages:
        if not stage.name.strip():
            errors.append("Stage name must not be empty.")
        if not stage.agent_type.strip():
            errors.append(f"Stage {stage.name!r} must define a non-empty agent_type.")
        if not stage.prompt_template.strip():
            errors.append(f"Stage {stage.name!r} must define a prompt_template.")
        if stage.model is not None and not stage.model.strip():
            errors.append(f"Stage {stage.name!r} model must not be empty when provided.")
        if stage.timeout_seconds <= 0:
            errors.append(f"Stage {stage.name!r} timeout_seconds must be > 0.")
        if stage.max_retries < 0:
            errors.append(f"Stage {stage.name!r} max_retries must be >= 0.")

        for dependency in stage.depends_on:
            if dependency == stage.name:
                errors.append(f"Stage {stage.name!r} cannot depend on itself.")
            elif dependency not in known_names:
                errors.append(
                    f"Stage {stage.name!r} depends on unknown stage {dependency!r}."
                )

    if errors:
        return errors

    cycle = _find_cycle(pipeline)
    if cycle:
        errors.append(f"Circular dependency detected: {' -> '.join(cycle)}")
    return errors


def _parse_stage(raw: Any, *, path: Path, index: int) -> PipelineStage:
    if not isinstance(raw, dict):
        raise ValueError(f"Stage #{index} in {path} must be a mapping.")

    raw_type = _require_str(raw, "type", path, index=index)
    try:
        stage_type = StageType(raw_type)
    except ValueError as exc:
        valid_values = ", ".join(stage.value for stage in StageType)
        raise ValueError(
            f"Invalid stage type {raw_type!r} in stage #{index} of {path}; "
            f"expected one of: {valid_values}"
        ) from exc

    depends_on = raw.get("depends_on", [])
    if not isinstance(depends_on, list) or any(not isinstance(item, str) for item in depends_on):
        raise ValueError(f"'depends_on' for stage #{index} in {path} must be a list of strings.")

    context_files = raw.get("context_files", [])
    if not isinstance(context_files, list) or any(
        not isinstance(item, str) for item in context_files
    ):
        raise ValueError(
            f"'context_files' for stage #{index} in {path} must be a list of strings."
        )

    timeout_seconds = raw.get("timeout_seconds", 3600)
    if not isinstance(timeout_seconds, int):
        raise ValueError(
            f"'timeout_seconds' for stage #{index} in {path} must be an integer."
        )

    retry_on_failure = raw.get("retry_on_failure", True)
    if not isinstance(retry_on_failure, bool):
        raise ValueError(
            f"'retry_on_failure' for stage #{index} in {path} must be a boolean."
        )

    max_retries = raw.get("max_retries", 3)
    if not isinstance(max_retries, int):
        raise ValueError(f"'max_retries' for stage #{index} in {path} must be an integer.")

    model = raw.get("model")
    if model is not None and not isinstance(model, str):
        raise ValueError(f"'model' for stage #{index} in {path} must be a string.")

    metadata = _optional_mapping(raw.get("metadata"), "metadata", path, index=index)

    return PipelineStage(
        name=_require_str(raw, "name", path, index=index),
        type=stage_type,
        agent_type=_require_str(raw, "agent_type", path, index=index),
        prompt_template=_require_str(raw, "prompt_template", path, index=index),
        model=model,
        depends_on=list(depends_on),
        timeout_seconds=timeout_seconds,
        retry_on_failure=retry_on_failure,
        max_retries=max_retries,
        context_files=list(context_files),
        metadata=metadata,
    )


def _require_str(
    raw: Mapping[str, Any],
    key: str,
    path: Path,
    *,
    index: int | None = None,
) -> str:
    value = raw.get(key)
    if not isinstance(value, str):
        location = f"stage #{index}" if index is not None else "pipeline"
        raise ValueError(f"Expected string field {key!r} in {location} definition: {path}")
    return value


def _optional_mapping(
    value: Any,
    key: str,
    path: Path,
    *,
    index: int | None = None,
) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        location = f"stage #{index}" if index is not None else "pipeline"
        raise ValueError(f"Expected mapping field {key!r} in {location} definition: {path}")
    return dict(value)


def _find_cycle(pipeline: Pipeline) -> list[str] | None:
    dependency_map = {stage.name: list(stage.depends_on) for stage in pipeline.stages}
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(stage_name: str) -> list[str] | None:
        if stage_name in visiting:
            cycle_start = stack.index(stage_name)
            return stack[cycle_start:] + [stage_name]
        if stage_name in visited:
            return None

        visiting.add(stage_name)
        stack.append(stage_name)
        for dependency in dependency_map.get(stage_name, []):
            cycle = visit(dependency)
            if cycle:
                return cycle
        stack.pop()
        visiting.remove(stage_name)
        visited.add(stage_name)
        return None

    for stage_name in dependency_map:
        cycle = visit(stage_name)
        if cycle:
            return cycle
    return None
