from __future__ import annotations

import json
from pathlib import Path

import pytest

from reins.cli import utils
from reins.cli.commands import init as init_cmd
from reins.cli.commands import spec as spec_cmd
from reins.cli.commands import task_context as task_ctx
from reins.context.compiler import ContextSource
from reins.platform.project_detector import ProjectDetector, ProjectType
from tests.unit.cli_helpers import create_repo, invoke


def test_project_detector_branch_coverage(tmp_path: Path) -> None:
    detector = ProjectDetector()

    frontend_repo = tmp_path / "frontend"
    (frontend_repo / "src" / "components").mkdir(parents=True)
    assert detector.detect(frontend_repo) == ProjectType.FRONTEND

    backend_repo = tmp_path / "backend"
    backend_repo.mkdir()
    (backend_repo / "worker.py").write_text("print('backend')\n", encoding="utf-8")
    assert detector.detect(backend_repo) == ProjectType.BACKEND
    assert detector.resolve(backend_repo, None) == ProjectType.BACKEND
    assert detector.resolve(backend_repo, "frontend") == ProjectType.FRONTEND

    marker_repo = tmp_path / "marker-backend"
    (marker_repo / "backend").mkdir(parents=True)
    assert detector.detect(marker_repo) == ProjectType.BACKEND

    pyproject_repo = tmp_path / "pyproject-repo"
    pyproject_repo.mkdir()
    (pyproject_repo / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\ndependencies = ['fastapi>=0.1']\n",
        encoding="utf-8",
    )
    assert detector.detect(pyproject_repo) == ProjectType.BACKEND

    generic_pyproject_repo = tmp_path / "generic-pyproject-repo"
    generic_pyproject_repo.mkdir()
    (generic_pyproject_repo / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\ndependencies = ['requests>=2']\n",
        encoding="utf-8",
    )
    assert detector.detect(generic_pyproject_repo) == ProjectType.BACKEND

    invalid_repo = tmp_path / "invalid"
    invalid_repo.mkdir()
    (invalid_repo / "package.json").write_text("{bad json", encoding="utf-8")
    assert detector.detect_packages(invalid_repo) == []
    assert detector.infer_package(invalid_repo, ["missing.py"]) is None

    workspace_repo = tmp_path / "workspace"
    (workspace_repo / "apps" / "web").mkdir(parents=True)
    (workspace_repo / "apps" / "web" / "src").mkdir()
    (workspace_repo / "apps" / "web" / "src" / "page.tsx").write_text("export default 1\n", encoding="utf-8")
    (workspace_repo / "package.json").write_text(
        json.dumps({"workspaces": {"packages": ["apps/*"]}}),
        encoding="utf-8",
    )
    assert detector.detect_packages(workspace_repo) == ["web"]

    direct_repo = tmp_path / "direct"
    direct_repo.mkdir()
    (direct_repo / "auth").mkdir()
    (direct_repo / "auth" / "api.py").write_text("print('auth')\n", encoding="utf-8")
    (direct_repo / "package.json").write_text(
        json.dumps({"workspaces": ["auth"]}),
        encoding="utf-8",
    )
    assert detector.resolve_package(direct_repo) == "auth"
    assert detector.infer_package(direct_repo, ["auth/api.py"]) == "auth"
    assert detector.resolve_package(direct_repo, file_paths=["auth/api.py"]) == "auth"

    multi_repo = tmp_path / "multi"
    (multi_repo / "packages" / "auth").mkdir(parents=True)
    (multi_repo / "packages" / "billing").mkdir(parents=True)
    assert detector.detect_packages(multi_repo) == ["auth", "billing"]
    assert detector.infer_package(multi_repo, ["README.md"]) is None
    assert detector.resolve_package(multi_repo, package="manual") == "manual"
    assert detector.resolve_package(multi_repo) is None


def test_init_helper_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    monkeypatch.setattr(init_cmd.typer, "prompt", lambda *_args, **_kwargs: "1")
    selected = init_cmd._resolve_platform(None, repo_root=repo_root)
    assert selected is not None

    monkeypatch.setattr(init_cmd.typer, "prompt", lambda *_args, **_kwargs: "999")
    with pytest.raises(utils.CLIError):
        init_cmd._resolve_platform(None, repo_root=repo_root)

    monkeypatch.setattr(init_cmd.typer, "prompt", lambda *_args, **_kwargs: "not-a-platform")
    with pytest.raises(utils.CLIError):
        init_cmd._resolve_platform(None, repo_root=repo_root)

    utils.write_developer_identity(repo_root, "peppa")
    assert init_cmd._resolve_developer(repo_root, None) == "peppa"

    monkeypatch.setattr(init_cmd.getpass, "getuser", lambda: (_ for _ in ()).throw(OSError("no user")))
    (repo_root / ".reins" / ".developer").unlink()
    assert init_cmd._resolve_developer(repo_root, None) == "unknown"

    detector = ProjectDetector()
    (repo_root / "packages" / "auth").mkdir(parents=True, exist_ok=True)
    assert init_cmd._resolve_package(detector, repo_root, None) == "auth"

    (repo_root / "packages" / "billing").mkdir(parents=True, exist_ok=True)

    class _TTY:
        @staticmethod
        def isatty() -> bool:
            return True

    monkeypatch.setattr(init_cmd.sys, "stdin", _TTY())
    monkeypatch.setattr(init_cmd.typer, "prompt", lambda *_args, **_kwargs: "billing")
    assert init_cmd._resolve_package(detector, repo_root, None) == "billing"


def test_task_context_helper_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = create_repo(tmp_path)

    with pytest.raises(utils.CLIError):
        task_ctx._load_task_metadata(repo, "missing-task")

    (repo / ".reins" / "spec" / "backend").mkdir(parents=True, exist_ok=True)
    (repo / ".reins" / "spec" / "backend" / "index.md").write_text("# Backend\n", encoding="utf-8")

    class _FakeCompiler:
        def resolve_spec_sources(self, *_args, **_kwargs):
            backend_dir = repo / ".reins" / "spec" / "backend"
            return [
                ContextSource(type="spec", identifier="none"),
                ContextSource(type="spec", path=str(backend_dir)),
                ContextSource(type="spec", path=str(backend_dir)),
            ]

    monkeypatch.setattr(task_ctx, "ContextCompiler", _FakeCompiler)
    files = task_ctx._relevant_spec_files(repo, "backend", None)
    assert files == [repo / ".reins" / "spec" / "backend" / "index.md"]

    with pytest.raises(utils.CLIError):
        task_ctx._init_context(repo, "run", "task-1", "invalid")
    with pytest.raises(utils.CLIError):
        task_ctx._add_context(repo, "run", "task-1", "invalid", repo / "missing.md", "nope")

    task_dir = repo / ".reins" / "tasks" / "task-1"
    task_dir.mkdir(parents=True, exist_ok=True)
    directory = repo / "docs"
    directory.mkdir()
    with pytest.raises(utils.CLIError):
        task_ctx._add_context(repo, "run", "task-1", "implement", directory, "directory")


def test_spec_helper_and_cli_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = create_repo(tmp_path)

    with pytest.raises(ValueError):
        spec_cmd._render_layer_index("backend")

    empty_package = spec_cmd._package_index_content("auth", [])
    assert "Add package layer guidance" in empty_package
    assert "Add layers under this package" in empty_package

    existing = repo / ".reins" / "spec" / "backend" / "index.md"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("keep", encoding="utf-8")
    assert spec_cmd._write_if_missing(existing, "new") is False

    errors = spec_cmd._validate_spec_data(
        {
            "content": 123,
            "spec_type": "invalid",
            "visibility_tier": 9,
            "precedence": "high",
            "required_capabilities": "not-a-list",
            "applicability": "not-a-dict",
        },
        Path("bad.yaml"),
    )
    assert len(errors) == 6

    monkeypatch.setattr(spec_cmd.utils, "get_current_task_id", lambda _repo_root: None)
    with pytest.raises(utils.CLIError):
        spec_cmd._load_task_metadata(repo, None)

    task_dir = repo / ".reins" / "tasks" / "task-1"
    task_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(spec_cmd.utils, "get_current_task_id", lambda _repo_root: "task-1")
    with pytest.raises(utils.CLIError):
        spec_cmd._load_task_metadata(repo, None)

    (repo / ".reins" / "spec" / "backend" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (repo / ".reins" / "spec" / "backend" / "index.md").write_text(
        "# Backend\n\n## Pre-Development Checklist\n\n- [ ] [Guide](guide.md) - Read it\n- [ ] [Missing](missing.md) - Missing file\n",
        encoding="utf-8",
    )
    (repo / ".reins" / "spec" / "guides").mkdir(parents=True, exist_ok=True)
    (repo / ".reins" / "spec" / "guides" / "shared.md").write_text("# Shared\n", encoding="utf-8")
    (repo / ".reins" / "spec" / "guides" / "index.md").write_text(
        "# Guides\n\n## Pre-Development Checklist\n\n- [ ] [Shared](shared.md) - Read it\n",
        encoding="utf-8",
    )

    real_context_compiler = spec_cmd.ContextCompiler

    class _ChecklistCompiler:
        def resolve_spec_sources(self, *_args, **_kwargs):
            return [
                ContextSource(type="spec", identifier="none"),
                ContextSource(type="spec", path=str(repo / ".reins" / "spec" / "backend")),
            ]

    monkeypatch.setattr(spec_cmd, "ContextCompiler", _ChecklistCompiler)
    checklist_sources = spec_cmd._checklist_sources(repo, {"task_type": 7, "metadata": "bad"})
    assert checklist_sources == [repo / ".reins" / "spec" / "backend" / "index.md"]
    monkeypatch.setattr(spec_cmd, "ContextCompiler", real_context_compiler)

    with pytest.raises(utils.CLIError):
        spec_cmd._normalize_tracked_path(repo, repo / "README.md")

    absolute_file = tmp_path / "absolute.md"
    absolute_file.write_text("# Absolute\n", encoding="utf-8")
    assert spec_cmd._resolve_mark_read_path(repo, {}, str(absolute_file)) == absolute_file

    repo_file = repo / "notes.md"
    repo_file.write_text("# Notes\n", encoding="utf-8")
    assert spec_cmd._resolve_mark_read_path(repo, {}, "notes.md") == repo_file

    spec_file = repo / ".reins" / "spec" / "backend" / "guide.md"
    assert spec_cmd._resolve_mark_read_path(repo, {}, "backend/guide.md") == spec_file

    unique_only = repo / ".reins" / "spec" / "backend" / "unique.md"
    unique_only.write_text("# Unique\n", encoding="utf-8")
    (repo / ".reins" / "spec" / "guides" / "index.md").write_text("# Guides\n", encoding="utf-8")
    (repo / ".reins" / "spec" / "backend" / "index.md").write_text(
        "# Backend\n\n## Pre-Development Checklist\n\n- [ ] [Unique](unique.md) - Read it\n",
        encoding="utf-8",
    )
    assert spec_cmd._resolve_mark_read_path(repo, {"task_type": "backend"}, "unique.md") == unique_only

    shared_backend = repo / ".reins" / "spec" / "backend" / "shared.md"
    shared_backend.write_text("# Shared backend\n", encoding="utf-8")
    (repo / ".reins" / "spec" / "guides" / "index.md").write_text(
        "# Guides\n\n## Pre-Development Checklist\n\n- [ ] [Shared](shared.md) - Read it\n",
        encoding="utf-8",
    )
    (repo / ".reins" / "spec" / "backend" / "index.md").write_text(
        "# Backend\n\n## Pre-Development Checklist\n\n- [ ] [Shared](shared.md) - Read it\n",
        encoding="utf-8",
    )
    with pytest.raises(utils.CLIError):
        spec_cmd._resolve_mark_read_path(repo, {"task_type": "backend"}, "shared.md")
    with pytest.raises(utils.CLIError):
        spec_cmd._resolve_mark_read_path(repo, {}, "missing.md")

    (repo / ".reins" / "spec" / "backend" / "index.md").write_text(
        "# Backend\n\n## Pre-Development Checklist\n\n- [ ] [Missing](missing.md) - Missing file\n",
        encoding="utf-8",
    )
    lines, complete = spec_cmd._render_checklist_summary(
        repo,
        {"task_type": "backend", "metadata": {"checklist": {"read_specs": []}}},
    )
    assert complete is False
    assert any("Missing files:" in line for line in lines)

    missing_list = invoke(repo, monkeypatch, ["spec", "list", "--package", "missing"])
    assert missing_list.exit_code == 1

    quiet_dir = repo / ".reins" / "spec" / "quiet"
    quiet_dir.mkdir(parents=True, exist_ok=True)
    (quiet_dir / ".hidden").write_text("x", encoding="utf-8")
    empty_list = invoke(repo, monkeypatch, ["spec", "list", "--package", "quiet"])
    assert empty_list.exit_code == 0
    assert "No specs found" in empty_list.output

    listed_dir = repo / ".reins" / "spec" / "listed"
    listed_dir.mkdir(parents=True, exist_ok=True)
    (listed_dir / "rules.yaml").write_text("content: ok\n", encoding="utf-8")
    (listed_dir / "notes.txt").write_text("ignore me\n", encoding="utf-8")
    listed = invoke(repo, monkeypatch, ["spec", "list", "--package", "listed"])
    assert listed.exit_code == 0
    assert "rules.yaml" in listed.output

    empty_validate_dir = repo / ".reins" / "spec" / "empty"
    empty_validate_dir.mkdir(parents=True, exist_ok=True)
    no_yaml = invoke(repo, monkeypatch, ["spec", "validate", str(empty_validate_dir)])
    assert no_yaml.exit_code == 0
    assert "No YAML spec files found" in no_yaml.output

    bad_yaml = repo / ".reins" / "spec" / "bad.yaml"
    bad_yaml.write_text(": bad", encoding="utf-8")
    bad_yaml_result = invoke(repo, monkeypatch, ["spec", "validate", str(bad_yaml)])
    assert bad_yaml_result.exit_code == 1

    list_yaml = repo / ".reins" / "spec" / "list.yaml"
    list_yaml.write_text("- just\n- a\n- list\n", encoding="utf-8")
    list_yaml_result = invoke(repo, monkeypatch, ["spec", "validate", str(list_yaml)])
    assert list_yaml_result.exit_code == 1

    add_without_index = invoke(repo, monkeypatch, ["spec", "add-layer", "pkg", "status"])
    assert add_without_index.exit_code == 0
    assert (repo / ".reins" / "spec" / "pkg" / "index.md").exists()

    manual_index = repo / ".reins" / "spec" / "pkg2" / "index.md"
    manual_index.parent.mkdir(parents=True, exist_ok=True)
    manual_index.write_text("# Pkg2\n", encoding="utf-8")
    add_manual = invoke(repo, monkeypatch, ["spec", "add-layer", "pkg2", "ops"])
    assert add_manual.exit_code == 0
    assert "ops/index.md" in manual_index.read_text(encoding="utf-8")


def test_spec_checklist_cli_edge_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = create_repo(tmp_path)
    task_dir = repo / ".reins" / "tasks" / "task-1"
    task_dir.mkdir(parents=True, exist_ok=True)
    (repo / ".reins" / ".current-task").write_text("tasks/task-1", encoding="utf-8")
    (repo / ".reins" / "spec" / "backend").mkdir(parents=True, exist_ok=True)
    (repo / ".reins" / "spec" / "backend" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (repo / ".reins" / "spec" / "backend" / "index.md").write_text(
        "# Backend\n\n## Pre-Development Checklist\n\n- [ ] [Guide](guide.md) - Read it\n",
        encoding="utf-8",
    )

    (task_dir / "task.json").write_text(
        json.dumps({"id": "task-1", "task_type": "backend", "metadata": "bad"}),
        encoding="utf-8",
    )
    mark_from_bad_metadata = invoke(
        repo,
        monkeypatch,
        ["spec", "checklist", "--task", "task-1", "--mark-read", "backend/guide.md"],
    )
    assert mark_from_bad_metadata.exit_code == 0

    (task_dir / "task.json").write_text(
        json.dumps({"id": "task-1", "task_type": "backend", "metadata": {"checklist": "bad"}}),
        encoding="utf-8",
    )
    mark_from_bad_checklist = invoke(
        repo,
        monkeypatch,
        ["spec", "checklist", "--task", "task-1", "--mark-read", "backend/guide.md"],
    )
    assert mark_from_bad_checklist.exit_code == 0

    (task_dir / "task.json").write_text(
        json.dumps(
            {
                "id": "task-1",
                "task_type": "backend",
                "metadata": {"checklist": {"read_specs": "bad"}},
            }
        ),
        encoding="utf-8",
    )
    mark_from_bad_reads = invoke(
        repo,
        monkeypatch,
        ["spec", "checklist", "--task", "task-1", "--mark-read", "backend/guide.md"],
    )
    assert mark_from_bad_reads.exit_code == 0

    (repo / ".reins" / "spec").rename(repo / ".reins" / "spec-hidden")
    no_sources_read_only = invoke(repo, monkeypatch, ["spec", "checklist", "--task", "task-1"])
    assert no_sources_read_only.exit_code == 0
    assert "No checklist sources found" in no_sources_read_only.output
    no_sources = invoke(repo, monkeypatch, ["spec", "checklist", "--task", "task-1", "--validate"])
    assert no_sources.exit_code == 1
    assert "No checklist sources found" in no_sources.output
