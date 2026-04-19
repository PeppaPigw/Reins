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


def _write_pipeline(repo_root: Path) -> Path:
    pipeline_dir = repo_root / ".reins" / "pipelines"
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    path = pipeline_dir / "standalone.yaml"
    path.write_text(
        """
name: standalone
description: Standalone pipeline
stages:
  - name: research
    type: research
    agent_type: researcher
    model: gpt-5.4-mini
    prompt_template: "Research {task_goal}"
  - name: verify
    type: verify
    agent_type: verifier
    depends_on: [research]
    prompt_template: "Verify {task_goal}"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_task(task_dir: Path, *, title: str) -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "task.json").write_text(
        json.dumps(
            {
                "task_id": task_dir.name,
                "title": title,
                "task_type": "backend",
                "metadata": {},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (task_dir / "prd.md").write_text(f"# {title}\n", encoding="utf-8")


def test_run_pipeline_script_writes_output_and_returns_success(tmp_path: Path) -> None:
    repo_root = _copy_runtime_repo(tmp_path)
    pipeline_path = _write_pipeline(repo_root)
    task_dir = repo_root / ".reins" / "tasks" / "task-1"
    _write_task(task_dir, title="Standalone pipeline task")
    output_dir = repo_root / ".reins" / "pipeline-output" / "task-1"

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "run_pipeline.py"),
            str(pipeline_path),
            "--task-dir",
            str(task_dir),
            "--output",
            str(output_dir),
            "--model",
            "gpt-5.4",
            "--parallel",
            "1",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Pipeline completed successfully" in result.stdout

    payload = json.loads((output_dir / "result.json").read_text(encoding="utf-8"))
    assert payload["success"] is True
    assert payload["status"] == "completed"
    assert (output_dir / "research.txt").exists()
    assert (output_dir / "verify.txt").exists()
    assert (output_dir / "pipeline-state.json").exists()


def test_run_batch_script_processes_multiple_tasks(tmp_path: Path) -> None:
    repo_root = _copy_runtime_repo(tmp_path)
    pipeline_path = _write_pipeline(repo_root)
    tasks_dir = repo_root / ".reins" / "tasks"
    _write_task(tasks_dir / "task-a", title="Task A")
    _write_task(tasks_dir / "task-b", title="Task B")
    output_dir = repo_root / ".reins" / "batch-output"

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "run_batch.py"),
            str(pipeline_path),
            str(tasks_dir),
            "--output",
            str(output_dir),
            "--parallel",
            "2",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Completed: 2/2 tasks successful" in result.stdout

    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert {entry["task"] for entry in summary} == {"task-a", "task-b"}
    assert all(entry["success"] is True for entry in summary)
    assert (output_dir / "task-a" / "result.json").exists()
    assert (output_dir / "task-b" / "result.json").exists()
