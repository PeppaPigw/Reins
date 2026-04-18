"""Tests for ContextSpecProjection."""

import pytest

from reins.context.spec_projection import ContextSpecProjection, SpecDescriptor
from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.event.spec_events import (
    SPEC_DEACTIVATED,
    SPEC_REGISTERED,
    SPEC_SUPERSEDED,
)
from reins.kernel.types import Actor


def test_projection_starts_empty():
    """Test that projection starts with no specs."""
    projection = ContextSpecProjection()
    assert projection.count_specs() == 0
    assert projection.count_active_specs() == 0


def test_apply_spec_registered_event():
    """Test applying SpecRegisteredEvent to projection."""
    projection = ContextSpecProjection()

    event = EventEnvelope(
        run_id="test-run",
        actor=Actor.SYSTEM,
        type=SPEC_REGISTERED,
        payload={
            "spec_id": "backend.error-handling",
            "spec_type": "standing_law",
            "scope": "workspace",
            "content": "# Error Handling\n\nUse structured errors...",
            "applicability": {"task_type": "backend"},
            "required_capabilities": ["fs:write"],
            "visibility_tier": 1,
            "precedence": 100,
            "source_path": ".reins/spec/backend/error-handling.yaml",
            "registered_by": "system",
            "token_count": 150,
        },
    )

    projection.apply_event(event)

    assert projection.count_specs() == 1
    assert projection.count_active_specs() == 1

    spec = projection.get_spec("backend.error-handling")
    assert spec is not None
    assert spec.spec_id == "backend.error-handling"
    assert spec.spec_type == "standing_law"
    assert spec.scope == "workspace"
    assert spec.precedence == 100
    assert spec.token_count == 150
    assert not spec.is_superseded
    assert not spec.is_deactivated


def test_get_spec_content():
    """Test retrieving full spec content."""
    projection = ContextSpecProjection()

    content_text = "# Test Spec\n\nThis is test content."

    event = EventEnvelope(
        run_id="test-run",
        actor=Actor.SYSTEM,
        type=SPEC_REGISTERED,
        payload={
            "spec_id": "test.spec",
            "spec_type": "standing_law",
            "scope": "workspace",
            "content": content_text,
            "applicability": {},
            "required_capabilities": [],
            "visibility_tier": 0,
            "precedence": 100,
            "source_path": None,
            "registered_by": "system",
            "token_count": 50,
        },
    )

    projection.apply_event(event)

    spec_content = projection.get_spec_content("test.spec")
    assert spec_content is not None
    assert spec_content.spec_id == "test.spec"
    assert spec_content.content == content_text
    assert spec_content.descriptor.spec_id == "test.spec"


def test_apply_spec_superseded_event():
    """Test superseding a spec."""
    projection = ContextSpecProjection()

    # Register original spec
    register_event = EventEnvelope(
        run_id="test-run",
        actor=Actor.SYSTEM,
        type=SPEC_REGISTERED,
        payload={
            "spec_id": "old.spec",
            "spec_type": "standing_law",
            "scope": "workspace",
            "content": "Old content",
            "applicability": {},
            "required_capabilities": [],
            "visibility_tier": 0,
            "precedence": 100,
            "source_path": None,
            "registered_by": "system",
            "token_count": 50,
        },
    )
    projection.apply_event(register_event)

    # Supersede it
    supersede_event = EventEnvelope(
        run_id="test-run",
        actor=Actor.SYSTEM,
        type=SPEC_SUPERSEDED,
        payload={
            "spec_id": "old.spec",
            "superseded_by": "new.spec",
            "reason": "Updated for v2.0",
        },
    )
    projection.apply_event(supersede_event)

    spec = projection.get_spec("old.spec")
    assert spec is not None
    assert spec.is_superseded
    assert spec.superseded_by == "new.spec"

    # Count should include superseded, but active count should not
    assert projection.count_specs() == 1
    assert projection.count_active_specs() == 0


def test_apply_spec_deactivated_event():
    """Test deactivating a spec."""
    projection = ContextSpecProjection()

    # Register spec
    register_event = EventEnvelope(
        run_id="test-run",
        actor=Actor.SYSTEM,
        type=SPEC_REGISTERED,
        payload={
            "spec_id": "obsolete.spec",
            "spec_type": "standing_law",
            "scope": "workspace",
            "content": "Obsolete content",
            "applicability": {},
            "required_capabilities": [],
            "visibility_tier": 0,
            "precedence": 100,
            "source_path": None,
            "registered_by": "system",
            "token_count": 50,
        },
    )
    projection.apply_event(register_event)

    # Deactivate it
    deactivate_event = EventEnvelope(
        run_id="test-run",
        actor=Actor.SYSTEM,
        type=SPEC_DEACTIVATED,
        payload={
            "spec_id": "obsolete.spec",
            "reason": "No longer applicable",
            "deactivated_by": "admin",
        },
    )
    projection.apply_event(deactivate_event)

    spec = projection.get_spec("obsolete.spec")
    assert spec is not None
    assert spec.is_deactivated
    assert spec.deactivated_reason == "No longer applicable"

    assert projection.count_specs() == 1
    assert projection.count_active_specs() == 0


def test_list_specs_by_scope():
    """Test filtering specs by scope."""
    projection = ContextSpecProjection()

    # Register workspace spec
    workspace_event = EventEnvelope(
        run_id="test-run",
        actor=Actor.SYSTEM,
        type=SPEC_REGISTERED,
        payload={
            "spec_id": "workspace.spec",
            "spec_type": "standing_law",
            "scope": "workspace",
            "content": "Workspace content",
            "applicability": {},
            "required_capabilities": [],
            "visibility_tier": 0,
            "precedence": 100,
            "source_path": None,
            "registered_by": "system",
            "token_count": 50,
        },
    )
    projection.apply_event(workspace_event)

    # Register task spec
    task_event = EventEnvelope(
        run_id="test-run",
        actor=Actor.SYSTEM,
        type=SPEC_REGISTERED,
        payload={
            "spec_id": "task.spec",
            "spec_type": "task_contract",
            "scope": "task:123",
            "content": "Task content",
            "applicability": {},
            "required_capabilities": [],
            "visibility_tier": 0,
            "precedence": 100,
            "source_path": None,
            "registered_by": "system",
            "token_count": 50,
        },
    )
    projection.apply_event(task_event)

    # List all specs
    all_specs = projection.list_specs()
    assert len(all_specs) == 2

    # List workspace specs only
    workspace_specs = projection.list_specs(scope="workspace")
    assert len(workspace_specs) == 1
    assert workspace_specs[0].spec_id == "workspace.spec"

    # List task specs only
    task_specs = projection.list_specs(scope="task:123")
    assert len(task_specs) == 1
    assert task_specs[0].spec_id == "task.spec"


def test_list_specs_excludes_superseded_by_default():
    """Test that list_specs excludes superseded specs by default."""
    projection = ContextSpecProjection()

    # Register and supersede a spec
    register_event = EventEnvelope(
        run_id="test-run",
        actor=Actor.SYSTEM,
        type=SPEC_REGISTERED,
        payload={
            "spec_id": "old.spec",
            "spec_type": "standing_law",
            "scope": "workspace",
            "content": "Old",
            "applicability": {},
            "required_capabilities": [],
            "visibility_tier": 0,
            "precedence": 100,
            "source_path": None,
            "registered_by": "system",
            "token_count": 50,
        },
    )
    projection.apply_event(register_event)

    supersede_event = EventEnvelope(
        run_id="test-run",
        actor=Actor.SYSTEM,
        type=SPEC_SUPERSEDED,
        payload={"spec_id": "old.spec", "superseded_by": "new.spec"},
    )
    projection.apply_event(supersede_event)

    # Default: exclude superseded
    specs = projection.list_specs()
    assert len(specs) == 0

    # Explicit: include superseded
    specs_with_superseded = projection.list_specs(include_superseded=True)
    assert len(specs_with_superseded) == 1


def test_list_specs_excludes_deactivated_by_default():
    """Test that list_specs excludes deactivated specs by default."""
    projection = ContextSpecProjection()

    # Register and deactivate a spec
    register_event = EventEnvelope(
        run_id="test-run",
        actor=Actor.SYSTEM,
        type=SPEC_REGISTERED,
        payload={
            "spec_id": "obsolete.spec",
            "spec_type": "standing_law",
            "scope": "workspace",
            "content": "Obsolete",
            "applicability": {},
            "required_capabilities": [],
            "visibility_tier": 0,
            "precedence": 100,
            "source_path": None,
            "registered_by": "system",
            "token_count": 50,
        },
    )
    projection.apply_event(register_event)

    deactivate_event = EventEnvelope(
        run_id="test-run",
        actor=Actor.SYSTEM,
        type=SPEC_DEACTIVATED,
        payload={"spec_id": "obsolete.spec", "deactivated_by": "system"},
    )
    projection.apply_event(deactivate_event)

    # Default: exclude deactivated
    specs = projection.list_specs()
    assert len(specs) == 0

    # Explicit: include deactivated
    specs_with_deactivated = projection.list_specs(include_deactivated=True)
    assert len(specs_with_deactivated) == 1


def test_get_nonexistent_spec():
    """Test getting a spec that doesn't exist."""
    projection = ContextSpecProjection()
    spec = projection.get_spec("nonexistent")
    assert spec is None

    content = projection.get_spec_content("nonexistent")
    assert content is None
