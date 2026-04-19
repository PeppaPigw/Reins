from __future__ import annotations

from pathlib import Path

from tests.unit.cli_helpers import create_repo, invoke


def _latest_task_id(repo: Path) -> str:
    task_dirs = sorted(path.name for path in (repo / ".reins" / "tasks").iterdir() if path.is_dir())
    assert task_dirs
    return task_dirs[-1]


def test_task_lifecycle_hooks_fire_from_cli(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path)
    (repo / ".reins" / "config.yaml").write_text(
        """
hooks:
  after_create:
    - python -c "import json, os, pathlib; data=json.load(open(os.environ['TASK_JSON_PATH'])); pathlib.Path('after-create.txt').write_text(data['status'], encoding='utf-8')"
  after_start:
    - python -c "import json, os, pathlib; data=json.load(open(os.environ['TASK_JSON_PATH'])); pathlib.Path('after-start.txt').write_text(data['status'], encoding='utf-8')"
  after_archive:
    - python -c "import json, os, pathlib; data=json.load(open(os.environ['TASK_JSON_PATH'])); pathlib.Path('after-archive.txt').write_text(data['status'], encoding='utf-8')"
""".strip(),
        encoding="utf-8",
    )

    create = invoke(
        repo,
        monkeypatch,
        [
            "task",
            "create",
            "Hooked task",
            "--type",
            "backend",
            "--priority",
            "P1",
        ],
    )
    assert create.exit_code == 0
    task_id = _latest_task_id(repo)
    assert (repo / "after-create.txt").read_text(encoding="utf-8") == "pending"

    start = invoke(repo, monkeypatch, ["task", "start", task_id, "--assignee", "peppa"])
    assert start.exit_code == 0
    assert (repo / "after-start.txt").read_text(encoding="utf-8") == "in_progress"

    archive = invoke(repo, monkeypatch, ["task", "archive", task_id])
    assert archive.exit_code == 0
    assert (repo / "after-archive.txt").read_text(encoding="utf-8") == "archived"
