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
        }

        task_dir = self._resolve_current_task_dir()
        if task_dir is None:
            return context

        task_metadata = self._load_task_metadata(task_dir)
        agent_context = self._load_agent_context(task_dir, agent_type)
        specs = await self._compile_specs(task_metadata)

        context["task_metadata"] = task_metadata
        context["agent_context"] = agent_context
        context["specs"] = specs

        await self._emit_context_injected(
            run_id=run_id,
            agent_type=agent_type,
            stage="before_subagent_spawn",
            task_metadata=task_metadata,
            agent_context=agent_context,
            specs=specs,
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

    async def _compile_specs(self, task_metadata: dict[str, Any] | None) -> list[dict[str, Any]]:
        sources = self._build_spec_sources(task_metadata)
        if not sources:
            return []

        compiled: CompiledContext = await self.context_compiler.compile_sources(
            sources=sources,
            optimize=True,
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

        paths: list[tuple[Path, str, float]] = []
        if package:
            package_dir = spec_root / package
            if package_dir.exists():
                paths.append((package_dir, f"package:{package}", 120.0))

        if task_type in {"backend", "fullstack"}:
            backend_dir = spec_root / "backend"
            if backend_dir.exists():
                paths.append((backend_dir, "backend", 100.0))

        if task_type in {"frontend", "fullstack"}:
            frontend_dir = spec_root / "frontend"
            if frontend_dir.exists():
                paths.append((frontend_dir, "frontend", 100.0))

        guides_dir = spec_root / "guides"
        if guides_dir.exists():
            paths.append((guides_dir, "guides", 90.0))

        sources: list[ContextSource] = []
        seen: set[str] = set()
        for path, identifier, priority in paths:
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            sources.append(
                ContextSource(
                    type="spec",
                    path=str(path),
                    identifier=identifier,
                    priority=priority,
                )
            )
        return sources

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

    async def _emit_context_injected(
        self,
        *,
        run_id: str | None,
        agent_type: str,
        stage: str,
        task_metadata: dict[str, Any] | None,
        agent_context: list[dict[str, Any]],
        specs: list[dict[str, Any]],
    ) -> None:
        payload = {
            "agent_type": agent_type,
            "stage": stage,
            "task_id": self._task_id(task_metadata),
            "agent_context_count": len(agent_context),
            "specs_count": len(specs),
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
