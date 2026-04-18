from __future__ import annotations

from pathlib import Path

import pytest

from reins.isolation.worktree_config import (
    WorktreeConfigError,
    WorktreeTemplateConfig,
    load_worktree_config,
    save_worktree_config,
)


def test_load_worktree_config_prefers_reins(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    reins_dir = repo_root / ".reins"
    trellis_dir = repo_root / ".trellis"
    reins_dir.mkdir()
    trellis_dir.mkdir()

    (reins_dir / "worktree.yaml").write_text(
        "worktree_dir: ../agent-worktrees\ncopy:\n  - .reins/.developer\n",
        encoding="utf-8",
    )
    (trellis_dir / "worktree.yaml").write_text(
        "worktree_dir: ../trellis-worktrees\ncopy:\n  - .trellis/.developer\n",
        encoding="utf-8",
    )

    config = load_worktree_config(repo_root)

    assert config.source_path == reins_dir / "worktree.yaml"
    assert config.worktree_dir == repo_root.parent / "agent-worktrees"
    assert config.copy == [".reins/.developer"]


def test_load_worktree_config_falls_back_to_trellis(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    trellis_dir = repo_root / ".trellis"
    trellis_dir.mkdir()

    (trellis_dir / "worktree.yaml").write_text(
        """
worktree_dir: ../trellis-worktrees
copy:
  - .trellis/.developer
post_create:
  - python -V
verify:
  - git status --short
""".strip(),
        encoding="utf-8",
    )

    config = load_worktree_config(repo_root)

    assert config.source_path == trellis_dir / "worktree.yaml"
    assert config.worktree_dir == repo_root.parent / "trellis-worktrees"
    assert config.copy == [".trellis/.developer"]
    assert config.post_create == ["python -V"]
    assert config.verify == ["git status --short"]


def test_load_worktree_config_rejects_invalid_types(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    reins_dir = repo_root / ".reins"
    reins_dir.mkdir()

    (reins_dir / "worktree.yaml").write_text(
        "worktree_dir: 123\ncopy: not-a-list\n",
        encoding="utf-8",
    )

    with pytest.raises(WorktreeConfigError, match="worktree_dir"):
        load_worktree_config(repo_root)


def test_save_worktree_config_round_trips(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    config = WorktreeTemplateConfig(
        worktree_dir=repo_root.parent / "reins-worktrees",
        copy=[".reins/.developer"],
        post_create=["python -V"],
        verify=["git status --short"],
    )

    target = repo_root / ".reins" / "worktree.yaml"
    save_worktree_config(config, repo_root=repo_root, path=target)

    loaded = load_worktree_config(repo_root, path=target)

    assert loaded.worktree_dir == config.worktree_dir
    assert loaded.copy == config.copy
    assert loaded.post_create == config.post_create
    assert loaded.verify == config.verify
