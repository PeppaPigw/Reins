"""Template fetching and installation for platform configurators."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping

import typer

from reins.platform.template_hash import TemplateHashStore, sha256_path, sha256_text
from reins.platform.types import PlatformConfig

ConflictResolver = Callable[[Path, str, str], "ConflictAction"]


class ConflictAction(str, Enum):
    """Actions available when an installed file conflicts with user edits."""

    KEEP = "keep"
    OVERWRITE = "overwrite"
    MERGE = "merge"


@dataclass(frozen=True)
class TemplateApplyResult:
    """Result of a single template application."""

    source_path: Path
    target_path: Path
    action: str


class TemplateFetcher:
    """Fetch and install platform templates."""

    def __init__(
        self,
        *,
        template_root: Path | None = None,
        hash_store: TemplateHashStore | None = None,
    ) -> None:
        self.template_root = template_root or Path(__file__).parent / "templates"
        self.hash_store = hash_store

    def _platform_dir(self, platform: PlatformConfig) -> Path:
        """Return the concrete template directory for a platform."""
        directory_name = platform.template_dirs[-1] if platform.template_dirs else platform.slug
        return self.template_root / directory_name

    def list_templates(self, platform: PlatformConfig) -> list[Path]:
        """List all template files for a platform."""
        platform_dir = self._platform_dir(platform)
        if not platform_dir.exists():
            return []
        return sorted(path for path in platform_dir.rglob("*") if path.is_file())

    def fetch_remote_templates(self, platform: PlatformConfig) -> list[Path]:
        """Placeholder for future remote template support."""
        raise NotImplementedError(
            f"Remote template registries are not implemented for {platform.name}."
        )

    def render_template(
        self,
        template_text: str,
        variables: Mapping[str, str] | None = None,
    ) -> str:
        """Render `{{name}}` variables inside a template string."""
        variables = variables or {}

        def replace(match: re.Match[str]) -> str:
            key = match.group(1).strip()
            return variables.get(key, match.group(0))

        return re.sub(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", replace, template_text)

    def install_templates(
        self,
        *,
        platform: PlatformConfig,
        repo_root: Path,
        file_mapping: Mapping[str, str],
        variables: Mapping[str, str] | None = None,
        conflict_resolver: ConflictResolver | None = None,
    ) -> list[TemplateApplyResult]:
        """Install platform templates into a repository."""
        if self.hash_store is None:
            self.hash_store = TemplateHashStore(repo_root)

        results: list[TemplateApplyResult] = []
        platform_dir = self._platform_dir(platform)

        for source_relative, target_relative in file_mapping.items():
            source_path = platform_dir / source_relative
            if not source_path.exists():
                raise FileNotFoundError(f"Missing template: {source_path}")

            target_path = repo_root / target_relative
            target_path.parent.mkdir(parents=True, exist_ok=True)

            rendered_content = self.render_template(
                source_path.read_text(encoding="utf-8"),
                variables,
            )
            template_hash = sha256_path(source_path)
            rendered_hash = sha256_text(rendered_content)

            result = self._write_template(
                source_path=source_path,
                target_path=target_path,
                rendered_content=rendered_content,
                template_hash=template_hash,
                rendered_hash=rendered_hash,
                conflict_resolver=conflict_resolver,
            )
            results.append(result)

        return results

    def _write_template(
        self,
        *,
        source_path: Path,
        target_path: Path,
        rendered_content: str,
        template_hash: str,
        rendered_hash: str,
        conflict_resolver: ConflictResolver | None,
    ) -> TemplateApplyResult:
        store = self.hash_store
        assert store is not None

        if not target_path.exists():
            target_path.write_text(rendered_content, encoding="utf-8")
            store.update(
                target_path=target_path,
                template_path=source_path,
                template_hash=template_hash,
                rendered_hash=rendered_hash,
            )
            return TemplateApplyResult(source_path, target_path, "created")

        record = store.get(target_path)
        if record is None:
            action = self._resolve_conflict(
                target_path=target_path,
                has_existing_record=False,
                conflict_resolver=conflict_resolver,
            )
            return self._apply_conflict_action(
                action=action,
                source_path=source_path,
                target_path=target_path,
                rendered_content=rendered_content,
                template_hash=template_hash,
                rendered_hash=rendered_hash,
            )

        current_hash = sha256_path(target_path)
        if current_hash == record.rendered_hash:
            if rendered_hash == record.rendered_hash:
                return TemplateApplyResult(source_path, target_path, "unchanged")
            target_path.write_text(rendered_content, encoding="utf-8")
            store.update(
                target_path=target_path,
                template_path=source_path,
                template_hash=template_hash,
                rendered_hash=rendered_hash,
            )
            return TemplateApplyResult(source_path, target_path, "updated")

        action = self._resolve_conflict(
            target_path=target_path,
            has_existing_record=True,
            conflict_resolver=conflict_resolver,
        )
        return self._apply_conflict_action(
            action=action,
            source_path=source_path,
            target_path=target_path,
            rendered_content=rendered_content,
            template_hash=template_hash,
            rendered_hash=rendered_hash,
        )

    def _resolve_conflict(
        self,
        *,
        target_path: Path,
        has_existing_record: bool,
        conflict_resolver: ConflictResolver | None,
    ) -> ConflictAction:
        if conflict_resolver is not None:
            return conflict_resolver(
                target_path,
                "managed" if has_existing_record else "unmanaged",
                "user customization detected",
            )

        if not sys.stdin.isatty():
            return ConflictAction.KEEP

        typer.echo(f"Conflict detected for {target_path}")
        typer.echo("Choose: keep / overwrite / merge")
        response = typer.prompt("Action", default=ConflictAction.KEEP.value).strip().lower()
        try:
            return ConflictAction(response)
        except ValueError:
            return ConflictAction.KEEP

    def _apply_conflict_action(
        self,
        *,
        action: ConflictAction,
        source_path: Path,
        target_path: Path,
        rendered_content: str,
        template_hash: str,
        rendered_hash: str,
    ) -> TemplateApplyResult:
        store = self.hash_store
        assert store is not None

        if action == ConflictAction.OVERWRITE:
            target_path.write_text(rendered_content, encoding="utf-8")
            store.update(
                target_path=target_path,
                template_path=source_path,
                template_hash=template_hash,
                rendered_hash=rendered_hash,
            )
            return TemplateApplyResult(source_path, target_path, "overwritten")

        if action == ConflictAction.MERGE:
            merge_path = target_path.with_name(f"{target_path.name}.reins-merge")
            merge_path.write_text(rendered_content, encoding="utf-8")
            return TemplateApplyResult(source_path, merge_path, "merged")

        return TemplateApplyResult(source_path, target_path, "kept")
