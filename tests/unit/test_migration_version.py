from __future__ import annotations

import pytest

from reins.migration.types import Migration, MigrationManifest
from reins.migration.version import SemanticVersion, sort_versions, versions_in_range


def test_semantic_version_ordering_and_sorting() -> None:
    versions = ["1.0.0", "0.10.0", "0.2.5", "0.2.0"]

    sorted_versions = sort_versions(versions)

    assert sorted_versions == ["0.2.0", "0.2.5", "0.10.0", "1.0.0"]
    assert SemanticVersion.parse("1.2.3") > SemanticVersion.parse("1.2.2")


def test_versions_in_range_is_exclusive_of_from_and_inclusive_of_to() -> None:
    versions = ["0.1.0", "0.2.0", "0.3.0"]

    selected = versions_in_range(versions, from_version="0.1.0", to_version="0.3.0")

    assert selected == ["0.2.0", "0.3.0"]


def test_migration_manifest_models_validate_required_fields() -> None:
    manifest = MigrationManifest(
        version="0.1.0",
        migrations=[
            Migration(
                type="rename",
                from_path="old.txt",
                to_path="new.txt",
                description="Rename the file",
            )
        ],
    )

    assert manifest.version == "0.1.0"
    assert manifest.migrations[0].type == "rename"


def test_safe_file_delete_requires_allowed_hashes() -> None:
    with pytest.raises(ValueError, match="allowed_hashes"):
        Migration(
            type="safe-file-delete",
            from_path="delete-me.txt",
            to_path=None,
            allowed_hashes=[],
            description="Delete only known template content",
        )
