from __future__ import annotations

from dataclasses import dataclass

from reins.execution.adapter import Adapter, Handle, Observation
from reins.execution.adapters.fs import FilesystemAdapter
from reins.execution.adapters.git import GitAdapter
from reins.execution.adapters.mcp_adapter import McpAdapter
from reins.execution.adapters.shell import NetworkShellAdapter, SandboxedShellAdapter
from reins.execution.adapters.test_runner import TestRunnerAdapter
from reins.kernel.intent.envelope import CommandEnvelope
from reins.kernel.types import HandleRef
from reins.serde import canonical_json


@dataclass(frozen=True)
class DispatchResult:
    observation: Observation
    handle_ref: HandleRef
    opened_new_handle: bool


class ExecutionDispatcher:
    """Dispatches trusted commands through handle-based adapters."""

    def __init__(self, adapters: dict[str, Adapter] | None = None) -> None:
        self._adapters = adapters or {
            "fs": FilesystemAdapter(),
            "git": GitAdapter(),
            "shell_sandboxed": SandboxedShellAdapter(),
            "shell_network": NetworkShellAdapter(),
            "test": TestRunnerAdapter(),
            "mcp": McpAdapter(),
        }
        self._handles: dict[str, Handle] = {}

    def supports(self, capability: str) -> bool:
        return capability in {
            "fs.read",
            "fs.write.workspace",
            "git.status",
            "git.commit",
            "exec.shell.sandboxed",
            "exec.shell.network",
            "test.run",
            "mcp.tool.invoke",
            "mcp.resource.read",
            "mcp.prompt.get",
        }

    async def dispatch(self, run_id: str, command: CommandEnvelope) -> DispatchResult:
        adapter_kind, open_spec, adapter_command = self._resolve(command)
        adapter = self._adapters[adapter_kind]
        key = self._handle_key(run_id, adapter_kind, open_spec)
        handle = self._handles.get(key)
        opened_new_handle = handle is None
        if handle is None:
            handle = await adapter.open(open_spec)
            self._handles[key] = handle
        observation = await adapter.exec(handle, adapter_command)
        return DispatchResult(
            observation=observation,
            handle_ref=HandleRef(
                handle_id=handle.handle_id,
                adapter_kind=handle.adapter_kind,
                adapter_id=handle.adapter_id,
            ),
            opened_new_handle=opened_new_handle,
        )

    async def freeze_run(self, run_id: str) -> list[dict]:
        frozen: list[dict] = []
        for key, handle in self._handles.items():
            if not key.startswith(f"{run_id}:"):
                continue
            adapter = self._adapters[handle.adapter_kind]
            frozen.append(await adapter.freeze(handle))
        return frozen

    async def thaw_run(self, run_id: str, frozen_handles: list[dict]) -> list[HandleRef]:
        restored: list[HandleRef] = []
        for frozen in frozen_handles:
            adapter_kind = frozen["adapter_kind"]
            adapter = self._adapters[adapter_kind]
            handle = await adapter.thaw(frozen)
            open_spec = self._open_spec_from_frozen(adapter_kind, frozen)
            key = self._handle_key(run_id, adapter_kind, open_spec)
            self._handles[key] = handle
            restored.append(
                HandleRef(
                    handle_id=handle.handle_id,
                    adapter_kind=handle.adapter_kind,
                    adapter_id=handle.adapter_id,
                )
            )
        return restored

    @staticmethod
    def _handle_key(run_id: str, adapter_kind: str, open_spec: dict) -> str:
        return f"{run_id}:{adapter_kind}:{canonical_json(open_spec)}"

    @staticmethod
    def _open_spec_from_frozen(adapter_kind: str, frozen: dict) -> dict:
        if adapter_kind == "fs":
            return {"root": frozen["root"]}
        if adapter_kind == "git":
            return {"repo": frozen["repo"]}
        if adapter_kind == "shell_sandboxed" or adapter_kind == "shell_network":
            return {"cwd": frozen["cwd"], "env": frozen.get("env", {})}
        if adapter_kind == "test":
            metadata = frozen.get("metadata", {})
            return {
                "root": metadata.get("root", "."),
                "framework": metadata.get("framework", "pytest"),
            }
        if adapter_kind == "mcp":
            return {"server_id": frozen["server_id"]}
        raise ValueError(f"unsupported adapter kind: {adapter_kind}")

    @staticmethod
    def _resolve(command: CommandEnvelope) -> tuple[str, dict, dict]:
        capability = command.normalized_kind
        args = command.args
        if capability == "fs.read":
            return (
                "fs",
                {"root": args.get("root", ".")},
                {"op": "read", "path": args["path"]},
            )
        if capability == "fs.write.workspace":
            return (
                "fs",
                {"root": args.get("root", ".")},
                {
                    "op": "write",
                    "path": args["path"],
                    "content": args.get("content", ""),
                },
            )
        if capability == "git.status":
            return (
                "git",
                {"repo": args.get("repo", args.get("cwd", "."))},
                {"op": "status"},
            )
        if capability == "git.commit":
            return (
                "git",
                {"repo": args.get("repo", args.get("cwd", "."))},
                {
                    "op": "commit",
                    "message": args["message"],
                    "add_all": args.get("add_all", True),
                },
            )
        if capability in {"exec.shell.sandboxed", "exec.shell.network"}:
            cwd = args.get("cwd", ".")
            env = args.get("env", {})
            adapter_kind = "shell_sandboxed" if capability == "exec.shell.sandboxed" else "shell_network"
            return (
                adapter_kind,
                {"cwd": cwd, "env": env},
                {"cmd": args["cmd"], "cwd": cwd, "env": env},
            )
        if capability == "test.run":
            return (
                "test",
                {
                    "root": args.get("root", "."),
                    "framework": args.get("framework", "pytest"),
                },
                {
                    "op": "run",
                    "target": args.get("target", "tests/"),
                    "args": args.get("args", []),
                },
            )
        if capability == "mcp.tool.invoke":
            server_id = args.get("server_id", "default")
            return (
                "mcp",
                {"server_id": server_id, "name": args.get("name", server_id), "endpoint": args.get("endpoint", "")},
                {
                    "op": "invoke_tool",
                    "tool_name": args["tool_name"],
                    "args": args.get("args", {}),
                    "run_id": args.get("run_id", ""),
                },
            )
        if capability == "mcp.resource.read":
            server_id = args.get("server_id", "default")
            return (
                "mcp",
                {"server_id": server_id, "name": args.get("name", server_id), "endpoint": args.get("endpoint", "")},
                {"op": "read_resource", "uri": args["uri"]},
            )
        if capability == "mcp.prompt.get":
            server_id = args.get("server_id", "default")
            return (
                "mcp",
                {"server_id": server_id, "name": args.get("name", server_id), "endpoint": args.get("endpoint", "")},
                {"op": "get_prompt", "name": args["prompt_name"], "args": args.get("args", {})},
            )
        raise ValueError(f"unsupported capability for dispatcher: {capability}")
