"""Shared types for markdown-based spec guidance."""

from __future__ import annotations

from enum import Enum


class SpecLayer(str, Enum):
    """Supported spec layer types."""

    BACKEND = "backend"
    FRONTEND = "frontend"
    UNIT_TEST = "unit-test"
    INTEGRATION_TEST = "integration-test"
    GUIDES = "guides"
    CUSTOM = "custom"

    @classmethod
    def from_name(cls, value: str) -> "SpecLayer":
        """Resolve a layer name, falling back to ``CUSTOM``."""
        normalized = value.strip().lower()
        for layer in cls:
            if layer.value == normalized:
                return layer
        return cls.CUSTOM

    @classmethod
    def standard_layers(cls) -> tuple["SpecLayer", ...]:
        """Return the standard non-custom layer set."""
        return (
            cls.BACKEND,
            cls.FRONTEND,
            cls.UNIT_TEST,
            cls.INTEGRATION_TEST,
            cls.GUIDES,
        )

    @classmethod
    def default_layers_for_project_type(cls, project_type: str) -> tuple["SpecLayer", ...]:
        """Return the default layers for a detected project type."""
        normalized = project_type.strip().lower()
        if normalized == "frontend":
            return (
                cls.FRONTEND,
                cls.UNIT_TEST,
                cls.INTEGRATION_TEST,
                cls.GUIDES,
            )
        if normalized == "fullstack":
            return (
                cls.BACKEND,
                cls.FRONTEND,
                cls.UNIT_TEST,
                cls.INTEGRATION_TEST,
                cls.GUIDES,
            )
        return (
            cls.BACKEND,
            cls.UNIT_TEST,
            cls.INTEGRATION_TEST,
            cls.GUIDES,
        )


LAYER_PRIORITY: dict[SpecLayer, float] = {
    SpecLayer.BACKEND: 120.0,
    SpecLayer.FRONTEND: 118.0,
    SpecLayer.UNIT_TEST: 108.0,
    SpecLayer.INTEGRATION_TEST: 104.0,
    SpecLayer.GUIDES: 80.0,
    SpecLayer.CUSTOM: 96.0,
}


def normalize_layer_name(value: str) -> str:
    """Normalize a layer name to its canonical string form."""
    return SpecLayer.from_name(value).value if value.strip() else SpecLayer.CUSTOM.value
