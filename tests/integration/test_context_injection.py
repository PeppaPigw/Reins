"""Integration test for end-to-end context injection flow.

Tests the complete flow:
1. Import spec from filesystem
2. Event emitted to journal
3. Projection builds from events
4. Query resolves specs
5. Compiler assembles context with token budget
"""

import pytest
from pathlib import Path
import tempfile
import shutil

from reins.context.spec_registrar import SpecRegistrar
from reins.context.spec_projection import ContextSpecProjection, SpecQuery
from reins.context.compiler_v2 import ContextCompilerV2
from reins.context.token_budget import TokenBudget
from reins.kernel.event.journal import EventJournal


@pytest.fixture
def temp_dir():
    """Create temporary directory for test files."""
    temp = Path(tempfile.mkdtemp())
    yield temp
    shutil.rmtree(temp)


@pytest.mark.asyncio
async def test_end_to_end_context_injection(temp_dir):
    """Test complete context injection flow from spec file to compiled context."""

    # Setup: Create spec directory and files
    spec_dir = temp_dir / "specs"
    spec_dir.mkdir()

    backend_dir = spec_dir / "backend"
    backend_dir.mkdir()

    # Create error handling spec
    error_spec = backend_dir / "error-handling.yaml"
    error_spec.write_text(
        """
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
  # Error Handling Guidelines

  Always use structured error types.
  Never catch and ignore exceptions.
  Log errors at boundaries.
"""
    )

    # Create logging spec
    logging_spec = backend_dir / "logging.yaml"
    logging_spec.write_text(
        """
spec_type: standing_law
scope: workspace
precedence: 90
visibility_tier: 1
required_capabilities:
  - fs:write
applicability:
  task_type: backend
  run_phase: null
  actor_type: null
  path_pattern: null
content: |
  # Logging Guidelines

  Use structured logging (JSON format).
  Include trace_id for correlation.
  Don't log sensitive data.
"""
    )

    # Step 1: Import specs via SpecRegistrar
    journal_path = temp_dir / "journal.jsonl"
    journal = EventJournal(journal_path)
    registrar = SpecRegistrar(journal, "test-run")

    spec_ids = await registrar.import_from_directory(spec_dir)

    assert len(spec_ids) == 2
    assert "backend.error-handling" in spec_ids
    assert "backend.logging" in spec_ids

    # Step 2: Build projection from events
    projection = ContextSpecProjection()

    async for event in journal.read_from("test-run"):
        projection.apply_event(event)

    assert projection.count_active_specs() == 2

    # Step 3: Query specs
    query = SpecQuery(
        scope="workspace",
        task_type="backend",
        granted_capabilities={"fs:write"},
        visibility_tier=1,
    )

    resolved = projection.resolve(query)

    assert len(resolved) == 2
    # Should be sorted by precedence (highest first)
    assert resolved[0].spec_id == "backend.error-handling"  # precedence 100
    assert resolved[1].spec_id == "backend.logging"  # precedence 90

    # Step 4: Compile context with token budget
    compiler = ContextCompilerV2(projection)

    budget = TokenBudget.default(total=10_000)

    manifest = compiler.seed_context(
        task_state={"task_type": "backend"},
        granted_capabilities={"fs:write"},
        token_budget=budget,
    )

    # Verify manifest
    assert len(manifest.standing_law) == 2
    assert manifest.standing_law[0].spec_id == "backend.error-handling"
    assert manifest.standing_law[1].spec_id == "backend.logging"
    assert len(manifest.task_contract) == 0  # No task contract specs
    assert len(manifest.spec_shards) == 0  # Empty at seed time

    # Verify token accounting
    assert manifest.total_tokens > 0
    assert manifest.total_tokens <= budget.standing_law
    assert "standing_law" in manifest.token_breakdown

    # Verify audit trail
    assert "backend.error-handling" in manifest.resolved_spec_ids
    assert "backend.logging" in manifest.resolved_spec_ids
    assert len(manifest.dropped_spec_ids) == 0  # Nothing dropped

    # Verify content can be converted to text
    text = manifest.to_text()
    assert "Error Handling Guidelines" in text
    assert "Logging Guidelines" in text


@pytest.mark.asyncio
async def test_token_budget_allocation(temp_dir):
    """Test that token budget is respected and specs are truncated/dropped."""

    spec_dir = temp_dir / "specs"
    spec_dir.mkdir()

    # Create a large spec that will exceed budget
    large_content = "x" * 20_000  # ~5000 tokens
    large_spec = spec_dir / "large.yaml"
    large_spec.write_text(
        f"""
content: |
  {large_content}
"""
    )

    # Create a small spec
    small_spec = spec_dir / "small.yaml"
    small_spec.write_text(
        """
content: |
  Small spec content.
"""
    )

    # Import and build projection
    journal = EventJournal(temp_dir / "journal.jsonl")
    registrar = SpecRegistrar(journal, "test-run")
    await registrar.import_from_directory(spec_dir)

    projection = ContextSpecProjection()
    async for event in journal.read_from("test-run"):
        projection.apply_event(event)

    # Compile with small budget
    compiler = ContextCompilerV2(projection)
    budget = TokenBudget.default(total=1_000)  # Small budget

    manifest = compiler.seed_context(
        granted_capabilities=set(),
        token_budget=budget,
    )

    # Large spec should be truncated or dropped
    # Small spec should be included
    assert manifest.total_tokens <= budget.standing_law

    # Check if any specs were truncated
    truncated = [s for s in manifest.all_sections if s.was_truncated]
    if truncated:
        assert truncated[0].original_token_count > truncated[0].token_count


@pytest.mark.asyncio
async def test_capability_filtering(temp_dir):
    """Test that specs are filtered by required capabilities."""

    spec_dir = temp_dir / "specs"
    spec_dir.mkdir()

    # Spec requiring fs:write
    write_spec = spec_dir / "write.yaml"
    write_spec.write_text(
        """
required_capabilities:
  - fs:write
content: |
  Write operations spec.
"""
    )

    # Spec requiring no capabilities
    read_spec = spec_dir / "read.yaml"
    read_spec.write_text(
        """
required_capabilities: []
content: |
  Read operations spec.
"""
    )

    # Import and build projection
    journal = EventJournal(temp_dir / "journal.jsonl")
    registrar = SpecRegistrar(journal, "test-run")
    await registrar.import_from_directory(spec_dir)

    projection = ContextSpecProjection()
    async for event in journal.read_from("test-run"):
        projection.apply_event(event)

    compiler = ContextCompilerV2(projection)

    # Agent with no capabilities should only see read spec
    manifest_no_caps = compiler.seed_context(
        granted_capabilities=set(),
    )

    spec_ids_no_caps = [s.spec_id for s in manifest_no_caps.all_sections]
    assert "read" in spec_ids_no_caps
    assert "write" not in spec_ids_no_caps

    # Agent with fs:write should see both
    manifest_with_caps = compiler.seed_context(
        granted_capabilities={"fs:write"},
    )

    spec_ids_with_caps = [s.spec_id for s in manifest_with_caps.all_sections]
    assert "read" in spec_ids_with_caps
    assert "write" in spec_ids_with_caps


@pytest.mark.asyncio
async def test_precedence_sorting(temp_dir):
    """Test that specs are sorted by precedence."""

    spec_dir = temp_dir / "specs"
    spec_dir.mkdir()

    # Create specs with different precedence
    for i, precedence in enumerate([50, 200, 100]):
        spec_file = spec_dir / f"spec{i}.yaml"
        spec_file.write_text(
            f"""
precedence: {precedence}
content: |
  Spec with precedence {precedence}
"""
        )

    # Import and build projection
    journal = EventJournal(temp_dir / "journal.jsonl")
    registrar = SpecRegistrar(journal, "test-run")
    await registrar.import_from_directory(spec_dir)

    projection = ContextSpecProjection()
    async for event in journal.read_from("test-run"):
        projection.apply_event(event)

    # Query and verify order
    query = SpecQuery(scope="workspace", granted_capabilities=set())
    resolved = projection.resolve(query)

    # Should be sorted by precedence descending: 200, 100, 50
    assert resolved[0].precedence == 200
    assert resolved[1].precedence == 100
    assert resolved[2].precedence == 50
