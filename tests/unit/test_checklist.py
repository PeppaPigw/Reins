from __future__ import annotations

from pathlib import Path

from reins.context.checklist import ChecklistParser, validate_layer_structure
from reins.context.types import SpecLayer


def test_checklist_parser_supports_markdown_links_and_nested_items(tmp_path: Path) -> None:
    content = """# Backend Specifications

## Pre-Development Checklist

- [ ] Review backend layer
  - [x] [Directory Structure](directory-structure.md) - Understand the file layout
  - [ ] [Error Handling](error-handling.yaml) - Understand error patterns
"""

    checklist = ChecklistParser.parse_content(content, tmp_path)
    assert checklist is not None
    assert len(checklist.items) == 1
    assert checklist.items[0].target is None
    assert len(checklist.items[0].children) == 2
    assert checklist.items[0].children[0].target == "directory-structure.md"
    assert checklist.items[0].children[1].target == "error-handling.yaml"


def test_checklist_validation_uses_read_specs_for_nested_completion(tmp_path: Path) -> None:
    (tmp_path / "directory-structure.md").write_text("# Directory Structure\n", encoding="utf-8")
    (tmp_path / "error-handling.yaml").write_text("content: ok\n", encoding="utf-8")
    content = """# Backend Specifications

## Pre-Development Checklist

- [ ] Review backend layer
  - [x] [Directory Structure](directory-structure.md) - Understand the file layout
  - [ ] [Error Handling](error-handling.yaml) - Understand error patterns
"""

    checklist = ChecklistParser.parse_content(content, tmp_path)
    assert checklist is not None

    incomplete = checklist.validate_completion({"directory-structure.md"})
    assert incomplete.is_complete is False
    assert "error-handling.yaml - Understand error patterns" in incomplete.incomplete_items

    complete = checklist.validate_completion({"directory-structure.md", "error-handling.yaml"})
    assert complete.is_complete is True
    assert complete.completed_count == 3


def test_validate_layer_structure_reports_missing_and_custom_layers(tmp_path: Path) -> None:
    (tmp_path / "backend").mkdir()
    (tmp_path / "guides").mkdir()
    (tmp_path / "custom-layer").mkdir()

    result = validate_layer_structure(
        tmp_path,
        required_layers=[SpecLayer.BACKEND, SpecLayer.UNIT_TEST, SpecLayer.GUIDES],
    )

    assert result.is_valid is False
    assert result.missing_layers == ["unit-test"]
    assert result.custom_layers == ["custom-layer"]
