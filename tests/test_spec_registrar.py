"""Tests for SpecRegistrar."""

import pytest
from pathlib import Path
import tempfile
import shutil

from reins.context.spec_registrar import SpecRegistrar, SpecValidationError
from reins.kernel.event.journal import EventJournal
from reins.kernel.event.spec_events import SPEC_REGISTERED


@pytest.fixture
def temp_spec_dir():
    """Create a temporary spec directory for testing."""
    temp_dir = Path(tempfile.mkdtemp())
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def temp_journal():
    """Create a temporary journal for testing."""
    temp_dir = Path(tempfile.mkdtemp())
    journal_path = temp_dir / "test.jsonl"
    journal = EventJournal(journal_path)
    yield journal
    shutil.rmtree(temp_dir)


@pytest.mark.asyncio
async def test_import_valid_spec(temp_spec_dir, temp_journal):
    """Test importing a valid spec file."""
    registrar = SpecRegistrar(temp_journal, "test-run")

    # Create a valid spec file
    spec_file = temp_spec_dir / "test.yaml"
    spec_file.write_text("""
spec_type: standing_law
scope: workspace
precedence: 100
visibility_tier: 1
required_capabilities:
  - fs:write
applicability:
  task_type: backend
  run_phase: null
  actor_type: null
  path_pattern: null
content: |
  # Test Spec
  This is test content.
""")

    spec_ids = await registrar.import_from_directory(temp_spec_dir)

    assert len(spec_ids) == 1
    assert spec_ids[0] == "test"

    # Verify event was emitted
    events = []
    async for event in temp_journal.read_from("test-run"):
        events.append(event)

    assert len(events) == 1
    assert events[0].type == SPEC_REGISTERED
    assert events[0].payload["spec_id"] == "test"
    assert events[0].payload["spec_type"] == "standing_law"


@pytest.mark.asyncio
async def test_import_nested_specs(temp_spec_dir, temp_journal):
    """Test importing specs from nested directories."""
    registrar = SpecRegistrar(temp_journal, "test-run")

    # Create nested structure
    backend_dir = temp_spec_dir / "backend"
    backend_dir.mkdir()

    spec1 = backend_dir / "error-handling.yaml"
    spec1.write_text("""
content: |
  # Error Handling
  Test content.
""")

    spec2 = backend_dir / "logging.yaml"
    spec2.write_text("""
content: |
  # Logging
  Test content.
""")

    spec_ids = await registrar.import_from_directory(temp_spec_dir)

    assert len(spec_ids) == 2
    assert "backend.error-handling" in spec_ids
    assert "backend.logging" in spec_ids


@pytest.mark.asyncio
async def test_import_missing_content_field(temp_spec_dir, temp_journal):
    """Test that missing content field raises validation error."""
    registrar = SpecRegistrar(temp_journal, "test-run")

    spec_file = temp_spec_dir / "invalid.yaml"
    spec_file.write_text("""
spec_type: standing_law
scope: workspace
""")

    with pytest.raises(SpecValidationError, match="Missing required field 'content'"):
        await registrar.import_from_directory(temp_spec_dir)


@pytest.mark.asyncio
async def test_import_invalid_spec_type(temp_spec_dir, temp_journal):
    """Test that invalid spec_type raises validation error."""
    registrar = SpecRegistrar(temp_journal, "test-run")

    spec_file = temp_spec_dir / "invalid.yaml"
    spec_file.write_text("""
spec_type: invalid_type
content: |
  Test content
""")

    with pytest.raises(SpecValidationError, match="Invalid spec_type"):
        await registrar.import_from_directory(temp_spec_dir)


@pytest.mark.asyncio
async def test_import_invalid_visibility_tier(temp_spec_dir, temp_journal):
    """Test that invalid visibility_tier raises validation error."""
    registrar = SpecRegistrar(temp_journal, "test-run")

    spec_file = temp_spec_dir / "invalid.yaml"
    spec_file.write_text("""
visibility_tier: 5
content: |
  Test content
""")

    with pytest.raises(SpecValidationError, match="Invalid visibility_tier"):
        await registrar.import_from_directory(temp_spec_dir)


@pytest.mark.asyncio
async def test_import_untrusted_source(temp_spec_dir, temp_journal):
    """Test that untrusted sources are rejected."""
    registrar = SpecRegistrar(temp_journal, "test-run")

    spec_file = temp_spec_dir / "test.yaml"
    spec_file.write_text("""
content: |
  Test content
""")

    with pytest.raises(SpecValidationError, match="Untrusted source"):
        await registrar.import_from_directory(temp_spec_dir, registered_by="user:123")


@pytest.mark.asyncio
async def test_import_nonexistent_directory(temp_journal):
    """Test that nonexistent directory raises error."""
    registrar = SpecRegistrar(temp_journal, "test-run")

    with pytest.raises(SpecValidationError, match="does not exist"):
        await registrar.import_from_directory(Path("/nonexistent"))


@pytest.mark.asyncio
async def test_spec_id_generation(temp_spec_dir, temp_journal):
    """Test spec_id generation from file paths."""
    registrar = SpecRegistrar(temp_journal, "test-run")

    # Create specs with various path structures
    (temp_spec_dir / "backend").mkdir()
    (temp_spec_dir / "backend" / "nested").mkdir()

    spec1 = temp_spec_dir / "simple.yaml"
    spec1.write_text("content: Test")

    spec2 = temp_spec_dir / "backend" / "error-handling.yaml"
    spec2.write_text("content: Test")

    spec3 = temp_spec_dir / "backend" / "nested" / "deep-spec.yaml"
    spec3.write_text("content: Test")

    spec_ids = await registrar.import_from_directory(temp_spec_dir)

    assert "simple" in spec_ids
    assert "backend.error-handling" in spec_ids
    assert "backend.nested.deep-spec" in spec_ids


@pytest.mark.asyncio
async def test_import_with_defaults(temp_spec_dir, temp_journal):
    """Test that default values are applied correctly."""
    registrar = SpecRegistrar(temp_journal, "test-run")

    # Minimal spec with only required field
    spec_file = temp_spec_dir / "minimal.yaml"
    spec_file.write_text("""
content: |
  Minimal spec content
""")

    spec_ids = await registrar.import_from_directory(temp_spec_dir)

    # Verify event has default values
    events = []
    async for event in temp_journal.read_from("test-run"):
        events.append(event)

    payload = events[0].payload
    assert payload["spec_type"] == "standing_law"
    assert payload["scope"] == "workspace"
    assert payload["precedence"] == 100
    assert payload["visibility_tier"] == 1
    assert payload["required_capabilities"] == []
    assert payload["applicability"] == {}


@pytest.mark.asyncio
async def test_token_count_estimation(temp_spec_dir, temp_journal):
    """Test that token count is estimated correctly."""
    registrar = SpecRegistrar(temp_journal, "test-run")

    # Create spec with known content length
    content = "x" * 400  # 400 chars = ~100 tokens
    spec_file = temp_spec_dir / "test.yaml"
    spec_file.write_text(f"""
content: |
  {content}
""")

    await registrar.import_from_directory(temp_spec_dir)

    events = []
    async for event in temp_journal.read_from("test-run"):
        events.append(event)

    token_count = events[0].payload["token_count"]
    assert token_count == 100  # 400 / 4
