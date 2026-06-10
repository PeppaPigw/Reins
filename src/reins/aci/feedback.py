from __future__ import annotations

import difflib
from pathlib import Path

from reins.aci.types import Diagnostic, DiagnosticSeverity, SearchResult


class FeedbackFormatter:
    """Formats ACI responses for optimal LLM consumption."""

    def __init__(self, *, max_lines: int = 160, max_chars: int = 12000) -> None:
        self.max_lines = max_lines
        self.max_chars = max_chars

    def format_file(
        self,
        path: Path,
        content: str,
        *,
        start_line: int = 1,
        focus_line: int | None = None,
    ) -> str:
        lines = content.splitlines()
        if focus_line is not None and len(lines) > self.max_lines:
            focus_index = max(focus_line - start_line, 0)
            body_budget = max(self.max_lines - 1, 1)
            context_budget = max(body_budget - 1, 0)
            before_budget = context_budget // 2
            after_budget = context_budget - before_budget
            window_start = max(focus_index - before_budget, 0)
            window_end = min(focus_index + after_budget + 1, len(lines))
            while window_end - window_start < body_budget and window_start > 0:
                window_start -= 1
            while window_end - window_start < body_budget and window_end < len(lines):
                window_end += 1
            visible_lines = lines[window_start:window_end]
            if window_start and len(visible_lines) >= body_budget:
                visible_lines = visible_lines[1:]
                window_start += 1
            if window_end < len(lines) and len(visible_lines) >= body_budget:
                visible_lines = visible_lines[:-1]
                window_end -= 1
            visible: list[tuple[int, str]] = list(
                enumerate(visible_lines, start=start_line + window_start)
            )
            numbered = []
            if window_start:
                numbered.append(f"... truncated {window_start} lines before focus ...")
            for offset, line in visible:
                marker = ">" if focus_line == offset else " "
                numbered.append(f"{marker} {offset:4d} | {line}")
            if window_end < len(lines):
                numbered.append(f"... truncated {len(lines) - window_end} lines after focus ...")
            body = "\n".join(numbered)
            output = f"File: {path}\n{body}"
            if len(output) <= self.max_chars:
                return output
            head_count = max(self.max_chars // 2, 1)
            tail_count = max(self.max_chars - head_count, 1)
            omitted = len(output) - head_count - tail_count
            return (
                f"{output[:head_count]}\n"
                f"... truncated {omitted} chars ...\n"
                f"{output[-tail_count:]}"
            )

        numbered = []
        for offset, line in enumerate(lines, start=start_line):
            marker = ">" if focus_line == offset else " "
            numbered.append(f"{marker} {offset:4d} | {line}")
        body = "\n".join(numbered) if numbered else "  <empty file>"
        return self.truncate(f"File: {path}\n{body}")

    def format_directory(self, path: Path, entries: list[str]) -> str:
        body = "\n".join(entries) if entries else "  <empty directory>"
        return self.truncate(f"Directory: {path}\n{body}")

    def format_search_results(self, query: str, results: tuple[SearchResult, ...]) -> str:
        if not results:
            return f"No results for: {query}"
        lines = [f"Search results for: {query}"]
        for index, result in enumerate(results, start=1):
            location = f"{result.path}:{result.line}"
            if result.column is not None:
                location = f"{location}:{result.column}"
            lines.append(f"{index}. {location} score={result.score:.2f}")
            if result.snippet:
                lines.append(f"   {result.snippet.strip()}")
        return self.truncate("\n".join(lines))

    def format_diagnostics(self, diagnostics: tuple[Diagnostic, ...]) -> str:
        if not diagnostics:
            return "No diagnostics."
        lines = ["Diagnostics:"]
        for diagnostic in diagnostics:
            location = diagnostic.path or "<unknown>"
            if diagnostic.line is not None:
                location = f"{location}:{diagnostic.line}"
            if diagnostic.column is not None:
                location = f"{location}:{diagnostic.column}"
            code = f" [{diagnostic.code}]" if diagnostic.code else ""
            lines.append(
                f"- {diagnostic.severity.value.upper()} "
                f"{location}{code}: {diagnostic.message}"
            )
            if diagnostic.suggestion:
                lines.append(f"  Fix suggestion: {diagnostic.suggestion}")
        return self.truncate("\n".join(lines))

    def format_error(
        self,
        message: str,
        *,
        path: str | None = None,
        suggestion: str | None = None,
    ) -> str:
        diagnostic = Diagnostic(
            message=message,
            severity=DiagnosticSeverity.ERROR,
            path=path,
            suggestion=suggestion,
        )
        return self.format_diagnostics((diagnostic,))

    def format_diff(self, path: str, before: str, after: str) -> str:
        diff = difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"{path}:before",
            tofile=f"{path}:after",
            lineterm="",
        )
        return self.truncate("\n".join(diff))

    def navigation_hints(self, suggestions: tuple[str, ...]) -> str:
        if not suggestions:
            return ""
        return "Next commands:\n" + "\n".join(f"- {suggestion}" for suggestion in suggestions)

    def truncate(self, output: str) -> str:
        lines = output.splitlines()
        truncated_by_lines = len(lines) > self.max_lines
        if truncated_by_lines:
            head_count = max(self.max_lines // 2, 1)
            tail_count = max(self.max_lines - head_count, 1)
            omitted = len(lines) - head_count - tail_count
            lines = [
                *lines[:head_count],
                f"... truncated {omitted} lines ...",
                *lines[-tail_count:],
            ]
            output = "\n".join(lines)

        if len(output) <= self.max_chars:
            return output
        head_count = max(self.max_chars // 2, 1)
        tail_count = max(self.max_chars - head_count, 1)
        omitted = len(output) - head_count - tail_count
        return f"{output[:head_count]}\n... truncated {omitted} chars ...\n{output[-tail_count:]}"
