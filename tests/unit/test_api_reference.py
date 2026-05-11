"""Tests for API reference generation from type annotations."""

from __future__ import annotations

import dataclasses
import enum
from pathlib import Path

from reins.dx.api_reference import (
    APIReferenceGenerator,
    AttributeDoc,
    ClassDoc,
    FunctionDoc,
    ModuleDoc,
    ParameterDoc,
)


# --- Test fixtures ---


class SampleEnum(str, enum.Enum):
    """A sample enum for testing."""

    alpha = "alpha"
    beta = "beta"


@dataclasses.dataclass
class SampleDataclass:
    """A sample dataclass for testing."""

    name: str
    count: int = 0
    tags: list[str] = dataclasses.field(default_factory=list)

    def process(self, value: int) -> str:
        """Process a value."""
        return str(value)


async def sample_async_function(x: int, y: str = "default") -> bool:
    """An async function for testing."""
    return True


def sample_sync_function(path: Path) -> list[str]:
    """A sync function for testing."""
    return []


# --- Tests ---


class TestDocumentModule:
    def test_document_module_extracts_classes(self) -> None:
        gen = APIReferenceGenerator()
        doc = gen.document_module("reins.workflow.state_machine")
        class_names = [c.name for c in doc.classes]
        assert "WorkflowState" in class_names
        assert "WorkflowStateMachine" in class_names

    def test_document_module_extracts_functions(self) -> None:
        gen = APIReferenceGenerator()
        doc = gen.document_module("reins.kernel.event.envelope")
        func_names = [f.name for f in doc.functions]
        assert "compute_checksum" in func_names
        assert "event_to_dict" in func_names

    def test_document_module_has_docstring(self) -> None:
        gen = APIReferenceGenerator()
        doc = gen.document_module("reins.workflow.state_machine")
        assert doc.docstring is not None
        assert "state machine" in doc.docstring.lower()


class TestDocumentClass:
    def test_document_class_gets_methods(self) -> None:
        gen = APIReferenceGenerator()
        doc = gen.document_class(SampleDataclass)
        method_names = [m.name for m in doc.methods]
        assert "process" in method_names

    def test_document_class_detects_dataclass(self) -> None:
        gen = APIReferenceGenerator()
        doc = gen.document_class(SampleDataclass)
        assert doc.is_dataclass is True
        assert doc.is_enum is False

    def test_document_class_detects_enum(self) -> None:
        gen = APIReferenceGenerator()
        doc = gen.document_class(SampleEnum)
        assert doc.is_enum is True
        assert doc.is_dataclass is False

    def test_document_class_gets_attributes(self) -> None:
        gen = APIReferenceGenerator()
        doc = gen.document_class(SampleDataclass)
        attr_names = [a.name for a in doc.attributes]
        assert "name" in attr_names
        assert "count" in attr_names

    def test_document_class_gets_bases(self) -> None:
        gen = APIReferenceGenerator()
        doc = gen.document_class(SampleEnum)
        assert "str" in doc.bases or "Enum" in doc.bases


class TestDocumentFunction:
    def test_document_function_gets_signature(self) -> None:
        gen = APIReferenceGenerator()
        doc = gen.document_function(sample_sync_function)
        assert "path" in doc.signature

    def test_document_function_gets_parameters(self) -> None:
        gen = APIReferenceGenerator()
        doc = gen.document_function(sample_async_function)
        param_names = [p.name for p in doc.parameters]
        assert "x" in param_names
        assert "y" in param_names

    def test_document_function_detects_async(self) -> None:
        gen = APIReferenceGenerator()
        doc = gen.document_function(sample_async_function)
        assert doc.is_async is True

    def test_document_function_gets_return_type(self) -> None:
        gen = APIReferenceGenerator()
        doc = gen.document_function(sample_async_function)
        assert doc.return_type == "bool"

    def test_document_function_gets_defaults(self) -> None:
        gen = APIReferenceGenerator()
        doc = gen.document_function(sample_async_function)
        y_param = next(p for p in doc.parameters if p.name == "y")
        assert y_param.default == "'default'"


class TestRenderMarkdown:
    def test_render_module_markdown_has_headers(self) -> None:
        gen = APIReferenceGenerator()
        doc = gen.document_module("reins.workflow.state_machine")
        md = gen.render_module_markdown(doc)
        assert "# state_machine" in md
        assert "## WorkflowState" in md or "## WorkflowStateMachine" in md

    def test_render_class_markdown_has_attributes(self) -> None:
        gen = APIReferenceGenerator()
        cls_doc = gen.document_class(SampleDataclass)
        md = gen.render_class_markdown(cls_doc)
        assert "### Attributes" in md
        assert "`name`" in md
        assert "`count`" in md


class TestGeneratePackage:
    def test_generate_for_package_creates_files(self, tmp_path: Path) -> None:
        gen = APIReferenceGenerator()
        output_dir = tmp_path / "api_docs"
        files = gen.generate_for_package("reins.workflow", output_dir)
        assert len(files) > 0
        for f in files:
            assert f.exists()
            content = f.read_text()
            assert content.startswith("#")

    def test_generate_index_creates_links(self, tmp_path: Path) -> None:
        gen = APIReferenceGenerator()
        modules = [
            ModuleDoc(module_path="reins.kernel.event.envelope", docstring="Event envelope."),
            ModuleDoc(module_path="reins.workflow.state_machine", docstring="State machine."),
        ]
        index_path = tmp_path / "index.md"
        gen.generate_index(modules, index_path)
        assert index_path.exists()
        content = index_path.read_text()
        assert "reins.kernel.event.envelope" in content
        assert "reins.workflow.state_machine" in content
        assert ".md" in content
