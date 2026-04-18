"""Tests for checklist parser."""

from pathlib import Path

import pytest

from reins.context.checklist import ChecklistItem, Checklist, ChecklistParser, create_checklist_template


def test_checklist_item_str():
    """Test ChecklistItem string representation."""
    item = ChecklistItem(checked=False, spec_file="error-handling.md")
    assert str(item) == "- [ ] error-handling.md"

    item_with_desc = ChecklistItem(
        checked=True,
        spec_file="conventions.md",
        description="Code style and naming"
    )
    assert str(item_with_desc) == "- [x] conventions.md - Code style and naming"


def test_checklist_validate(tmp_path):
    """Test checklist validation."""
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()

    # Create some spec files
    (spec_dir / "error-handling.md").write_text("# Error Handling")
    (spec_dir / "conventions.md").write_text("# Conventions")

    # Create checklist with existing and missing files
    checklist = Checklist(
        spec_dir=spec_dir,
        items=[
            ChecklistItem(checked=False, spec_file="error-handling.md"),
            ChecklistItem(checked=False, spec_file="conventions.md"),
            ChecklistItem(checked=False, spec_file="missing.md"),
        ]
    )

    is_valid, missing = checklist.validate()
    assert not is_valid
    assert missing == ["missing.md"]


def test_checklist_get_required_specs(tmp_path):
    """Test getting required spec paths."""
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()

    # Create spec files
    (spec_dir / "error-handling.md").write_text("# Error Handling")
    (spec_dir / "conventions.md").write_text("# Conventions")

    checklist = Checklist(
        spec_dir=spec_dir,
        items=[
            ChecklistItem(checked=False, spec_file="error-handling.md"),
            ChecklistItem(checked=False, spec_file="conventions.md"),
            ChecklistItem(checked=False, spec_file="missing.md"),
        ]
    )

    specs = checklist.get_required_specs()
    assert len(specs) == 2
    assert spec_dir / "error-handling.md" in specs
    assert spec_dir / "conventions.md" in specs
    assert spec_dir / "missing.md" not in specs


def test_parse_checklist():
    """Test parsing checklist from index.md content."""
    content = """# Backend Specifications

## Pre-Development Checklist

Before starting backend work, read:

- [ ] `error-handling.md` - Error handling patterns
- [x] `conventions.md` - Code style
- [ ] api-design.md

## Other Section

Some other content.
"""

    checklist = ChecklistParser.parse_content(content, Path("/tmp/spec"))
    assert checklist is not None
    assert len(checklist.items) == 3

    assert checklist.items[0].checked is False
    assert checklist.items[0].spec_file == "error-handling.md"
    assert checklist.items[0].description == "Error handling patterns"

    assert checklist.items[1].checked is True
    assert checklist.items[1].spec_file == "conventions.md"
    assert checklist.items[1].description == "Code style"

    assert checklist.items[2].checked is False
    assert checklist.items[2].spec_file == "api-design.md"
    assert checklist.items[2].description is None


def test_parse_checklist_no_checklist():
    """Test parsing when no checklist section exists."""
    content = """# Backend Specifications

## Overview

Some content without a checklist.
"""

    checklist = ChecklistParser.parse_content(content, Path("/tmp/spec"))
    assert checklist is None


def test_parse_checklist_case_insensitive():
    """Test parsing with different case variations."""
    content = """# Backend Specifications

## pre-development checklist

- [ ] `error-handling.md`
"""

    checklist = ChecklistParser.parse_content(content, Path("/tmp/spec"))
    assert checklist is not None
    assert len(checklist.items) == 1


def test_parse_checklist_stops_at_next_section():
    """Test parsing stops at next section header."""
    content = """# Backend Specifications

## Pre-Development Checklist

- [ ] `error-handling.md`
- [ ] `conventions.md`

## Another Section

- [ ] `this-should-not-be-included.md`
"""

    checklist = ChecklistParser.parse_content(content, Path("/tmp/spec"))
    assert checklist is not None
    assert len(checklist.items) == 2
    assert all(item.spec_file != "this-should-not-be-included.md" for item in checklist.items)


def test_find_checklists(tmp_path):
    """Test finding checklists in spec directory structure."""
    spec_root = tmp_path / "spec"
    spec_root.mkdir()

    # Create backend spec with checklist
    backend_dir = spec_root / "backend"
    backend_dir.mkdir()
    (backend_dir / "index.md").write_text("""# Backend Specifications

## Pre-Development Checklist

- [ ] `error-handling.md`
""")

    # Create frontend spec with checklist
    frontend_dir = spec_root / "frontend"
    frontend_dir.mkdir()
    (frontend_dir / "index.md").write_text("""# Frontend Specifications

## Pre-Development Checklist

- [ ] `component-patterns.md`
""")

    # Create guides without checklist
    guides_dir = spec_root / "guides"
    guides_dir.mkdir()
    (guides_dir / "index.md").write_text("""# Development Guides

No checklist here.
""")

    checklists = ChecklistParser.find_checklists(spec_root)
    assert len(checklists) == 2
    assert "backend" in checklists
    assert "frontend" in checklists
    assert "guides" not in checklists

    assert len(checklists["backend"].items) == 1
    assert checklists["backend"].items[0].spec_file == "error-handling.md"

    assert len(checklists["frontend"].items) == 1
    assert checklists["frontend"].items[0].spec_file == "component-patterns.md"


def test_create_checklist_template():
    """Test creating checklist template."""
    template = create_checklist_template(
        "backend",
        ["error-handling.md", "conventions.md", "api-design.md"]
    )

    assert "# Backend Specifications" in template
    assert "## Pre-Development Checklist" in template
    assert "Before starting backend work, read:" in template
    assert "- [ ] `error-handling.md`" in template
    assert "- [ ] `conventions.md`" in template
    assert "- [ ] `api-design.md`" in template


def test_parse_from_file(tmp_path):
    """Test parsing checklist from actual file."""
    spec_dir = tmp_path / "spec" / "backend"
    spec_dir.mkdir(parents=True)

    index_path = spec_dir / "index.md"
    index_path.write_text("""# Backend Specifications

## Pre-Development Checklist

- [ ] `error-handling.md`
- [x] `conventions.md` - Code style
""")

    checklist = ChecklistParser.parse(index_path)
    assert checklist is not None
    assert len(checklist.items) == 2
    assert checklist.spec_dir == spec_dir


def test_parse_nonexistent_file():
    """Test parsing nonexistent file returns None."""
    checklist = ChecklistParser.parse(Path("/nonexistent/index.md"))
    assert checklist is None
