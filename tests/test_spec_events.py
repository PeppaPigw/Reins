"""Tests for spec event types."""

import pytest

from reins.kernel.event.spec_events import (
    SpecDeactivatedEvent,
    SpecRegisteredEvent,
    SpecSupersededEvent,
)
from reins.serde import to_primitive


def test_spec_registered_event_creation():
    """Test creating a SpecRegisteredEvent."""
    event = SpecRegisteredEvent(
        spec_id="backend.error-handling",
        spec_type="standing_law",
        scope="workspace",
        content="# Error Handling\n\nUse structured errors...",
        applicability={
            "task_type": "backend",
            "run_phase": None,
            "actor_type": None,
            "path_pattern": None,
        },
        required_capabilities=["fs:write"],
        visibility_tier=1,
        precedence=100,
        source_path=".reins/spec/backend/error-handling.yaml",
        registered_by="system",
        token_count=150,
    )

    assert event.spec_id == "backend.error-handling"
    assert event.spec_type == "standing_law"
    assert event.scope == "workspace"
    assert event.precedence == 100
    assert event.token_count == 150


def test_spec_registered_event_serialization():
    """Test that SpecRegisteredEvent can be serialized to dict."""
    event = SpecRegisteredEvent(
        spec_id="test.spec",
        spec_type="spec_shard",
        scope="workspace",
        content="Test content",
        applicability={},
        required_capabilities=[],
        visibility_tier=0,
        precedence=100,
        token_count=50,
    )

    data = to_primitive(event)

    assert isinstance(data, dict)
    assert data["spec_id"] == "test.spec"
    assert data["spec_type"] == "spec_shard"
    assert data["content"] == "Test content"
    assert data["token_count"] == 50


def test_spec_superseded_event():
    """Test creating a SpecSupersededEvent."""
    event = SpecSupersededEvent(
        spec_id="old.spec",
        superseded_by="new.spec",
        reason="Updated for v2.0",
    )

    assert event.spec_id == "old.spec"
    assert event.superseded_by == "new.spec"
    assert event.reason == "Updated for v2.0"


def test_spec_superseded_event_serialization():
    """Test that SpecSupersededEvent can be serialized."""
    event = SpecSupersededEvent(
        spec_id="old.spec",
        superseded_by="new.spec",
    )

    data = to_primitive(event)

    assert isinstance(data, dict)
    assert data["spec_id"] == "old.spec"
    assert data["superseded_by"] == "new.spec"


def test_spec_deactivated_event():
    """Test creating a SpecDeactivatedEvent."""
    event = SpecDeactivatedEvent(
        spec_id="obsolete.spec",
        reason="No longer applicable",
        deactivated_by="admin",
    )

    assert event.spec_id == "obsolete.spec"
    assert event.reason == "No longer applicable"
    assert event.deactivated_by == "admin"


def test_spec_deactivated_event_serialization():
    """Test that SpecDeactivatedEvent can be serialized."""
    event = SpecDeactivatedEvent(
        spec_id="obsolete.spec",
        deactivated_by="system",
    )

    data = to_primitive(event)

    assert isinstance(data, dict)
    assert data["spec_id"] == "obsolete.spec"
    assert data["deactivated_by"] == "system"


def test_spec_registered_minimal():
    """Test SpecRegisteredEvent with minimal required fields."""
    event = SpecRegisteredEvent(
        spec_id="minimal.spec",
        spec_type="standing_law",
        scope="workspace",
        content="Minimal content",
        applicability={},
        required_capabilities=[],
        visibility_tier=0,
        precedence=100,
    )

    assert event.spec_id == "minimal.spec"
    assert event.source_path is None
    assert event.registered_by == "system"
    assert event.token_count == 0
