from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def _copy_runtime_repo(tmp_path: Path) -> Path:
    source_root = Path(__file__).resolve().parents[2]
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    shutil.copytree(source_root / "src", repo_root / "src")
    shutil.copytree(source_root / "scripts", repo_root / "scripts")
    (repo_root / ".reins").mkdir()
    (repo_root / ".reins" / "tasks").mkdir()
    (repo_root / ".reins" / "spec").mkdir()
    (repo_root / ".reins" / "workspace").mkdir()
    return repo_root


def _write_pipeline(repo_root: Path, name: str) -> Path:
    pipeline_dir = repo_root / ".reins" / "pipelines"
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    path = pipeline_dir / f"{name}.yaml"
    path.write_text(
        f"""
name: {name}
description: {name} pipeline
stages:
  - name: {name}-stage
    type: custom
    agent_type: tester
    prompt_template: "{name} {{task_goal}}"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return path


def _task_dirs(repo_root: Path) -> list[Path]:
    return sorted(path for path in (repo_root / ".reins" / "tasks").iterdir() if path.is_dir())


def test_feature_bootstrap_creates_task_prd_and_pipeline_output(tmp_path: Path) -> None:
    repo_root = _copy_runtime_repo(tmp_path)
    pipeline_path = _write_pipeline(repo_root, "standard")

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "bootstrap" / "feature.py"),
            "Add user authentication",
            "--type",
            "fullstack",
            "--pipeline",
            str(pipeline_path),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    task_dir = _task_dirs(repo_root)[0]
    assert (task_dir / "prd.md").exists()
    assert "## Requirements" in (task_dir / "prd.md").read_text(encoding="utf-8")
    assert (task_dir / "pipeline-output" / "result.json").exists()


def test_bugfix_bootstrap_creates_bug_report_and_debug_output(tmp_path: Path) -> None:
    repo_root = _copy_runtime_repo(tmp_path)
    pipeline_path = _write_pipeline(repo_root, "debug")

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "bootstrap" / "bugfix.py"),
            "Fix login timeout",
            "--file",
            "src/auth/login.py",
            "--pipeline",
            str(pipeline_path),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    task_dir = _task_dirs(repo_root)[0]
    bug_report = task_dir / "bug-report.md"
    assert bug_report.exists()
    assert "`src/auth/login.py`" in bug_report.read_text(encoding="utf-8")
    assert (task_dir / "debug-output" / "result.json").exists()


def test_tdd_bootstrap_creates_templates_without_pipeline(tmp_path: Path) -> None:
    repo_root = _copy_runtime_repo(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "bootstrap" / "tdd.py"),
            "Add user validation",
            "--module",
            "validate_user",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    task_dir = _task_dirs(repo_root)[0]
    assert (task_dir / "test_template.py").exists()
    assert (task_dir / "implementation_template.py").exists()
    task_json = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    assert task_json["metadata"]["bootstrap"] == "tdd"
