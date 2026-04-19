#!/usr/bin/env python3
"""Bootstrap a new feature-development workflow."""

from __future__ import annotations

import argparse
import asyncio
import sys

import _bootstrap  # noqa: F401
from _reins_script_support import (
    create_executor,
    create_task,
    get_repo_root,
    load_pipeline,
    resolve_path,
    result_error,
    safe_slug,
    write_pipeline_output,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap feature development.")
    parser.add_argument("title", help="Feature title.")
    parser.add_argument(
        "--type",
        choices=["frontend", "backend", "fullstack"],
        default="fullstack",
        help="Task type.",
    )
    parser.add_argument(
        "--pipeline",
        default=".reins/pipelines/standard.yaml",
        help="Pipeline YAML to run after task creation.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo_root = get_repo_root()
    task_dir = create_task(
        repo_root,
        title=args.title,
        task_type=args.type,
        slug=safe_slug(args.title, max_length=30),
        prd_content=f"Plan and deliver: {args.title}",
        acceptance_criteria=[
            "Requirements are clarified in the PRD",
            "Implementation approach is captured",
            "Verification path is defined",
        ],
        metadata={"bootstrap": "feature"},
    )

    prd_path = task_dir / "prd.md"
    prd_path.write_text(
        "\n".join(
            [
                f"# {args.title}",
                "",
                "## Goal",
                "[Describe what you want to achieve]",
                "",
                "## Requirements",
                "- [ ] Requirement 1",
                "- [ ] Requirement 2",
                "",
                "## Acceptance Criteria",
                "- [ ] Criterion 1",
                "- [ ] Criterion 2",
                "",
                "## Technical Notes",
                "[Any technical decisions or constraints]",
                "",
            ]
        ),
        encoding="utf-8",
    )

    pipeline_path = resolve_path(args.pipeline, repo_root=repo_root)
    if not pipeline_path.exists():
        print(f"Error: pipeline file not found: {pipeline_path}", file=sys.stderr)
        return 1

    pipeline = load_pipeline(pipeline_path)
    executor = create_executor(repo_root)
    result = asyncio.run(executor.run_pipeline_definition(pipeline, task_dir))
    output_dir = task_dir / "pipeline-output"
    write_pipeline_output(
        output_dir,
        pipeline_path=pipeline_path,
        task_dir=task_dir,
        result=result,
    )

    print(f"Created task: {task_dir}")
    print(f"Created PRD: {prd_path}")
    print(f"Pipeline output: {output_dir}")

    if not result.success:
        print(f"Bootstrap failed: {result_error(result) or 'unknown error'}", file=sys.stderr)
        return 1

    print("\nBootstrap complete")
    print("Next steps:")
    print(f"  1. Edit {prd_path}")
    print(f"  2. Run: reins task start {task_dir.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
