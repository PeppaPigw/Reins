"""Context injection hooks for automatic subagent context delivery.

This module implements the core Trellis pattern used by the orchestration
layer:

- Read the active task from ``.reins/.current-task``
- Load ``task.json`` metadata from the active task directory
- Load agent-specific JSONL context (``implement.jsonl``, ``check.jsonl``, ...)
- Compile relevant specs from ``.reins/spec/`` automatically
- Append outcomes/errors back into task context files
- Emit context lifecycle events to the event journal
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ulid

from reins.context.checklist import Checklist, ChecklistParser
from reins.context.compiler import CompiledContext, ContextCompiler, ContextSource
from reins.kernel.event.builder import EventBuilder
from reins.kernel.event.journal import EventJournal
from reins.task.context_jsonl import ContextJSONL, ContextMessage
from reins.task.metadata import TaskStatus


class ContextInjectionHook:
    """Hook that injects task context before subagent execution."""

    def __init__(
        self,
        repo_root: Path,
        journal: EventJournal,
        context_compiler: ContextCompiler,
        *,
        spec_token_budget: int = 8_000,
    ) -> None:
        self.repo_root = repo_root
        self.journal = journal
        self.context_compiler = context_compiler
        self.spec_token_budget = spec_token_budget
        self._event_builder = EventBuilder(journal)
        self._reins_dir = repo_root / ".reins"
        self._current_task_file = self._reins_dir / ".current-task"

    async def before_subagent_spawn(
        self,
        agent_type: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Load structured task/spec context for a subagent."""
        context: dict[str, Any] = {
            "task_metadata": None,
            "agent_context": [],
            "specs": [],
            "checklist": None,
        }

        task_dir = self._resolve_current_task_dir()
        if task_dir is None:
            return context

        task_metadata = self._load_task_metadata(task_dir)
        agent_context = self._load_agent_context(task_dir, agent_type)
        spec_sources = self._build_spec_sources(task_metadata)
        specs = await self._compile_specs(spec_sources)
        checklist, updated_metadata = self._update_checklist_status(
            task_dir=task_dir,
            task_metadata=task_metadata,
            spec_sources=spec_sources,
            specs=specs,
        )

        context["task_metadata"] = updated_metadata
        context["agent_context"] = agent_context
        context["specs"] = specs
        context["checklist"] = checklist

        if checklist is not None and not checklist["complete"]:
            await self._event_builder.commit(
                run_id=self._resolve_run_id(run_id),
                event_type="checklist.incomplete",
                payload={
                    "agent_type": agent_type,
                    "task_id": self._task_id(updated_metadata),
                    "missing_files": checklist["missing_files"],
                    "unread_specs": checklist["unread_specs"],
                },
            )

        await self._emit_context_injected(
            run_id=run_id,
            agent_type=agent_type,
            stage="before_subagent_spawn",
            task_metadata=updated_metadata,
            agent_context=agent_context,
            specs=specs,
            checklist=checklist,
        )
        return context

    async def after_subagent_complete(
        self,
        agent_type: str,
        result: dict[str, Any],
        run_id: str | None = None,
    ) -> None:
        """Append subagent output to task context and update task state."""
        task_dir = self._resolve_current_task_dir()
        if task_dir is None:
            return

        result_message = ContextMessage(
            role="assistant",
            content=json.dumps(result, ensure_ascii=False, sort_keys=True),
            metadata={
                "agent_type": agent_type,
                "kind": "result",
                "result": result,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
        ContextJSONL.write_message(task_dir / f"{agent_type}.jsonl", result_message)

        task_metadata = self._load_task_metadata(task_dir)
        updated_metadata = self._update_task_status_from_result(task_dir, task_metadata, result)
        agent_context = self._load_agent_context(task_dir, agent_type)

        await self._emit_context_injected(
            run_id=run_id,
            agent_type=agent_type,
            stage="after_subagent_complete",
            task_metadata=updated_metadata,
            agent_context=agent_context,
            specs=[],
            checklist=None,
        )

    async def on_error(
        self,
        agent_type: str,
        error: Exception,
        run_id: str | None = None,
    ) -> None:
        """Append an error entry to ``debug.jsonl`` and emit a journal event."""
        task_dir = self._resolve_current_task_dir()
        if task_dir is None:
            return

        error_metadata = {
            "agent_type": agent_type,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        ContextJSONL.write_message(
            task_dir / "debug.jsonl",
            ContextMessage(
                role="system",
                content=f"{type(error).__name__}: {error}",
                metadata=error_metadata,
            ),
        )

        await self._event_builder.commit(
            run_id=self._resolve_run_id(run_id),
            event_type="context.error",
            payload=error_metadata,
        )

    def _resolve_current_task_dir(self) -> Path | None:
        if not self._current_task_file.exists():
            return None

        raw_pointer = self._current_task_file.read_text(encoding="utf-8").strip()
        if not raw_pointer:
            return None

        pointer_path = Path(raw_pointer)
        candidates: list[Path] = []
        if pointer_path.is_absolute():
            candidates.append(pointer_path)
        else:
            candidates.extend(
                [
                    self.repo_root / raw_pointer,
                    self._reins_dir / raw_pointer,
                ]
            )
            if "/" not in raw_pointer:
                candidates.append(self._reins_dir / "tasks" / raw_pointer)

        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _load_task_metadata(self, task_dir: Path) -> dict[str, Any] | None:
        task_json_path = task_dir / "task.json"
        if not task_json_path.exists():
            return None

        raw = json.loads(task_json_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        return raw

    def _load_agent_context(self, task_dir: Path, agent_type: str) -> list[dict[str, Any]]:
        return [
            message.to_dict()
            for message in ContextJSONL.read_messages(task_dir / f"{agent_type}.jsonl")
        ]

    async def _compile_specs(self, sources: list[ContextSource]) -> list[dict[str, Any]]:
        if not sources:
            return []

        compiled: CompiledContext = await self.context_compiler.compile_layered_sources(
            sources=sources,
            max_tokens=self.spec_token_budget,
            priority=["spec"],
        )
        return [
            {
                "identifier": section.identifier,
                "content": section.content,
                "priority": section.priority,
                "token_count": section.token_count,
                "metadata": section.metadata,
                "source_type": section.source_type,
            }
            for section in compiled.sections
        ]

    def _build_spec_sources(
        self,
        task_metadata: dict[str, Any] | None,
    ) -> list[ContextSource]:
        spec_root = self._reins_dir / "spec"
        if not spec_root.exists():
            return []

        task_type = "backend"
        package: str | None = None
        if task_metadata is not None:
            raw_type = task_metadata.get("task_type", task_metadata.get("type", "backend"))
            if isinstance(raw_type, str) and raw_type:
                task_type = raw_type
            metadata = task_metadata.get("metadata")
            if isinstance(metadata, dict):
                raw_package = metadata.get("package")
                if isinstance(raw_package, str) and raw_package:
                    package = raw_package

        return self.context_compiler.resolve_spec_sources(
            spec_root,
            task_type=task_type,
            package=package,
        )

    def _update_task_status_from_result(
        self,
        task_dir: Path,
        task_metadata: dict[str, Any] | None,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        if task_metadata is None:
            return None

        new_status = self._status_from_result(result)
        if new_status is None:
            return task_metadata

        now = datetime.now(UTC).isoformat()
        updated = dict(task_metadata)
        updated["status"] = new_status
        if new_status == TaskStatus.IN_PROGRESS.value and not updated.get("started_at"):
            updated["started_at"] = now
        if new_status == TaskStatus.COMPLETED.value and not updated.get("completed_at"):
            updated["completed_at"] = now

        (task_dir / "task.json").write_text(
            json.dumps(updated, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return updated

    def _status_from_result(self, result: dict[str, Any]) -> str | None:
        raw_status = result.get("status")
        valid_statuses = {status.value for status in TaskStatus}
        if isinstance(raw_status, str) and raw_status in valid_statuses:
            return raw_status
        if result.get("completed") is True:
            return TaskStatus.COMPLETED.value
        return None

    def _update_checklist_status(
        self,
        *,
        task_dir: Path,
        task_metadata: dict[str, Any] | None,
        spec_sources: list[ContextSource],
        specs: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        if task_metadata is None:
            return None, task_metadata

        read_specs = self._tracked_read_specs(task_metadata)
        read_specs.update(self._read_specs_from_compiled_context(specs))

        layers: list[dict[str, Any]] = []
        for source in spec_sources:
            if not source.path:
                continue
            source_path = Path(source.path)
            index_path = source_path / "index.md" if source_path.is_dir() else source_path
            checklist = ChecklistParser.parse(index_path)
            if checklist is None:
                continue

            relative_reads = self._relative_reads_for_checklist(checklist, read_specs)
            validation = checklist.validate_completion(relative_reads)
            layers.append(
                {
                    "identifier": source.identifier,
                    "index_path": self._relative_to_repo(index_path),
                    "layer": str(source.metadata.get("layer", source_path.name)),
                    "package": source.metadata.get("package"),
                    "package_specific": bool(source.metadata.get("package_specific", False)),
                    "complete": validation.is_complete,
                    "completed_count": validation.completed_count,
                    "total_items": validation.total_items,
                    "missing_files": validation.missing_files,
                    "unread_specs": validation.incomplete_items,
                    "completed_specs": validation.completed_items,
                    "items": [
                        self._serialize_checklist_item(checklist, item, relative_reads)
                        for item in checklist.items
                    ],
                }
            )

        if not layers:
            return None, task_metadata

        checklist_status = {
            "complete": all(layer["complete"] for layer in layers),
            "validated_at": datetime.now(UTC).isoformat(),
            "read_specs": sorted(read_specs),
            "layers": layers,
            "missing_files": sorted({path for layer in layers for path in layer["missing_files"]}),
            "unread_specs": [
                item
                for layer in layers
                for item in layer["unread_specs"]
            ],
        }

        updated = dict(task_metadata)
        metadata = dict(updated.get("metadata") or {})
        metadata["checklist"] = checklist_status
        updated["metadata"] = metadata
        (task_dir / "task.json").write_text(
            json.dumps(updated, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return checklist_status, updated

    def _tracked_read_specs(self, task_metadata: dict[str, Any]) -> set[str]:
        metadata = task_metadata.get("metadata")
        if not isinstance(metadata, dict):
            return set()
        checklist = metadata.get("checklist")
        if not isinstance(checklist, dict):
            return set()
        read_specs = checklist.get("read_specs", [])
        if not isinstance(read_specs, list):
            return set()
        return {self._normalize_spec_path(item) for item in read_specs if isinstance(item, str)}

    def _read_specs_from_compiled_context(self, specs: list[dict[str, Any]]) -> set[str]:
        spec_root = (self._reins_dir / "spec").resolve()
        read_specs: set[str] = set()
        for spec in specs:
            metadata = spec.get("metadata")
            if not isinstance(metadata, dict):
                continue
            raw_path = metadata.get("path")
            if not isinstance(raw_path, str):
                continue
            try:
                path = Path(raw_path).resolve()
                relative = path.relative_to(spec_root)
            except ValueError:
                continue
            read_specs.add(self._normalize_spec_path(relative))
        return read_specs

    def _relative_reads_for_checklist(
        self,
        checklist: Checklist,
        read_specs: set[str],
    ) -> set[str]:
        spec_root = (self._reins_dir / "spec").resolve()
        checklist_root = checklist.spec_dir.resolve()
        relative_reads: set[str] = set()
        for read_spec in read_specs:
            path = (spec_root / read_spec).resolve()
            if not path.is_relative_to(checklist_root):
                continue
            relative_reads.add(path.relative_to(checklist_root).as_posix())
        return relative_reads

    def _serialize_checklist_item(
        self,
        checklist: Checklist,
        item: Any,
        read_specs: set[str],
    ) -> dict[str, Any]:
        normalized_target = None
        if item.target is not None:
            target_path = (checklist.spec_dir / item.target).resolve()
            try:
                normalized_target = self._normalize_spec_path(
                    target_path.relative_to((self._reins_dir / "spec").resolve())
                )
            except ValueError:
                normalized_target = self._normalize_spec_path(item.target)

        return {
            "text": item.text,
            "target": normalized_target,
            "description": item.description,
            "checked": item.checked,
            "complete": checklist._is_item_completed(item, read_specs),
            "level": item.level,
            "children": [
                self._serialize_checklist_item(checklist, child, read_specs)
                for child in item.children
            ],
        }

    def _relative_to_repo(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.repo_root.resolve()).as_posix()
        except ValueError:
            return path.as_posix()

    def _normalize_spec_path(self, path: str | Path) -> str:
        raw = path.as_posix() if isinstance(path, Path) else str(path)
        return raw.replace("\\", "/").lstrip("./")

    async def _emit_context_injected(
        self,
        *,
        run_id: str | None,
        agent_type: str,
        stage: str,
        task_metadata: dict[str, Any] | None,
        agent_context: list[dict[str, Any]],
        specs: list[dict[str, Any]],
        checklist: dict[str, Any] | None,
    ) -> None:
        payload = {
            "agent_type": agent_type,
            "stage": stage,
            "task_id": self._task_id(task_metadata),
            "agent_context_count": len(agent_context),
            "specs_count": len(specs),
            "spec_identifiers": [spec["identifier"] for spec in specs],
            "checklist": checklist,
        }
        await self._event_builder.commit(
            run_id=self._resolve_run_id(run_id),
            event_type="context.injected",
            payload=payload,
        )

    def _task_id(self, task_metadata: dict[str, Any] | None) -> str | None:
        if task_metadata is None:
            return None
        raw_task_id = task_metadata.get("task_id", task_metadata.get("id"))
        return raw_task_id if isinstance(raw_task_id, str) else None

    def _resolve_run_id(self, run_id: str | None) -> str:
        if run_id:
            return run_id
        return f"context-hook-{ulid.new()}"
