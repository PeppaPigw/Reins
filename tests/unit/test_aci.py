from __future__ import annotations

from pathlib import Path

from reins.aci import (
    ACIResponse,
    ACICommandRegistry,
    ACISession,
    CommandCategory,
    CommandContext,
    FeedbackFormatter,
)
from reins.aci.types import ACICommand, Diagnostic, DiagnosticSeverity, SearchResult
from reins.kernel.event.journal import EventJournal


def _write_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    package = repo / "pkg"
    tests = repo / "tests"
    package.mkdir(parents=True)
    tests.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "sample.py").write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "",
                "class Widget:",
                "    def render(self) -> str:",
                "        return helper()",
                "",
                "def helper() -> str:",
                "    return 'ok'",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (tests / "test_sample.py").write_text(
        "\n".join(
            [
                "from pkg.sample import helper",
                "",
                "",
                "def test_helper() -> None:",
                "    assert helper() == 'ok'",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return repo


def _context(repo: Path) -> CommandContext:
    return CommandContext(working_directory=str(repo))


async def _execute(
    registry: ACICommandRegistry,
    name: str,
    category: CommandCategory,
    context: CommandContext,
    **args: object,
) -> ACIResponse:
    command = ACICommand(name=name, category=category, args=dict(args), context=context)
    return await registry.execute(command)


async def test_command_registration_and_discovery(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    registry = ACICommandRegistry(repo)

    commands = registry.discover()
    names = {command.name for command in commands}

    assert "find_definition" in names
    assert "edit_range" in names
    assert "run_test" in names
    navigation = registry.discover(CommandCategory.NAVIGATION)
    assert all(command.category is CommandCategory.NAVIGATION for command in navigation)


async def test_navigation_commands_find_definition_and_search(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    registry = ACICommandRegistry(repo)
    context = _context(repo)

    definition = await _execute(
        registry,
        "find_definition",
        CommandCategory.NAVIGATION,
        context,
        symbol="helper",
    )
    search = await _execute(
        registry,
        "search_codebase",
        CommandCategory.SEARCH,
        context,
        query="Widget",
        file_pattern="*.py",
    )

    assert definition.success is True
    assert "pkg/sample.py:7" in definition.output
    assert definition.context_update is not None
    assert definition.context_update.new_file == "pkg/sample.py"
    assert search.success is True
    assert "Widget" in search.output
    assert "open_file" in search.suggestions


async def test_open_file_and_directory_listing(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    registry = ACICommandRegistry(repo)
    context = _context(repo)

    opened = await _execute(
        registry,
        "open_file",
        CommandCategory.NAVIGATION,
        context,
        path="pkg/sample.py",
        line=3,
    )
    listed = await _execute(
        registry,
        "list_directory",
        CommandCategory.NAVIGATION,
        context,
        path="pkg",
    )

    assert opened.success is True
    assert ">    3 | class Widget:" in opened.output
    assert opened.context_update is not None
    assert opened.context_update.new_cursor_line == 3
    assert "pkg/sample.py" in listed.output


async def test_editing_commands_edit_insert_delete_create_and_rename(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    registry = ACICommandRegistry(repo)
    context = _context(repo)

    edited = await _execute(
        registry,
        "edit_range",
        CommandCategory.EDITING,
        context,
        file="pkg/sample.py",
        start_line=8,
        end_line=8,
        new_content="    return 'changed'",
    )
    inserted = await _execute(
        registry,
        "insert_after",
        CommandCategory.EDITING,
        context,
        file="pkg/sample.py",
        line=8,
        content="# temporary marker",
    )
    deleted = await _execute(
        registry,
        "delete_range",
        CommandCategory.EDITING,
        context,
        file="pkg/sample.py",
        start_line=9,
        end_line=9,
    )
    created = await _execute(
        registry,
        "create_file",
        CommandCategory.EDITING,
        context,
        path="pkg/extra.py",
        content="VALUE = 'helper'\n",
    )
    renamed = await _execute(
        registry,
        "rename_symbol",
        CommandCategory.EDITING,
        context,
        old_name="helper",
        new_name="make_value",
        scope="pkg/*.py",
    )

    sample = (repo / "pkg" / "sample.py").read_text(encoding="utf-8")
    extra = (repo / "pkg" / "extra.py").read_text(encoding="utf-8")
    assert edited.success is True
    assert inserted.success is True
    assert deleted.success is True
    assert created.context_update is not None
    assert created.context_update.files_created == ("pkg/extra.py",)
    assert renamed.success is True
    assert "def make_value" in sample
    assert "make_value()" in sample
    assert "VALUE = 'make_value'" in extra


async def test_execution_commands_run_test_run_command_and_check_syntax(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    registry = ACICommandRegistry(repo, default_timeout=15)
    context = _context(repo)

    command = await _execute(
        registry,
        "run_command",
        CommandCategory.EXECUTION,
        context,
        cmd="python3 -c 'print(123)'",
    )
    syntax = await _execute(
        registry,
        "check_syntax",
        CommandCategory.EXECUTION,
        context,
        file="pkg/sample.py",
    )
    tests = await _execute(
        registry,
        "run_test",
        CommandCategory.EXECUTION,
        context,
        test_path="tests/test_sample.py",
    )

    assert command.success is True
    assert "123" in command.output
    assert syntax.success is True
    assert tests.success is True
    assert "exit_code=0" in tests.output


async def test_execution_commands_report_lint_and_typecheck_failures_when_tools_missing(
    tmp_path: Path,
) -> None:
    repo = _write_repo(tmp_path)
    registry = ACICommandRegistry(repo, default_timeout=15)
    context = _context(repo)

    lint = await _execute(
        registry,
        "run_lint",
        CommandCategory.EXECUTION,
        context,
        file="pkg/sample.py",
    )
    typecheck = await _execute(
        registry,
        "run_typecheck",
        CommandCategory.EXECUTION,
        context,
        file="pkg/sample.py",
    )

    assert lint.command_id
    assert typecheck.command_id
    assert "ruff" in lint.output
    assert "mypy" in typecheck.output


async def test_context_commands_outline_related_changes_and_errors(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    registry = ACICommandRegistry(repo)
    context = _context(repo)

    outline = await _execute(
        registry,
        "get_file_outline",
        CommandCategory.CONTEXT,
        context,
        file="pkg/sample.py",
    )
    related = await _execute(
        registry,
        "get_related_files",
        CommandCategory.CONTEXT,
        context,
        file="pkg/sample.py",
    )
    recent = await _execute(registry, "get_recent_changes", CommandCategory.CONTEXT, context)
    bad = await _execute(
        registry,
        "check_syntax",
        CommandCategory.EXECUTION,
        context,
        file="missing.py",
    )
    errors = await _execute(registry, "summarize_errors", CommandCategory.CONTEXT, context)

    assert outline.success is True
    assert "class Widget:3" in outline.output
    assert related.success is True
    assert recent.command_id
    assert bad.success is False
    assert "missing.py" in errors.output


async def test_session_tracks_context_history_working_set_and_suggestions(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    session = ACISession(repo, active_task="aci-layer")

    opened = await session.execute("open_file", path="pkg/sample.py", line=7)
    searched = await session.execute("find_references", symbol="helper")
    context = await session.get_context()
    suggestions = await session.suggest_next_commands()

    assert opened.success is True
    assert searched.success is True
    assert context.current_file == "pkg/sample.py"
    assert context.cursor_line == 7
    assert context.open_files == ("pkg/sample.py",)
    assert context.recent_commands == ("open_file", "find_references")
    assert session.working_set == ("pkg/sample.py",)
    assert len(session.history) == 2
    assert "get_file_outline" in suggestions


async def test_session_records_command_history_to_event_journal(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    journal = EventJournal(tmp_path / "journal.jsonl")
    session = ACISession(repo, journal=journal, run_id="aci-run")

    response = await session.execute("open_file", path="pkg/sample.py")
    events = [event async for event in journal.read_from("aci-run")]

    assert response.success is True
    assert len(events) == 1
    assert events[0].type == "command.executed"
    assert events[0].payload["observation"]["aci_command"] == "open_file"


def test_feedback_formatter_formats_llm_friendly_outputs(tmp_path: Path) -> None:
    formatter = FeedbackFormatter(max_lines=4, max_chars=500)
    path = tmp_path / "sample.py"
    path.write_text("a\nb\nc\nd\ne\n", encoding="utf-8")
    diagnostic = Diagnostic(
        message="bad syntax",
        severity=DiagnosticSeverity.ERROR,
        path="sample.py",
        line=2,
        suggestion="Fix line 2.",
    )
    result = SearchResult(path="sample.py", line=1, snippet="def helper():", score=0.9)

    file_output = formatter.format_file(path, path.read_text(encoding="utf-8"), focus_line=2)
    search_output = formatter.format_search_results("helper", (result,))
    diagnostic_output = formatter.format_diagnostics((diagnostic,))
    diff_output = formatter.format_diff("sample.py", "old\n", "new\n")
    hints = formatter.navigation_hints(("open_file", "run_test"))

    assert "... truncated" in file_output
    assert ">    2 | b" in file_output
    assert "score=0.90" in search_output
    assert "Fix suggestion: Fix line 2." in diagnostic_output
    assert "--- sample.py:before" in diff_output
    assert "- open_file" in hints
