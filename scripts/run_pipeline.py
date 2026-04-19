#!/usr/bin/env python3
"""Standalone pipeline runner for CI/CD and automation.

Usage:
    python3 scripts/run_pipeline.py <pipeline-yaml> --task-dir <dir>

Example:
    python3 scripts/run_pipeline.py .reins/pipelines/standard.yaml --task-dir .reins/tasks/my-task
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from _reins_script_support import (
    create_executor,
    get_repo_root,
    load_pipeline,
    resolve_path,
    result_error,
    write_pipeline_output,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a Reins multi-agent pipeline.")
    parser.add_argument("pipeline", help="Path to the pipeline YAML file.")
    parser.add_argument("--task-dir", required=True, help="Task directory path.")
    parser.add_argument(
        "--output",
        default=".reins/pipeline-output",
        help="Directory where run artifacts are written.",
    )
    parser.add_argument("--model", default=None, help="Override the stage model hint.")
    parser.add_argument(
        "--parallel",
        type=int,
        default=3,
        help="Maximum number of parallel stages to execute at once.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo_root = get_repo_root()
    pipeline_path = resolve_path(args.pipeline, repo_root=repo_root)
    task_dir = resolve_path(args.task_dir, repo_root=repo_root)
    output_dir = resolve_path(args.output, repo_root=repo_root)

    if not pipeline_path.exists():
        print(f"Error: pipeline file not found: {pipeline_path}", file=sys.stderr)
        return 1

    pipeline = load_pipeline(pipeline_path, model_override=args.model)
    executor = create_executor(repo_root, max_parallel_stages=args.parallel)

    print(f"Running pipeline: {pipeline.name}")
    print(f"Pipeline file: {pipeline_path}")
    print(f"Task directory: {task_dir}")
    print(f"Stages: {len(pipeline.stages)}")

    try:
        result = asyncio.run(executor.run_pipeline_definition(pipeline, task_dir))
    except Exception as exc:
        print(f"\nPipeline failed before completion: {exc}", file=sys.stderr)
        return 1

    write_pipeline_output(
        output_dir,
        pipeline_path=pipeline_path,
        task_dir=task_dir,
        result=result,
    )

    if result.success:
        print("\nPipeline completed successfully")
        print(f"Duration: {result.total_duration_seconds:.3f}s")
        print(f"Output: {output_dir}")
        return 0

    error = result_error(result) or "unknown error"
    print(f"\nPipeline failed: {error}", file=sys.stderr)
    print(f"Output: {output_dir}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
