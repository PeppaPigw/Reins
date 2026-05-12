from __future__ import annotations

from reins.kernel.event.schema.registry import UpcasterRegistry


def test_register_and_upcast_v1_to_v2():
    registry = UpcasterRegistry()
    registry.set_current_version("task.created", 2)
    registry.register("task.created", 1, lambda p: {**p, "priority": "medium"})

    payload, version = registry.upcast("task.created", {"title": "foo"}, 1)
    assert payload == {"title": "foo", "priority": "medium"}
    assert version == 2


def test_chained_upcast_v1_to_v3():
    registry = UpcasterRegistry()
    registry.set_current_version("task.created", 3)
    registry.register("task.created", 1, lambda p: {**p, "priority": "medium"})
    registry.register("task.created", 2, lambda p: {**p, "tags": []})

    payload, version = registry.upcast("task.created", {"title": "foo"}, 1)
    assert payload == {"title": "foo", "priority": "medium", "tags": []}
    assert version == 3


def test_passthrough_when_no_upcaster_registered():
    registry = UpcasterRegistry()
    registry.set_current_version("task.created", 3)

    payload, version = registry.upcast("task.created", {"title": "foo"}, 1)
    assert payload == {"title": "foo"}
    assert version == 3


def test_needs_upcast_true_when_behind():
    registry = UpcasterRegistry()
    registry.set_current_version("task.created", 2)
    assert registry.needs_upcast("task.created", 1) is True


def test_needs_upcast_false_when_current():
    registry = UpcasterRegistry()
    registry.set_current_version("task.created", 2)
    assert registry.needs_upcast("task.created", 2) is False


def test_get_current_version_default():
    registry = UpcasterRegistry()
    assert registry.get_current_version("unknown.event") == 1


def test_get_current_version_after_set():
    registry = UpcasterRegistry()
    registry.set_current_version("task.created", 5)
    assert registry.get_current_version("task.created") == 5
