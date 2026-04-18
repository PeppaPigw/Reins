"""Spec exporter - exports specs to YAML manifest files.

Exports ContextSpecProjection to `.reins/spec/` directory structure.
These are derived artifacts for platform interop and human review.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from reins.context.spec_projection import ContextSpecProjection, SpecDescriptor


class SpecExporter:
    """Exports specs to YAML manifest files.

    Reads from ContextSpecProjection and writes to `.reins/spec/` directory.
    """

    def __init__(
        self,
        projection: ContextSpecProjection,
        export_dir: Path,
    ) -> None:
        """Initialize spec exporter.

        Args:
            projection: Spec projection to export from
            export_dir: Base directory for exports (e.g., `.reins/spec/`)
        """
        self._projection = projection
        self._export_dir = export_dir

    def export_all(self) -> list[Path]:
        """Export all active specs to YAML files.

        Returns:
            List of paths to exported files
        """
        exported_files: list[Path] = []

        # Get all active specs
        specs = self._projection.list_active()

        for spec in specs:
            # Get full content
            content = self._projection.get_content(spec.spec_id)
            if content:
                file_path = self._export_spec(content.descriptor, content.content)
                exported_files.append(file_path)

        return exported_files

    def export_spec(self, spec_id: str) -> Path | None:
        """Export a single spec to YAML file.

        Args:
            spec_id: ID of spec to export

        Returns:
            Path to exported file, or None if spec not found
        """
        content = self._projection.get_content(spec_id)
        if not content:
            return None

        return self._export_spec(content.descriptor, content.content)

    def _export_spec(self, descriptor: SpecDescriptor, content: str) -> Path:
        """Export spec to YAML file.

        Args:
            descriptor: Spec descriptor
            content: Spec content

        Returns:
            Path to exported file
        """
        # Determine file path based on spec_id
        # Format: {category}/{name}.yaml
        parts = descriptor.spec_id.split(".", 1)
        if len(parts) == 2:
            category, name = parts
        else:
            category = "general"
            name = descriptor.spec_id

        # Create category directory
        category_dir = self._export_dir / category
        category_dir.mkdir(parents=True, exist_ok=True)

        # Create YAML manifest
        manifest = {
            "spec_id": descriptor.spec_id,
            "spec_type": descriptor.spec_type,
            "scope": descriptor.scope,
            "precedence": descriptor.precedence,
            "visibility_tier": descriptor.visibility_tier,
            "required_capabilities": descriptor.required_capabilities,
            "applicability": descriptor.applicability,
            "content": content,
        }

        # Add optional fields
        if descriptor.source_path:
            manifest["source_path"] = descriptor.source_path

        # Write YAML file
        file_path = category_dir / f"{name}.yaml"
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(manifest, f, default_flow_style=False, allow_unicode=True)

        return file_path

    def create_index(self, category: str | None = None) -> Path:
        """Create index.md file for a category.

        Args:
            category: Category to create index for (None = root)

        Returns:
            Path to index file
        """
        if category:
            index_dir = self._export_dir / category
            specs = [
                s
                for s in self._projection.list_active()
                if s.spec_id.startswith(f"{category}.")
            ]
        else:
            index_dir = self._export_dir
            specs = self._projection.list_active()

        index_dir.mkdir(parents=True, exist_ok=True)

        # Create index content
        lines = [
            f"# Specs: {category or 'All'}\n",
            "\n",
            "## Available Specs\n",
            "\n",
        ]

        # Group by spec_type
        by_type: dict[str, list[SpecDescriptor]] = {}
        for spec in specs:
            if spec.spec_type not in by_type:
                by_type[spec.spec_type] = []
            by_type[spec.spec_type].append(spec)

        for spec_type, type_specs in sorted(by_type.items()):
            lines.append(f"### {spec_type}\n\n")
            for spec in sorted(type_specs, key=lambda s: s.spec_id):
                # Get file path
                parts = spec.spec_id.split(".", 1)
                if len(parts) == 2:
                    _, name = parts
                else:
                    name = spec.spec_id

                lines.append(f"- [{spec.spec_id}]({name}.yaml)\n")
                if spec.applicability:
                    lines.append(f"  - Applicability: {spec.applicability}\n")

            lines.append("\n")

        # Write index
        index_path = index_dir / "index.md"
        with open(index_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        return index_path

    def cleanup_orphans(self) -> list[Path]:
        """Remove YAML files for specs that no longer exist.

        Returns:
            List of paths that were removed
        """
        removed: list[Path] = []

        if not self._export_dir.exists():
            return removed

        # Get all active spec IDs
        active_ids = {s.spec_id for s in self._projection.list_active()}

        # Find all YAML files
        for yaml_file in self._export_dir.rglob("*.yaml"):
            # Read spec_id from file
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    spec_id = data.get("spec_id")

                    if spec_id and spec_id not in active_ids:
                        yaml_file.unlink()
                        removed.append(yaml_file)
            except Exception:
                # Skip files that can't be read
                pass

        return removed
