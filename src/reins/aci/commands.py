from __future__ import annotations

import ast
import asyncio
import fnmatch
import py_compile
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Iterable

from reins.aci.feedback import FeedbackFormatter
from reins.aci.types import (
    ACICommand,
    ACIResponse,
    CommandCategory,
    CommandContext,
    ContextUpdate,
    Diagnostic,
    DiagnosticSeverity,
    EditResult,
    SearchResult,
)

CommandHandler = Callable[[ACICommand], Awaitable[ACIResponse]]

SKIP_DIRS = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
}


@dataclass(frozen=True)
class CommandDefinition:
    name: str
    category: CommandCategory
    description: str
    args_schema: dict[str, str]


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


class ACICommandRegistry:
    """Registry of available ACI commands with LLM-friendly descriptions."""

    def __init__(
        self,
        working_directory: str | Path,
        *,
        formatter: FeedbackFormatter | None = None,
        default_timeout: float = 30.0,
    ) -> None:
        self.working_directory = Path(working_directory).resolve()
        self.formatter = formatter or FeedbackFormatter()
        self.default_timeout = default_timeout
        self._handlers: dict[str, CommandHandler] = {}
        self._definitions: dict[str, CommandDefinition] = {}
        self._diagnostics: list[Diagnostic] = []
        self._last_search_results: tuple[SearchResult, ...] | None = None
        self._register_defaults()

    def register(
        self,
        name: str,
        category: CommandCategory,
        description: str,
        args_schema: dict[str, str],
        handler: CommandHandler,
    ) -> None:
        self._definitions[name] = CommandDefinition(name, category, description, args_schema)
        self._handlers[name] = handler

    def discover(self, category: CommandCategory | None = None) -> tuple[CommandDefinition, ...]:
        definitions: Iterable[CommandDefinition] = self._definitions.values()
        if category is not None:
            definitions = [item for item in definitions if item.category is category]
        return tuple(sorted(definitions, key=lambda item: item.name))

    @property
    def last_search_results(self) -> tuple[SearchResult, ...] | None:
        return self._last_search_results

    async def execute(self, command: ACICommand) -> ACIResponse:
        handler = self._handlers.get(command.name)
        if handler is None:
            response = self._failure(
                command,
                f"Unknown ACI command: {command.name}",
                suggestion="Call get_context or discover available commands.",
            )
            self._diagnostics.extend(response.diagnostics)
            return response
        try:
            response = await handler(command)
        except Exception as exc:
            response = self._failure(command, str(exc), suggestion="Inspect arguments and retry.")
        self._diagnostics.extend(response.diagnostics)
        return response

    def make_command(
        self,
        name: str,
        category: CommandCategory,
        context: CommandContext,
        **args: object,
    ) -> ACICommand:
        return ACICommand(name=name, category=category, args=dict(args), context=context)

    def _register_defaults(self) -> None:
        self.register(
            "find_definition",
            CommandCategory.NAVIGATION,
            "Find where a symbol is defined.",
            {"symbol": "Symbol name to locate."},
            self.find_definition,
        )
        self.register(
            "find_references",
            CommandCategory.NAVIGATION,
            "Find all references to a symbol.",
            {"symbol": "Symbol name to locate."},
            self.find_references,
        )
        self.register(
            "open_file",
            CommandCategory.NAVIGATION,
            "Open a file with line-numbered context.",
            {"path": "File path.", "line": "Optional focus line."},
            self.open_file,
        )
        self.register(
            "list_directory",
            CommandCategory.NAVIGATION,
            "List directory contents with metadata.",
            {"path": "Optional directory path."},
            self.list_directory,
        )
        self.register(
            "search_codebase",
            CommandCategory.SEARCH,
            "Search source files for a query.",
            {"query": "Search text or regex.", "file_pattern": "Optional glob pattern."},
            self.search_codebase,
        )
        self.register(
            "edit_range",
            CommandCategory.EDITING,
            "Replace a line range with new content.",
            {
                "file": "File path.",
                "start_line": "First line to replace.",
                "end_line": "Last line to replace.",
                "new_content": "Replacement content.",
            },
            self.edit_range,
        )
        self.register(
            "insert_after",
            CommandCategory.EDITING,
            "Insert content after a line.",
            {
                "file": "File path.",
                "line": "Line after which content is inserted.",
                "content": "Text.",
            },
            self.insert_after,
        )
        self.register(
            "delete_range",
            CommandCategory.EDITING,
            "Delete a line range.",
            {"file": "File path.", "start_line": "First line.", "end_line": "Last line."},
            self.delete_range,
        )
        self.register(
            "create_file",
            CommandCategory.EDITING,
            "Create a new file.",
            {"path": "New file path.", "content": "File content."},
            self.create_file,
        )
        self.register(
            "rename_symbol",
            CommandCategory.EDITING,
            "Rename a symbol across matching files.",
            {
                "old_name": "Existing symbol.",
                "new_name": "New symbol.",
                "scope": "Optional glob scope.",
            },
            self.rename_symbol,
        )
        self.register(
            "run_test",
            CommandCategory.EXECUTION,
            "Run pytest for a path or test name.",
            {"test_path": "Optional test path.", "test_name": "Optional test selection."},
            self.run_test,
        )
        self.register(
            "run_lint",
            CommandCategory.EXECUTION,
            "Run ruff on a file or project.",
            {"file": "Optional file path."},
            self.run_lint,
        )
        self.register(
            "run_typecheck",
            CommandCategory.EXECUTION,
            "Run mypy on a file or project.",
            {"file": "Optional file path."},
            self.run_typecheck,
        )
        self.register(
            "run_command",
            CommandCategory.EXECUTION,
            "Run an arbitrary command with timeout.",
            {"cmd": "Command string or argv list.", "timeout": "Optional timeout seconds."},
            self.run_command,
        )
        self.register(
            "check_syntax",
            CommandCategory.EXECUTION,
            "Compile a Python file to check syntax.",
            {"file": "Python file path."},
            self.check_syntax,
        )
        self.register(
            "get_context",
            CommandCategory.CONTEXT,
            "Get current ACI context summary.",
            {},
            self.get_context,
        )
        self.register(
            "get_file_outline",
            CommandCategory.CONTEXT,
            "Get imports, classes, and functions for a Python file.",
            {"file": "Python file path."},
            self.get_file_outline,
        )
        self.register(
            "get_related_files",
            CommandCategory.CONTEXT,
            "Find files related to a path.",
            {"file": "File path."},
            self.get_related_files,
        )
        self.register(
            "get_recent_changes",
            CommandCategory.CONTEXT,
            "Show recent git changes.",
            {},
            self.get_recent_changes,
        )
        self.register(
            "summarize_errors",
            CommandCategory.CONTEXT,
            "Summarize current diagnostics.",
            {},
            self.summarize_errors,
        )

    async def find_definition(self, command: ACICommand) -> ACIResponse:
        symbol = self._required_str(command, "symbol")
        pattern = re.compile(
            rf"^\s*(class|def|async\s+def)\s+{re.escape(symbol)}\b|^\s*{re.escape(symbol)}\s*="
        )
        results = await self._search_lines(pattern, file_pattern="*.py", symbol=symbol)
        self._last_search_results = results
        suggestions = self._navigation_suggestions(results)
        output = self.formatter.format_search_results(f"definition:{symbol}", results)
        return self._success(
            command,
            output,
            suggestions=suggestions,
            context_update=self._search_update(results),
        )

    async def find_references(self, command: ACICommand) -> ACIResponse:
        symbol = self._required_str(command, "symbol")
        pattern = re.compile(rf"\b{re.escape(symbol)}\b")
        results = await self._search_lines(pattern, symbol=symbol)
        self._last_search_results = results
        output = self.formatter.format_search_results(f"references:{symbol}", results)
        return self._success(
            command,
            output,
            suggestions=self._navigation_suggestions(results),
            context_update=self._search_update(results),
        )

    async def open_file(self, command: ACICommand) -> ACIResponse:
        path = self._resolve_path(self._required_str(command, "path"))
        line = self._optional_int(command, "line") or 1
        content = await asyncio.to_thread(path.read_text, encoding="utf-8")
        output = self.formatter.format_file(self._display_path(path), content, focus_line=line)
        return self._success(
            command,
            output,
            suggestions=("get_file_outline", "find_references", "edit_range"),
            context_update=ContextUpdate(
                new_file=str(self._display_path(path)),
                new_cursor_line=line,
            ),
        )

    async def list_directory(self, command: ACICommand) -> ACIResponse:
        raw_path = str(command.args.get("path") or ".")
        path = self._resolve_path(raw_path)
        if not path.is_dir():
            raise ValueError(f"Not a directory: {raw_path}")
        entries: list[str] = []
        children = sorted(
            path.iterdir(),
            key=lambda item: (not item.is_dir(), item.name.lower()),
        )
        for child in children:
            if child.name in SKIP_DIRS:
                continue
            kind = "dir " if child.is_dir() else "file"
            size = "-" if child.is_dir() else str(child.stat().st_size)
            entries.append(f"{kind:4} {self._display_path(child)} size={size}")
        output = self.formatter.format_directory(self._display_path(path), entries)
        return self._success(command, output, suggestions=("open_file", "search_codebase"))

    async def search_codebase(self, command: ACICommand) -> ACIResponse:
        query = self._required_str(command, "query")
        file_pattern = self._optional_str(command, "file_pattern")
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        results = await self._search_lines(pattern, file_pattern=file_pattern, symbol=query)
        self._last_search_results = results
        output = self.formatter.format_search_results(query, results)
        return self._success(
            command,
            output,
            suggestions=self._navigation_suggestions(results),
            context_update=self._search_update(results),
        )

    async def edit_range(self, command: ACICommand) -> ACIResponse:
        file_path = self._required_str(command, "file")
        start_line = self._required_int(command, "start_line")
        end_line = self._required_int(command, "end_line")
        new_content = str(command.args.get("new_content", ""))
        path = self._resolve_path(file_path)
        before, after, result = await self._replace_range(path, start_line, end_line, new_content)
        output = self._format_edit_result(result, before, after)
        return self._success(
            command,
            output,
            suggestions=("check_syntax", "run_test", "get_recent_changes"),
            context_update=ContextUpdate(
                new_file=str(self._display_path(path)),
                new_cursor_line=start_line,
                files_modified=(str(self._display_path(path)),),
            ),
        )

    async def insert_after(self, command: ACICommand) -> ACIResponse:
        file_path = self._required_str(command, "file")
        line = self._required_int(command, "line")
        content = str(command.args.get("content", ""))
        path = self._resolve_path(file_path)
        before, after, result = await self._replace_range(path, line + 1, line, content)
        output = self._format_edit_result(result, before, after)
        return self._success(
            command,
            output,
            suggestions=("check_syntax", "run_test"),
            context_update=ContextUpdate(
                new_file=str(self._display_path(path)),
                new_cursor_line=line + 1,
                files_modified=(str(self._display_path(path)),),
            ),
        )

    async def delete_range(self, command: ACICommand) -> ACIResponse:
        file_path = self._required_str(command, "file")
        start_line = self._required_int(command, "start_line")
        end_line = self._required_int(command, "end_line")
        path = self._resolve_path(file_path)
        before, after, result = await self._replace_range(path, start_line, end_line, "")
        output = self._format_edit_result(result, before, after)
        return self._success(
            command,
            output,
            suggestions=("check_syntax", "run_test"),
            context_update=ContextUpdate(
                new_file=str(self._display_path(path)),
                new_cursor_line=start_line,
                files_modified=(str(self._display_path(path)),),
            ),
        )

    async def create_file(self, command: ACICommand) -> ACIResponse:
        path = self._resolve_path(self._required_str(command, "path"), must_exist=False)
        if path.exists():
            raise ValueError(f"File already exists: {self._display_path(path)}")
        content = str(command.args.get("content", ""))
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_text, content, encoding="utf-8")
        output = self.formatter.format_file(self._display_path(path), content)
        return self._success(
            command,
            output,
            suggestions=("check_syntax", "run_test", "get_recent_changes"),
            context_update=ContextUpdate(
                new_file=str(self._display_path(path)),
                new_cursor_line=1,
                files_created=(str(self._display_path(path)),),
            ),
        )

    async def rename_symbol(self, command: ACICommand) -> ACIResponse:
        old_name = self._required_str(command, "old_name")
        new_name = self._required_str(command, "new_name")
        scope = self._optional_str(command, "scope")
        pattern = re.compile(rf"\b{re.escape(old_name)}\b")
        modified: list[str] = []
        diff_parts: list[str] = []
        for path in self._iter_files(scope):
            if not path.is_file() or self._is_binary(path):
                continue
            before = await asyncio.to_thread(path.read_text, encoding="utf-8")
            after = pattern.sub(new_name, before)
            if before == after:
                continue
            await asyncio.to_thread(path.write_text, after, encoding="utf-8")
            modified.append(str(self._display_path(path)))
            diff_parts.append(
                self.formatter.format_diff(str(self._display_path(path)), before, after)
            )
        output = "\n\n".join(diff_parts) if diff_parts else f"No occurrences found for {old_name}."
        return self._success(
            command,
            self.formatter.truncate(output),
            suggestions=("run_test", "run_lint", "get_recent_changes"),
            context_update=ContextUpdate(files_modified=tuple(modified)),
        )

    async def run_test(self, command: ACICommand) -> ACIResponse:
        test_path = self._optional_str(command, "test_path")
        test_name = self._optional_str(command, "test_name")
        args = [sys.executable, "-m", "pytest"]
        if test_path:
            target = test_path
            if test_name:
                target = f"{test_path}::{test_name}"
            args.append(target)
        elif test_name:
            args.extend(["-k", test_name])
        return await self._run_process_response(command, args, label="pytest")

    async def run_lint(self, command: ACICommand) -> ACIResponse:
        file_path = self._optional_str(command, "file") or "."
        return await self._run_process_response(
            command,
            [sys.executable, "-m", "ruff", "check", file_path],
            label="ruff",
        )

    async def run_typecheck(self, command: ACICommand) -> ACIResponse:
        file_path = self._optional_str(command, "file") or "."
        return await self._run_process_response(
            command,
            [sys.executable, "-m", "mypy", file_path],
            label="mypy",
        )

    async def run_command(self, command: ACICommand) -> ACIResponse:
        raw = command.args.get("cmd")
        if isinstance(raw, list):
            args = [str(item) for item in raw]
        elif isinstance(raw, str):
            args = shlex.split(raw)
        else:
            raise ValueError("cmd must be a string or list of arguments")
        if not args:
            raise ValueError("cmd cannot be empty")
        return await self._run_process_response(command, args, label=args[0])

    async def check_syntax(self, command: ACICommand) -> ACIResponse:
        path = self._resolve_path(self._required_str(command, "file"))
        try:
            await asyncio.to_thread(py_compile.compile, str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            diagnostic = Diagnostic(
                message=str(exc.msg),
                severity=DiagnosticSeverity.ERROR,
                path=str(self._display_path(path)),
                suggestion="Open the file around the reported line and fix invalid Python syntax.",
            )
            return self._failure_response(
                command,
                self.formatter.format_diagnostics((diagnostic,)),
                diagnostics=(diagnostic,),
            )
        return self._success(
            command,
            f"Syntax OK: {self._display_path(path)}",
            suggestions=("run_test", "run_lint"),
        )

    async def get_context(self, command: ACICommand) -> ACIResponse:
        context = command.context
        lines = [
            f"Working directory: {context.working_directory}",
            f"Current file: {context.current_file or '-'}",
            f"Cursor line: {context.cursor_line or '-'}",
            f"Open files: {', '.join(context.open_files) if context.open_files else '-'}",
            "Recent commands: "
            f"{', '.join(context.recent_commands) if context.recent_commands else '-'}",
            f"Active task: {context.active_task or '-'}",
        ]
        if context.search_results:
            lines.append(f"Search results cached: {len(context.search_results)}")
        return self._success(
            command,
            "\n".join(lines),
            suggestions=self._context_suggestions(context),
        )

    async def get_file_outline(self, command: ACICommand) -> ACIResponse:
        path = self._resolve_path(self._required_str(command, "file"))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports: list[str] = []
        definitions: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imports.append(f"{'.' * node.level}{module}")
            elif isinstance(node, ast.ClassDef):
                definitions.append(f"class {node.name}:{node.lineno}")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                definitions.append(f"{prefix} {node.name}:{node.lineno}")
        output = "\n".join(
            [
                f"Outline: {self._display_path(path)}",
                "Imports:",
                *(f"- {item}" for item in imports),
                "Definitions:",
                *(f"- {item}" for item in definitions),
            ]
        )
        return self._success(command, output, suggestions=("find_references", "open_file"))

    async def get_related_files(self, command: ACICommand) -> ACIResponse:
        path = self._resolve_path(self._required_str(command, "file"))
        stem = path.stem
        candidates: list[SearchResult] = []
        for item in self._iter_files(None):
            if item == path:
                continue
            if item.stem == stem or stem in item.name or item.stem in path.name:
                candidates.append(
                    SearchResult(
                        path=str(self._display_path(item)),
                        line=1,
                        snippet=item.name,
                        score=0.8 if item.stem == stem else 0.5,
                    )
                )
        results = tuple(sorted(candidates, key=lambda item: item.score, reverse=True)[:25])
        output = self.formatter.format_search_results(
            f"related:{self._display_path(path)}",
            results,
        )
        return self._success(command, output, suggestions=self._navigation_suggestions(results))

    async def get_recent_changes(self, command: ACICommand) -> ACIResponse:
        return await self._run_process_response(
            command,
            ["git", "status", "--short"],
            label="git status",
            success_suggestions=("run_test", "run_lint"),
        )

    async def summarize_errors(self, command: ACICommand) -> ACIResponse:
        diagnostics = tuple(self._diagnostics)
        return self._success(
            command,
            self.formatter.format_diagnostics(diagnostics),
            suggestions=("open_file", "check_syntax"),
        )

    async def _replace_range(
        self,
        path: Path,
        start_line: int,
        end_line: int,
        new_content: str,
    ) -> tuple[str, str, EditResult]:
        before = await asyncio.to_thread(path.read_text, encoding="utf-8")
        had_trailing_newline = before.endswith("\n")
        lines = before.splitlines()
        if start_line < 1 or end_line > len(lines) or end_line < start_line - 1:
            raise ValueError(
                f"Invalid range {start_line}-{end_line} for {self._display_path(path)} "
                f"with {len(lines)} lines"
            )
        replacement = new_content.splitlines()
        after_lines = [*lines[: start_line - 1], *replacement, *lines[end_line:]]
        after = "\n".join(after_lines)
        if had_trailing_newline or new_content.endswith("\n"):
            after += "\n"
        await asyncio.to_thread(path.write_text, after, encoding="utf-8")
        result = EditResult(
            file=str(self._display_path(path)),
            start_line=start_line,
            end_line=end_line,
            lines_added=len(replacement),
            lines_removed=max(end_line - start_line + 1, 0),
            diff=self.formatter.format_diff(str(self._display_path(path)), before, after),
        )
        return before, after, result

    async def _run_process_response(
        self,
        command: ACICommand,
        args: list[str],
        *,
        label: str,
        success_suggestions: tuple[str, ...] = ("get_recent_changes",),
    ) -> ACIResponse:
        timeout = float(command.args.get("timeout") or self.default_timeout)
        completed = await self._run_process(args, timeout=timeout)
        output = self.formatter.truncate(
            "\n".join(
                item
                for item in (
                    f"$ {shlex.join(args)}",
                    f"exit_code={completed.returncode}",
                    completed.stdout.strip(),
                    completed.stderr.strip(),
                )
                if item
            )
        )
        if completed.returncode == 0:
            return self._success(command, output, suggestions=success_suggestions)
        diagnostic = Diagnostic(
            message=f"{label} exited with {completed.returncode}",
            severity=DiagnosticSeverity.ERROR,
            suggestion=f"Inspect the {label} output above and rerun after fixing it.",
        )
        return self._failure_response(command, output, diagnostics=(diagnostic,))

    async def _run_process(self, args: list[str], *, timeout: float) -> ProcessResult:
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=self.working_directory,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError:
            process.kill()
            await process.communicate()
            raise TimeoutError(f"Command timed out after {timeout:g}s: {shlex.join(args)}")
        return ProcessResult(
            returncode=process.returncode or 0,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
        )

    async def _search_lines(
        self,
        pattern: re.Pattern[str],
        *,
        file_pattern: str | None = None,
        symbol: str | None = None,
        limit: int = 50,
    ) -> tuple[SearchResult, ...]:
        results: list[SearchResult] = []
        for path in self._iter_files(file_pattern):
            if self._is_binary(path):
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for line_number, line in enumerate(lines, start=1):
                match = pattern.search(line)
                if match is None:
                    continue
                score = self._score_match(line, symbol=symbol, match_start=match.start())
                results.append(
                    SearchResult(
                        path=str(self._display_path(path)),
                        line=line_number,
                        column=match.start() + 1,
                        snippet=line.strip(),
                        score=score,
                        symbol=symbol,
                    )
                )
                if len(results) >= limit:
                    return tuple(results)
        return tuple(sorted(results, key=lambda item: item.score, reverse=True))

    def _format_edit_result(self, result: EditResult, before: str, after: str) -> str:
        summary = (
            f"Edited {result.file}: removed {result.lines_removed} lines, "
            f"added {result.lines_added} lines."
        )
        return self.formatter.truncate(
            f"{summary}\n{self.formatter.format_diff(result.file, before, after)}"
        )

    def _success(
        self,
        command: ACICommand,
        output: str,
        *,
        suggestions: tuple[str, ...] = (),
        context_update: ContextUpdate | None = None,
    ) -> ACIResponse:
        return ACIResponse(
            command_id=command.command_id,
            success=True,
            output=output,
            context_update=context_update,
            suggestions=suggestions,
        )

    def _failure(
        self,
        command: ACICommand,
        message: str,
        *,
        suggestion: str | None = None,
    ) -> ACIResponse:
        diagnostic = Diagnostic(message=message, suggestion=suggestion)
        return self._failure_response(
            command,
            self.formatter.format_diagnostics((diagnostic,)),
            diagnostics=(diagnostic,),
        )

    def _failure_response(
        self,
        command: ACICommand,
        output: str,
        *,
        diagnostics: tuple[Diagnostic, ...],
    ) -> ACIResponse:
        return ACIResponse(
            command_id=command.command_id,
            success=False,
            output=output,
            context_update=ContextUpdate(diagnostics_added=len(diagnostics)),
            suggestions=("summarize_errors", "get_context"),
            diagnostics=diagnostics,
        )

    def _search_update(self, results: tuple[SearchResult, ...]) -> ContextUpdate | None:
        if not results:
            return None
        first = results[0]
        return ContextUpdate(new_file=first.path, new_cursor_line=first.line)

    def _navigation_suggestions(self, results: tuple[SearchResult, ...]) -> tuple[str, ...]:
        if not results:
            return ("search_codebase", "list_directory")
        return ("open_file", "get_file_outline", "find_references")

    def _context_suggestions(self, context: CommandContext) -> tuple[str, ...]:
        if context.current_file:
            return ("get_file_outline", "get_related_files", "get_recent_changes")
        return ("list_directory", "search_codebase")

    def _required_str(self, command: ACICommand, key: str) -> str:
        value = command.args.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Missing required string argument: {key}")
        return value

    def _optional_str(self, command: ACICommand, key: str) -> str | None:
        value = command.args.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"Argument {key} must be a string")
        return value or None

    def _required_int(self, command: ACICommand, key: str) -> int:
        value = command.args.get(key)
        if not isinstance(value, int):
            raise ValueError(f"Missing required integer argument: {key}")
        return value

    def _optional_int(self, command: ACICommand, key: str) -> int | None:
        value = command.args.get(key)
        if value is None:
            return None
        if not isinstance(value, int):
            raise ValueError(f"Argument {key} must be an integer")
        return value

    def _resolve_path(self, path: str, *, must_exist: bool = True) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.working_directory / candidate
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self.working_directory):
            raise ValueError(f"Path escapes working directory: {path}")
        if must_exist and not resolved.exists():
            raise ValueError(f"Path does not exist: {path}")
        return resolved

    def _display_path(self, path: Path) -> Path:
        try:
            return path.resolve().relative_to(self.working_directory)
        except ValueError:
            return path

    def _iter_files(self, file_pattern: str | None) -> list[Path]:
        paths: list[Path] = []
        for path in self.working_directory.rglob("*"):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if not path.is_file():
                continue
            relative = path.relative_to(self.working_directory)
            if file_pattern and not (
                fnmatch.fnmatch(str(relative), file_pattern)
                or fnmatch.fnmatch(path.name, file_pattern)
            ):
                continue
            paths.append(path)
        return sorted(paths)

    def _is_binary(self, path: Path) -> bool:
        try:
            chunk = path.read_bytes()[:1024]
        except OSError:
            return True
        return b"\0" in chunk

    def _score_match(self, line: str, *, symbol: str | None, match_start: int) -> float:
        stripped = line.strip()
        score = 0.55
        if stripped.startswith(("def ", "async def ", "class ")):
            score += 0.3
        if symbol and stripped.startswith(symbol):
            score += 0.25
        if match_start == 0:
            score += 0.1
        return min(score, 1.0)
