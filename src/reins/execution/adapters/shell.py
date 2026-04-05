from __future__ import annotations

import asyncio
from pathlib import Path

from reins.execution.adapter import Adapter, Handle, Observation


class ShellAdapter(Adapter):
    def __init__(self, adapter_id: str = "shell.local") -> None:
        self.adapter_id = adapter_id
        self._sessions: dict[str, dict] = {}

    async def open(self, spec: dict) -> Handle:
        cwd = str(Path(spec.get("cwd", ".")).resolve())
        env = dict(spec.get("env", {}))
        handle = Handle(adapter_kind="shell", adapter_id=self.adapter_id, metadata={"cwd": cwd})
        self._sessions[handle.handle_id] = {"cwd": cwd, "env": env, "history": []}
        return handle

    async def exec(self, handle: Handle, command: dict) -> Observation:
        session = self._sessions[handle.handle_id]
        cmd = command["cmd"]
        cwd = command.get("cwd", session["cwd"])
        env = session["env"] | command.get("env", {})
        process = await asyncio.create_subprocess_shell(
            cmd,
            cwd=cwd,
            env=env or None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        session["cwd"] = str(Path(cwd).resolve())
        session["history"].append({"cmd": cmd, "exit_code": process.returncode})
        return Observation(
            stdout=stdout.decode(),
            stderr=stderr.decode(),
            exit_code=process.returncode,
            effect_descriptor={"cmd": cmd, "cwd": session["cwd"]},
        )

    async def snapshot(self, handle: Handle) -> str:
        session = self._sessions[handle.handle_id]
        history = session["history"][-10:]
        return str({"cwd": session["cwd"], "env": session["env"], "history": history})

    async def freeze(self, handle: Handle) -> dict:
        session = self._sessions[handle.handle_id]
        return {
            "handle_id": handle.handle_id,
            "adapter_id": self.adapter_id,
            "cwd": session["cwd"],
            "env": session["env"],
            "history": session["history"][-20:],
            "restored_process": False,
        }

    async def thaw(self, frozen: dict) -> Handle:
        handle = Handle(
            adapter_kind="shell",
            adapter_id=frozen.get("adapter_id", self.adapter_id),
            metadata={"cwd": frozen["cwd"], "restored_process": False},
            handle_id=frozen["handle_id"],
        )
        self._sessions[handle.handle_id] = {
            "cwd": frozen["cwd"],
            "env": frozen.get("env", {}),
            "history": frozen.get("history", []),
        }
        return handle

    async def reset(self, handle: Handle) -> Handle:
        session = self._sessions[handle.handle_id]
        new_handle = Handle(
            adapter_kind="shell",
            adapter_id=self.adapter_id,
            metadata={"cwd": session["cwd"]},
        )
        self._sessions[new_handle.handle_id] = {"cwd": session["cwd"], "env": session["env"], "history": []}
        self._sessions.pop(handle.handle_id, None)
        return new_handle

    async def close(self, handle: Handle) -> None:
        self._sessions.pop(handle.handle_id, None)
