from __future__ import annotations

import json
from pathlib import Path

from tests.unit.cli_helpers import create_repo, invoke


def _write_pipeline(repo: Path, name: str, content: str) -> None:
    pipeline_dir = repo / ".reins" / "pipelines"
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    (pipeline_dir / f"{name}.yaml").write_text(content, encoding="utf-8")


def test_pipeline_cli_run_list_and_status(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path, git=False)
    task_dir = repo / ".reins" / "tasks" / "task-1"
    task_dir.mkdir(parents=True)
    (task_dir / "task.json").write_text(
        json.dumps(
            {
                "task_id": "task-1",
                "title": "CLI pipeline task",
                "task_type": "backend",
                "metadata": {},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (task_dir / "prd.md").write_text("# PRD\n", encoding="utf-8")
    _write_pipeline(
        repo,
        "standard",
        """
name: standard
description: Standard pipeline
stages:
  - name: research
    type: research
    agent_type: research
    prompt_template: "Research {task_goal}"
""".strip()
        + "\n",
    )

    listed = invoke(repo, monkeypatch, ["pipeline", "list"])
    assert listed.exit_code == 0
    assert "standard" in listed.output

    result = invoke(
        repo,
        monkeypatch,
        ["pipeline", "run", "standard", "--task", str(task_dir)],
    )
    assert result.exit_code == 0
    assert "Pipeline completed" in result.output

    pipeline_id = result.output.split("(")[-1].split(")")[0]
    status = invoke(repo, monkeypatch, ["pipeline", "status", pipeline_id])
    assert status.exit_code == 0
    assert "completed" in status.output
