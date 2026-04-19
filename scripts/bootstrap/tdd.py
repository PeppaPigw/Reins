#!/usr/bin/env python3
"""Bootstrap a test-driven-development workflow."""

from __future__ import annotations

import argparse
import asyncio

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
    parser = argparse.ArgumentParser(description="Bootstrap a TDD workflow.")
    parser.add_argument("title", help="Feature title.")
    parser.add_argument("--module", required=True, help="Module or function name.")
    parser.add_argument(
        "--pipeline",
        default=None,
        help="Optional pipeline YAML to run after generating the templates.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo_root = get_repo_root()
    module_name = args.module.replace("-", "_")
    class_name = "".join(part.capitalize() for part in module_name.split("_"))
    task_dir = create_task(
        repo_root,
        title=f"TDD: {args.title}",
        task_type="backend",
        slug=safe_slug(args.title, prefix="tdd", max_length=30),
        prd_content=f"Drive the implementation with tests first: {args.title}",
        acceptance_criteria=[
            "A failing test captures the intended behavior",
            "Implementation satisfies the new test suite",
            "Edge cases are covered explicitly",
        ],
        metadata={"bootstrap": "tdd", "module": module_name},
    )

    test_template = task_dir / "test_template.py"
    test_template.write_text(
        "\n".join(
            [
                f"# Test Template: {args.title}",
                "",
                "import pytest",
                "",
                "",
                f"class Test{class_name}:",
                f'    """Test suite for {module_name}."""',
                "",
                "    def test_basic_functionality(self):",
                '        """Test basic functionality."""',
                "        # TODO: Write test",
                "        pass",
                "",
                "    def test_edge_cases(self):",
                '        """Test edge cases."""',
                "        # TODO: Write test",
                "        pass",
                "",
                "    def test_error_handling(self):",
                '        """Test error handling."""',
                "        # TODO: Write test",
                "        pass",
                "",
            ]
        ),
        encoding="utf-8",
    )

    implementation_template = task_dir / "implementation_template.py"
    implementation_template.write_text(
        "\n".join(
            [
                f"# Implementation: {args.title}",
                "",
                "",
                f"def {module_name}():",
                f'    """TODO: Implement {args.title}."""',
                '    raise NotImplementedError("TODO: Implement this function")',
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"Created task: {task_dir}")
    print(f"Created test template: {test_template}")
    print(f"Created implementation template: {implementation_template}")

    if args.pipeline:
        pipeline_path = resolve_path(args.pipeline, repo_root=repo_root)
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
        print(f"Pipeline output: {output_dir}")
        if not result.success:
            print(f"Bootstrap failed: {result_error(result) or 'unknown error'}")
            return 1

    print("\nTDD bootstrap complete")
    print("Next steps:")
    print(f"  1. Write tests in {test_template}")
    print("  2. Run the tests and watch them fail first")
    print(f"  3. Implement the behavior in {implementation_template}")
    print("  4. Re-run the tests until they pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
