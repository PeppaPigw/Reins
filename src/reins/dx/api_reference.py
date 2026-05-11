"""API reference generation from Python type annotations and docstrings."""

from __future__ import annotations

import dataclasses
import enum
import importlib
import inspect
import pkgutil
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class ParameterDoc:
    """Documentation for a single function parameter."""

    name: str
    type_annotation: str | None = None
    default: str | None = None
    kind: str = "positional_or_keyword"


@dataclass
class AttributeDoc:
    """Documentation for a class attribute."""

    name: str
    type_annotation: str | None = None
    default: str | None = None


@dataclass
class FunctionDoc:
    """Documentation for a function or method."""

    name: str
    docstring: str | None = None
    signature: str = ""
    parameters: list[ParameterDoc] = field(default_factory=list)
    return_type: str | None = None
    is_async: bool = False


@dataclass
class ClassDoc:
    """Documentation for a class."""

    name: str
    docstring: str | None = None
    bases: list[str] = field(default_factory=list)
    methods: list[FunctionDoc] = field(default_factory=list)
    attributes: list[AttributeDoc] = field(default_factory=list)
    is_dataclass: bool = False
    is_enum: bool = False


@dataclass
class ModuleDoc:
    """Documentation for a Python module."""

    module_path: str
    docstring: str | None = None
    classes: list[ClassDoc] = field(default_factory=list)
    functions: list[FunctionDoc] = field(default_factory=list)
    constants: list[str] = field(default_factory=list)


class APIReferenceGenerator:
    """Generates API reference documentation from Python type annotations.

    Introspects modules, classes, and functions to produce structured
    documentation that can be rendered as markdown.
    """

    def __init__(self, base_package: str = "reins") -> None:
        self.base_package = base_package

    def document_module(self, module_path: str) -> ModuleDoc:
        """Import and introspect a module, extracting all public symbols."""
        module = importlib.import_module(module_path)
        classes: list[ClassDoc] = []
        functions: list[FunctionDoc] = []
        constants: list[str] = []

        for name, obj in inspect.getmembers(module):
            if name.startswith("_"):
                continue
            if inspect.isclass(obj) and obj.__module__ == module_path:
                classes.append(self.document_class(obj))
            elif inspect.isfunction(obj) and obj.__module__ == module_path:
                functions.append(self.document_function(obj))
            elif not callable(obj) and not isinstance(obj, types.ModuleType):
                constants.append(name)

        return ModuleDoc(
            module_path=module_path,
            docstring=inspect.getdoc(module),
            classes=classes,
            functions=functions,
            constants=constants,
        )

    def document_class(self, cls: type) -> ClassDoc:
        """Extract documentation from a class including methods and attributes."""
        methods: list[FunctionDoc] = []
        attributes: list[AttributeDoc] = []

        # Extract methods
        for name, method in inspect.getmembers(cls, predicate=inspect.isfunction):
            if name.startswith("_") and name != "__init__":
                continue
            methods.append(self.document_function(method))

        # Extract attributes from type annotations
        hints = _get_type_hints_safe(cls)
        for attr_name, annotation in hints.items():
            if attr_name.startswith("_"):
                continue
            default_val = None
            if dataclasses.is_dataclass(cls):
                for f in dataclasses.fields(cls):
                    if f.name == attr_name:
                        if f.default is not dataclasses.MISSING:
                            default_val = repr(f.default)
                        break
            attributes.append(AttributeDoc(
                name=attr_name,
                type_annotation=_format_annotation(annotation),
                default=default_val,
            ))

        bases = [b.__name__ for b in cls.__bases__ if b is not object]

        return ClassDoc(
            name=cls.__name__,
            docstring=inspect.getdoc(cls),
            bases=bases,
            methods=methods,
            attributes=attributes,
            is_dataclass=dataclasses.is_dataclass(cls),
            is_enum=issubclass(cls, enum.Enum),
        )

    def document_function(self, func: Callable[..., Any]) -> FunctionDoc:
        """Extract signature, parameters, return type, and docstring from a function."""
        parameters: list[ParameterDoc] = []
        return_type: str | None = None

        try:
            sig = inspect.signature(func)
            sig_str = str(sig)

            for param_name, param in sig.parameters.items():
                if param_name == "self":
                    continue
                annotation = (
                    _format_annotation(param.annotation)
                    if param.annotation is not inspect.Parameter.empty
                    else None
                )
                default = (
                    repr(param.default)
                    if param.default is not inspect.Parameter.empty
                    else None
                )
                kind = param.kind.name.lower()
                parameters.append(ParameterDoc(
                    name=param_name,
                    type_annotation=annotation,
                    default=default,
                    kind=kind,
                ))

            if sig.return_annotation is not inspect.Parameter.empty:
                return_type = _format_annotation(sig.return_annotation)
        except (ValueError, TypeError):
            sig_str = "()"

        return FunctionDoc(
            name=func.__name__,
            docstring=inspect.getdoc(func),
            signature=sig_str,
            parameters=parameters,
            return_type=return_type,
            is_async=inspect.iscoroutinefunction(func),
        )

    def render_module_markdown(self, doc: ModuleDoc) -> str:
        """Render a ModuleDoc as a markdown string."""
        lines: list[str] = []
        module_name = doc.module_path.split(".")[-1]
        lines.append(f"# {module_name}")
        lines.append("")

        if doc.docstring:
            lines.append(doc.docstring)
            lines.append("")

        lines.append(f"**Module:** `{doc.module_path}`")
        lines.append("")

        if doc.constants:
            lines.append("## Constants")
            lines.append("")
            for const in doc.constants:
                lines.append(f"- `{const}`")
            lines.append("")

        for cls_doc in doc.classes:
            lines.append(self.render_class_markdown(cls_doc))

        for func_doc in doc.functions:
            lines.append(self._render_function_markdown(func_doc, level=2))

        return "\n".join(lines)

    def render_class_markdown(self, doc: ClassDoc) -> str:
        """Render a ClassDoc as a markdown string."""
        lines: list[str] = []
        badge = ""
        if doc.is_dataclass:
            badge = " (dataclass)"
        elif doc.is_enum:
            badge = " (enum)"

        lines.append(f"## {doc.name}{badge}")
        lines.append("")

        if doc.bases:
            lines.append(f"**Bases:** {', '.join(f'`{b}`' for b in doc.bases)}")
            lines.append("")

        if doc.docstring:
            lines.append(doc.docstring)
            lines.append("")

        if doc.attributes:
            lines.append("### Attributes")
            lines.append("")
            lines.append("| Name | Type | Default |")
            lines.append("|------|------|---------|")
            for attr in doc.attributes:
                type_str = f"`{attr.type_annotation}`" if attr.type_annotation else "-"
                default_str = f"`{attr.default}`" if attr.default else "-"
                lines.append(f"| `{attr.name}` | {type_str} | {default_str} |")
            lines.append("")

        if doc.methods:
            lines.append("### Methods")
            lines.append("")
            for method in doc.methods:
                lines.append(self._render_function_markdown(method, level=4))

        return "\n".join(lines)

    def _render_function_markdown(self, doc: FunctionDoc, level: int = 3) -> str:
        """Render a single function/method as markdown."""
        lines: list[str] = []
        prefix = "#" * level
        async_prefix = "async " if doc.is_async else ""
        lines.append(f"{prefix} `{async_prefix}{doc.name}{doc.signature}`")
        lines.append("")

        if doc.docstring:
            lines.append(doc.docstring)
            lines.append("")

        if doc.parameters:
            lines.append("**Parameters:**")
            lines.append("")
            for param in doc.parameters:
                type_str = f": `{param.type_annotation}`" if param.type_annotation else ""
                default_str = f" = `{param.default}`" if param.default else ""
                lines.append(f"- `{param.name}`{type_str}{default_str}")
            lines.append("")

        if doc.return_type:
            lines.append(f"**Returns:** `{doc.return_type}`")
            lines.append("")

        return "\n".join(lines)

    def generate_for_package(self, package_path: str, output_dir: Path) -> list[Path]:
        """Generate markdown files for all modules in a package."""
        output_dir.mkdir(parents=True, exist_ok=True)
        generated: list[Path] = []

        try:
            package = importlib.import_module(package_path)
        except ImportError:
            return generated

        package_file = getattr(package, "__file__", None)
        if package_file is None:
            return generated

        package_dir = Path(package_file).parent

        for importer, module_name, is_pkg in pkgutil.walk_packages(
            [str(package_dir)], prefix=f"{package_path}."
        ):
            try:
                doc = self.document_module(module_name)
            except Exception:
                continue

            if not doc.classes and not doc.functions:
                continue

            relative = module_name.replace(f"{package_path}.", "").replace(".", "/")
            output_file = output_dir / f"{relative}.md"
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(self.render_module_markdown(doc), encoding="utf-8")
            generated.append(output_file)

        return generated

    def generate_index(self, modules: list[ModuleDoc], output_path: Path) -> None:
        """Create an index.md linking to all module documentation files."""
        lines: list[str] = []
        lines.append("# API Reference Index")
        lines.append("")
        lines.append("## Modules")
        lines.append("")

        for mod in sorted(modules, key=lambda m: m.module_path):
            relative = mod.module_path.replace(f"{self.base_package}.", "").replace(".", "/")
            name = mod.module_path.split(".")[-1]
            description = (mod.docstring or "").split("\n")[0] if mod.docstring else ""
            lines.append(f"- [{mod.module_path}]({relative}.md) - {description}")

        lines.append("")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines), encoding="utf-8")


def _format_annotation(annotation: Any) -> str:
    """Format a type annotation as a readable string."""
    if annotation is inspect.Parameter.empty:
        return ""
    if isinstance(annotation, str):
        return annotation
    if hasattr(annotation, "__name__"):
        return annotation.__name__
    return str(annotation).replace("typing.", "")


def _get_type_hints_safe(cls: type) -> dict[str, Any]:
    """Safely get type hints, falling back to __annotations__ on failure."""
    try:
        import typing
        return typing.get_type_hints(cls)
    except Exception:
        return getattr(cls, "__annotations__", {})
