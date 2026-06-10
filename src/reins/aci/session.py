from __future__ import annotations

from pathlib import Path

from reins.aci.commands import ACICommandRegistry
from reins.aci.types import (
    ACICommand,
    ACIResponse,
    CommandCategory,
    CommandContext,
    SearchResult,
    new_ulid,
)
from reins.kernel.event.builder import EventBuilder
from reins.kernel.event.journal import EventJournal


class ACISession:
    """Manages an ACI session with context tracking."""

    def __init__(
        self,
        working_directory: str | Path,
        *,
        session_id: str | None = None,
        active_task: str | None = None,
        registry: ACICommandRegistry | None = None,
        journal: EventJournal | None = None,
        run_id: str | None = None,
    ) -> None:
        self.working_directory = Path(working_directory).resolve()
        self.session_id = session_id or new_ulid()
        self.active_task = active_task
        self.registry = registry or ACICommandRegistry(self.working_directory)
        self.run_id = run_id or self.session_id
        self._event_builder = EventBuilder(journal) if journal is not None else None
        self._current_file: str | None = None
        self._cursor_line: int | None = None
        self._open_files: tuple[str, ...] = ()
        self._recent_commands: tuple[str, ...] = ()
        self._search_results: tuple[SearchResult, ...] | None = None
        self._working_set: tuple[str, ...] = ()
        self._history: list[ACIResponse] = []

    @property
    def context(self) -> CommandContext:
        return CommandContext(
            working_directory=str(self.working_directory),
            current_file=self._current_file,
            cursor_line=self._cursor_line,
            open_files=self._open_files,
            recent_commands=self._recent_commands,
            active_task=self.active_task,
            search_results=self._search_results,
        )

    @property
    def working_set(self) -> tuple[str, ...]:
        return self._working_set

    @property
    def history(self) -> tuple[ACIResponse, ...]:
        return tuple(self._history)

    async def execute(
        self,
        name: str,
        *,
        category: CommandCategory | None = None,
        **args: object,
    ) -> ACIResponse:
        definition = self.registry.discover()
        inferred = next((item.category for item in definition if item.name == name), None)
        command = ACICommand(
            name=name,
            category=category or inferred or CommandCategory.CONTEXT,
            args=dict(args),
            context=self.context,
        )
        response = await self.registry.execute(command)
        self._record(command, response)
        await self._audit(command, response)
        return response

    async def get_context(self) -> CommandContext:
        return self.context

    async def suggest_next_commands(self) -> tuple[str, ...]:
        context = self.context
        if self._history and not self._history[-1].success:
            return ("summarize_errors", "open_file", "run_test")
        if context.current_file:
            if context.current_file.endswith(".py"):
                return ("get_file_outline", "check_syntax", "run_test")
            return ("open_file", "search_codebase")
        if context.search_results:
            return ("open_file", "find_references")
        return ("list_directory", "search_codebase", "get_recent_changes")

    def _record(self, command: ACICommand, response: ACIResponse) -> None:
        self._recent_commands = (*self._recent_commands, command.name)[-5:]
        self._history.append(response)
        if command.name in {"search_codebase", "find_definition", "find_references"}:
            self._search_results = self.registry.last_search_results
        update = response.context_update
        if update is None:
            return
        if update.new_file:
            self._current_file = update.new_file
            self._open_files = self._append_unique(self._open_files, update.new_file, limit=12)
            self._working_set = self._append_unique(self._working_set, update.new_file, limit=20)
        if update.new_cursor_line is not None:
            self._cursor_line = update.new_cursor_line
        for path in (*update.files_modified, *update.files_created):
            self._working_set = self._append_unique(self._working_set, path, limit=20)

    async def _audit(self, command: ACICommand, response: ACIResponse) -> None:
        if self._event_builder is None:
            return
        await self._event_builder.emit_command_executed(
            self.run_id,
            command.command_id,
            {
                "aci_command": command.name,
                "category": command.category.value,
                "success": response.success,
                "diagnostics": [item.model_dump(mode="json") for item in response.diagnostics],
                "context_update": response.context_update.model_dump(mode="json")
                if response.context_update
                else None,
            },
        )

    def _append_unique(self, items: tuple[str, ...], item: str, *, limit: int) -> tuple[str, ...]:
        without = tuple(existing for existing in items if existing != item)
        return (*without, item)[-limit:]
