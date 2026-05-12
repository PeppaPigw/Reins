"""Descriptor-driven template engine for platform configuration."""

from __future__ import annotations

from pathlib import Path

from reins.platform.descriptors import PLATFORM_DESCRIPTORS, get_descriptor
from reins.platform.template_fetcher import (
    ConflictResolver,
    TemplateApplyResult,
    TemplateFetcher,
)
from reins.platform.template_hash import TemplateHashStore, sha256_path
from reins.platform.types import PlatformConfig


class DescriptorEngine:
    """Generate platform configs from declarative descriptors."""

    def __init__(
        self,
        repo_root: Path,
        hash_store: TemplateHashStore | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.hash_store = hash_store or TemplateHashStore(repo_root)
        self.template_fetcher = TemplateFetcher(
            hash_store=self.hash_store
        )

    def generate(
        self,
        config: PlatformConfig,
        variables: dict[str, str] | None = None,
        conflict_resolver: ConflictResolver | None = None,
    ) -> list[TemplateApplyResult]:
        """Generate platform config files from the descriptor."""
        descriptor = get_descriptor(config.platform_type)
        config_path = self.repo_root / config.config_dir

        if descriptor is None:
            config_path.mkdir(parents=True, exist_ok=True)
            return []

        config_path.mkdir(parents=True, exist_ok=True)
        for subdir in descriptor.subdirs:
            (config_path / subdir).mkdir(parents=True, exist_ok=True)

        file_mapping: dict[str, str] = {
            fm.template_source: (
                str(Path(config.config_dir) / fm.target_path)
            )
            for fm in descriptor.files
        }

        if not file_mapping:
            return []

        return self.template_fetcher.install_templates(
            platform=config,
            repo_root=self.repo_root,
            file_mapping=file_mapping,
            variables=variables or {},
            conflict_resolver=conflict_resolver,
        )

    def check_staleness(
        self,
        config: PlatformConfig,
    ) -> list[tuple[str, str]]:
        """Check which config files are stale, missing, or customized.

        Returns a list of (relative_path, status) tuples where status is one
        of: "missing", "customized", or "stale".
        """
        descriptor = get_descriptor(config.platform_type)
        if descriptor is None:
            return []

        config_path = self.repo_root / config.config_dir
        results: list[tuple[str, str]] = []

        for fm in descriptor.files:
            target = config_path / fm.target_path
            if not target.exists():
                results.append((fm.target_path, "missing"))
                continue

            record = self.hash_store.get(target)
            if record is None:
                # Untracked file — not managed by us
                continue

            current_hash = sha256_path(target)
            if current_hash != record.rendered_hash:
                results.append((fm.target_path, "customized"))
                continue

            # Check if the template source has changed
            template_path = (
                self.template_fetcher.template_root
                / config.template_dirs[-1]
                / fm.template_source
            )
            if template_path.exists():
                if sha256_path(template_path) != record.template_hash:
                    results.append((fm.target_path, "stale"))

        return results
