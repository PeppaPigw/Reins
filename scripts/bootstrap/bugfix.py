#!/usr/bin/env python3
"""Bootstrap a bug-fix workflow."""

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
    parser = argparse.ArgumentParser(description="Bootstrap a bug-fix workflow.")
    parser.add_argument("title", help="Bug description.")
    parser.add_argument("--file", required=True, help="File with the bug or failing behavior.")
    parser.add_argument(
        "--pipeline",
        default=".reins/pipelines/debug.yaml",
        help="Pipeline YAML to run after task creation.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo_root = get_repo_root()
    task_dir = create_task(
        repo_root,
        title=f"Fix: {args.title}",
        task_type="backend",
        slug=safe_slug(args.title, prefix="fix", max_length=30),
        prd_content=f"Investigate and fix: {args.title}",
        acceptance_criteria=[
            "Failure is described clearly",
            "Root cause is identified",
            "Fix is verified against the original bug",
        ],
        metadata={"bootstrap": "bugfix", "target_file": args.file},
    )

    bug_report = task_dir / "bug-report.md"
    bug_report.write_text(
        "\n".join(
            [
                f"# Bug Report: {args.title}",
                "",
                "## File",
                f"`{args.file}`",
                "",
                "## Symptoms",
                "[Describe what's happening]",
                "",
                "## Expected Behavior",
                "[Describe what should happen]",
                "",
                "## Steps to Reproduce",
                "1. Step 1",
                "2. Step 2",
                "3. Step 3",
                "",
                "## Error Messages",
                "```",
                "[Paste error messages here]",
                "```",
                "",
                "## Investigation Notes",
                "[Add notes as you investigate]",
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
    output_dir = task_dir / "debug-output"
    write_pipeline_output(
        output_dir,
        pipeline_path=pipeline_path,
        task_dir=task_dir,
        result=result,
    )

    print(f"Created task: {task_dir}")
    print(f"Created bug report: {bug_report}")
    print(f"Debug output: {output_dir}")

    if not result.success:
        print(f"Bootstrap failed: {result_error(result) or 'unknown error'}", file=sys.stderr)
        return 1

    print("\nBootstrap complete")
    print("Next steps:")
    print(f"  1. Fill in {bug_report}")
    print("  2. Review the debug pipeline output")
    print("  3. Implement and verify the fix")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
