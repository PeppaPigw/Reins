#!/usr/bin/env python3
"""Run a pipeline across multiple task directories."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from _reins_script_support import (
    create_executor,
    get_repo_root,
    load_pipeline,
    resolve_path,
    result_error,
    write_pipeline_output,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a pipeline on multiple tasks.")
    parser.add_argument("pipeline", help="Path to the pipeline YAML file.")
    parser.add_argument("tasks_dir", help="Directory containing task directories.")
    parser.add_argument(
        "--output",
        default=".reins/batch-output",
        help="Directory where per-task artifacts are written.",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=3,
        help="Maximum number of task directories to process concurrently.",
    )
    parser.add_argument("--model", default=None, help="Override the stage model hint.")
    return parser


async def _run_batch(
    *,
    repo_root: Path,
    pipeline_path: Path,
    task_dirs: list[Path],
    output_dir: Path,
    parallel: int,
    model_override: str | None,
) -> list[dict[str, str | bool | None]]:
    pipeline = load_pipeline(pipeline_path, model_override=model_override)
    semaphore = asyncio.Semaphore(parallel)
    journal = None

    async def run_task(task_dir: Path) -> dict[str, str | bool | None]:
        nonlocal journal
        async with semaphore:
            executor = create_executor(repo_root, journal=journal)
            if journal is None:
                journal = executor.journal
            result = await executor.run_pipeline_definition(pipeline, task_dir)
            task_output_dir = output_dir / task_dir.name
            write_pipeline_output(
                task_output_dir,
                pipeline_path=pipeline_path,
                task_dir=task_dir,
                result=result,
            )
            return {
                "task": task_dir.name,
                "success": result.success,
                "status": result.status.value,
                "error": result_error(result),
            }

    return await asyncio.gather(*(run_task(task_dir) for task_dir in task_dirs))


def main() -> int:
    args = build_parser().parse_args()
    repo_root = get_repo_root()
    pipeline_path = resolve_path(args.pipeline, repo_root=repo_root)
    tasks_dir = resolve_path(args.tasks_dir, repo_root=repo_root)
    output_dir = resolve_path(args.output, repo_root=repo_root)

    if not pipeline_path.exists():
        print(f"Error: pipeline file not found: {pipeline_path}", file=sys.stderr)
        return 1
    if not tasks_dir.is_dir():
        print(f"Error: tasks directory not found: {tasks_dir}", file=sys.stderr)
        return 1
    if args.parallel <= 0:
        print("Error: --parallel must be greater than zero.", file=sys.stderr)
        return 1

    task_dirs = sorted(path for path in tasks_dir.iterdir() if path.is_dir() and not path.name.startswith("."))
    if not task_dirs:
        print(f"Error: no task directories found in {tasks_dir}", file=sys.stderr)
        return 1

    print(f"Found {len(task_dirs)} tasks")
    print(f"Running with max {args.parallel} parallel tasks")

    results = asyncio.run(
        _run_batch(
            repo_root=repo_root,
            pipeline_path=pipeline_path,
            task_dirs=task_dirs,
            output_dir=output_dir,
            parallel=args.parallel,
            model_override=args.model,
        )
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    successes = 0
    for result in results:
        success = bool(result["success"])
        successes += 1 if success else 0
        status = "OK" if success else "FAIL"
        print(f"{status} {result['task']}")
        if result["error"]:
            print(f"  Error: {result['error']}")

    print(f"\nCompleted: {successes}/{len(results)} tasks successful")
    print(f"Output: {output_dir}")
    return 0 if successes == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
