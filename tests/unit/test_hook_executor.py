from __future__ import annotations

import json
from pathlib import Path

from reins.config.hooks import HookExecutor
from reins.config.types import HooksConfig, ReinsConfig


def test_hook_executor_injects_task_json_path(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    task_dir = repo_root / ".reins" / "tasks" / "task-1"
    task_dir.mkdir(parents=True)
    task_json = task_dir / "task.json"
    task_json.write_text(json.dumps({"task_id": "task-1"}), encoding="utf-8")

    config = ReinsConfig(
        hooks=HooksConfig(
            after_create=[
                "python -c \"import os, pathlib; pathlib.Path('hook-path.txt').write_text(os.environ['TASK_JSON_PATH'], encoding='utf-8')\""
            ]
        )
    )
    executor = HookExecutor(repo_root, config)

    results = executor.execute_after_create("task-1")

    assert results[0].returncode == 0
    assert (repo_root / "hook-path.txt").read_text(encoding="utf-8") == str(task_json)


def test_hook_executor_continues_after_failures(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    task_dir = repo_root / ".reins" / "tasks" / "task-1"
    task_dir.mkdir(parents=True)
    (task_dir / "task.json").write_text(json.dumps({"task_id": "task-1"}), encoding="utf-8")

    config = ReinsConfig(
        hooks=HooksConfig(
            after_archive=[
                "python -c \"from pathlib import Path; Path('first.txt').write_text('ok', encoding='utf-8')\"",
                "python -c \"import sys; sys.stderr.write('boom'); raise SystemExit(2)\"",
                "python -c \"from pathlib import Path; Path('third.txt').write_text('still-ran', encoding='utf-8')\"",
            ]
        )
    )
    executor = HookExecutor(repo_root, config)

    results = executor.execute_after_archive("task-1")

    assert [result.returncode for result in results] == [0, 2, 0]
    assert results[1].stderr == "boom"
    assert (repo_root / "first.txt").read_text(encoding="utf-8") == "ok"
    assert (repo_root / "third.txt").read_text(encoding="utf-8") == "still-ran"
