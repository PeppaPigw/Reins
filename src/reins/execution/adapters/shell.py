from __future__ import annotations

import asyncio
import os
from pathlib import Path

from reins.execution.adapter import Adapter, Handle, Observation


class SandboxedShellAdapter(Adapter):
    """Shell adapter with network disabled and restricted environment.

    For exec.shell.sandboxed capability (T1 risk tier).
    """

    def __init__(self, adapter_id: str = "shell.sandboxed") -> None:
        self.adapter_id = adapter_id
        self._sessions: dict[str, dict] = {}
        self._handle_kind = "shell_sandboxed"

    async def open(self, spec: dict) -> Handle:
        cwd = str(Path(spec.get("cwd", ".")).resolve())
        env = dict(spec.get("env", {}))
        handle = Handle(
            adapter_kind=self._handle_kind,
            adapter_id=self.adapter_id,
            metadata={"cwd": cwd, "sandboxed": True},
        )
        self._sessions[handle.handle_id] = {"cwd": cwd, "env": env, "history": []}
        return handle

    async def exec(self, handle: Handle, command: dict) -> Observation:
        session = self._sessions[handle.handle_id]
        cmd = command["cmd"]
        cwd = command.get("cwd", session["cwd"])

        # Build restricted environment
        env = self._build_sandboxed_env(session["env"], command.get("env", {}))

        process = await asyncio.create_subprocess_shell(
            cmd,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        session["cwd"] = str(Path(cwd).resolve())
        session["history"].append({"cmd": cmd, "exit_code": process.returncode})
        return Observation(
            stdout=stdout.decode(),
            stderr=stderr.decode(),
            exit_code=int(process.returncode or 0),
            effect_descriptor={"cmd": cmd, "cwd": session["cwd"], "sandboxed": True},
        )

    @staticmethod
    def _build_sandboxed_env(base_env: dict, command_env: dict) -> dict:
        """Build environment with network restrictions."""
        # Start with minimal safe environment
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
            "USER": os.environ.get("USER", "sandbox"),
            "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        }
        # Add base env (from spec)
        env.update(base_env)
        # Add command-specific env
        env.update(command_env)
        # Remove network-related variables
        for key in [
            "http_proxy",
            "https_proxy",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "no_proxy",
            "NO_PROXY",
        ]:
            env.pop(key, None)
        return env

    async def snapshot(self, handle: Handle) -> str:
        session = self._sessions[handle.handle_id]
        history = session["history"][-10:]
        return str({"cwd": session["cwd"], "env": session["env"], "history": history})

    async def freeze(self, handle: Handle) -> dict:
        session = self._sessions[handle.handle_id]
        return {
            "handle_id": handle.handle_id,
            "adapter_kind": handle.adapter_kind,
            "adapter_id": self.adapter_id,
            "cwd": session["cwd"],
            "env": session["env"],
            "history": session["history"][-20:],
        }

    async def thaw(self, frozen: dict) -> Handle:
        handle = Handle(
            adapter_kind=frozen.get("adapter_kind", self._handle_kind),
            adapter_id=frozen.get("adapter_id", self.adapter_id),
            metadata={"cwd": frozen["cwd"], "sandboxed": True},
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
            adapter_kind=self._handle_kind,
            adapter_id=self.adapter_id,
            metadata={"cwd": session["cwd"], "sandboxed": True},
        )
        self._sessions[new_handle.handle_id] = {
            "cwd": session["cwd"],
            "env": session["env"],
            "history": [],
        }
        self._sessions.pop(handle.handle_id, None)
        return new_handle

    async def close(self, handle: Handle) -> None:
        self._sessions.pop(handle.handle_id, None)


class NetworkShellAdapter(Adapter):
    """Shell adapter with network access enabled.

    For exec.shell.network capability (T2 risk tier).
    """

    def __init__(self, adapter_id: str = "shell.network") -> None:
        self.adapter_id = adapter_id
        self._sessions: dict[str, dict] = {}
        self._handle_kind = "shell_network"

    async def open(self, spec: dict) -> Handle:
        cwd = str(Path(spec.get("cwd", ".")).resolve())
        env = dict(spec.get("env", {}))
        handle = Handle(
            adapter_kind=self._handle_kind,
            adapter_id=self.adapter_id,
            metadata={"cwd": cwd, "network": True},
        )
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
            exit_code=int(process.returncode or 0),
            effect_descriptor={"cmd": cmd, "cwd": session["cwd"], "network": True},
        )

    async def snapshot(self, handle: Handle) -> str:
        session = self._sessions[handle.handle_id]
        history = session["history"][-10:]
        return str({"cwd": session["cwd"], "env": session["env"], "history": history})

    async def freeze(self, handle: Handle) -> dict:
        session = self._sessions[handle.handle_id]
        return {
            "handle_id": handle.handle_id,
            "adapter_kind": handle.adapter_kind,
            "adapter_id": self.adapter_id,
            "cwd": session["cwd"],
            "env": session["env"],
            "history": session["history"][-20:],
        }

    async def thaw(self, frozen: dict) -> Handle:
        handle = Handle(
            adapter_kind=frozen.get("adapter_kind", self._handle_kind),
            adapter_id=frozen.get("adapter_id", self.adapter_id),
            metadata={"cwd": frozen["cwd"], "network": True},
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
            adapter_kind=self._handle_kind,
            adapter_id=self.adapter_id,
            metadata={"cwd": session["cwd"], "network": True},
        )
        self._sessions[new_handle.handle_id] = {
            "cwd": session["cwd"],
            "env": session["env"],
            "history": [],
        }
        self._sessions.pop(handle.handle_id, None)
        return new_handle

    async def close(self, handle: Handle) -> None:
        self._sessions.pop(handle.handle_id, None)


# Backward compatibility alias
ShellAdapter = NetworkShellAdapter
