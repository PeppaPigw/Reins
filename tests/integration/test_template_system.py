"""Integration tests for the platform template system."""

from __future__ import annotations

from pathlib import Path

from reins.platform import ConflictAction, PlatformType, TemplateFetcher, get_platform
from reins.platform.template_hash import TemplateHashStore


def test_template_fetcher_tracks_hashes_for_installed_templates(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    config = get_platform(PlatformType.CURSOR)
    assert config is not None

    fetcher = TemplateFetcher(hash_store=TemplateHashStore(repo_root))
    results = fetcher.install_templates(
        platform=config,
        repo_root=repo_root,
        file_mapping={".cursorrules": ".cursorrules"},
        variables={"developer": "peppa", "project_type": "frontend"},
    )

    hash_store_path = repo_root / ".reins" / ".template-hashes.json"
    assert hash_store_path.exists()
    payload = hash_store_path.read_text(encoding="utf-8")
    assert ".cursorrules" in payload
    assert results[0].action == "created"


def test_template_fetcher_preserves_user_customizations_by_default(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    config = get_platform(PlatformType.CURSOR)
    assert config is not None

    fetcher = TemplateFetcher(hash_store=TemplateHashStore(repo_root))
    fetcher.install_templates(
        platform=config,
        repo_root=repo_root,
        file_mapping={".cursorrules": ".cursorrules"},
        variables={"developer": "peppa", "project_type": "frontend"},
    )

    target = repo_root / ".cursorrules"
    target.write_text("# user customization\n", encoding="utf-8")

    results = fetcher.install_templates(
        platform=config,
        repo_root=repo_root,
        file_mapping={".cursorrules": ".cursorrules"},
        variables={"developer": "peppa", "project_type": "frontend"},
    )

    assert target.read_text(encoding="utf-8") == "# user customization\n"
    assert results[0].action == "kept"


def test_template_fetcher_updates_file_when_template_changes_without_local_edits(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    template_root = tmp_path / "templates"
    (template_root / "cursor").mkdir(parents=True)
    (template_root / "cursor" / ".cursorrules").write_text(
        "version one {{developer}}\n",
        encoding="utf-8",
    )

    config = get_platform(PlatformType.CURSOR)
    assert config is not None
    fetcher = TemplateFetcher(
        template_root=template_root,
        hash_store=TemplateHashStore(repo_root),
    )

    fetcher.install_templates(
        platform=config,
        repo_root=repo_root,
        file_mapping={".cursorrules": ".cursorrules"},
        variables={"developer": "peppa"},
    )
    (template_root / "cursor" / ".cursorrules").write_text(
        "version two {{developer}}\n",
        encoding="utf-8",
    )

    results = fetcher.install_templates(
        platform=config,
        repo_root=repo_root,
        file_mapping={".cursorrules": ".cursorrules"},
        variables={"developer": "peppa"},
    )

    assert (repo_root / ".cursorrules").read_text(encoding="utf-8") == "version two peppa\n"
    assert results[0].action == "updated"


def test_template_fetcher_merge_writes_merge_candidate(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    config = get_platform(PlatformType.CURSOR)
    assert config is not None
    fetcher = TemplateFetcher(hash_store=TemplateHashStore(repo_root))

    fetcher.install_templates(
        platform=config,
        repo_root=repo_root,
        file_mapping={".cursorrules": ".cursorrules"},
        variables={"developer": "peppa"},
    )
    (repo_root / ".cursorrules").write_text("# custom\n", encoding="utf-8")

    results = fetcher.install_templates(
        platform=config,
        repo_root=repo_root,
        file_mapping={".cursorrules": ".cursorrules"},
        variables={"developer": "peppa"},
        conflict_resolver=lambda *_args: ConflictAction.MERGE,
    )

    merge_path = repo_root / ".cursorrules.reins-merge"
    assert merge_path.exists()
    assert results[0].action == "merged"
