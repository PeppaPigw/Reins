from __future__ import annotations

import asyncio
from pathlib import Path

import ulid

from reins.execution.adapter import Adapter, Handle, Observation
from reins.kernel.types import ArtifactRef


class GitAdapter(Adapter):
    def __init__(self, adapter_id: str = "git.local") -> None:
        self.adapter_id = adapter_id
        self._repos: dict[str, Path] = {}

    async def open(self, spec: dict) -> Handle:
        repo = Path(spec["repo"]).resolve()
        handle = Handle(adapter_kind="git", adapter_id=self.adapter_id, metadata={"repo": str(repo)})
        self._repos[handle.handle_id] = repo
        return handle

    async def _run(self, repo: Path, *args: str) -> tuple[str, str, int]:
        process = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=repo,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        return stdout.decode(), stderr.decode(), process.returncode

    async def exec(self, handle: Handle, command: dict) -> Observation:
        repo = self._repos[handle.handle_id]
        op = command["op"]
        args = {
            "status": ("status", "--short"),
            "diff": ("diff", "--stat"),
            "log": ("log", f"-n{command.get('n', 10)}", "--oneline"),
            "branch": ("branch",) if "name" not in command else ("branch", command["name"]),
            "checkout": ("checkout", command["target"]),
        }.get(op)
        if op == "commit":
            if command.get("add_all", True):
                await self._run(repo, "add", "-A")
            stdout, stderr, code = await self._run(repo, "commit", "-m", command["message"])
            artifacts = await self._capture_commit_artifact(repo) if code == 0 else []
            return Observation(stdout, stderr, code, artifacts, {"op": op, "repo": str(repo)})
        if args is None:
            return Observation("", f"unsupported op: {op}", 1, effect_descriptor={"op": op})
        stdout, stderr, code = await self._run(repo, *args)
        return Observation(stdout, stderr, code, effect_descriptor={"op": op, "repo": str(repo)})

    async def _capture_commit_artifact(self, repo: Path) -> list[ArtifactRef]:
        artifact_dir = repo / ".reins-artifacts"
        artifact_dir.mkdir(exist_ok=True)
        stdout, _, _ = await self._run(repo, "show", "--stat", "--format=medium", "HEAD")
        path = artifact_dir / f"git-{ulid.new()}.txt"
        path.write_text(stdout)
        return [ArtifactRef(str(ulid.new()), "git.diff", path.as_uri())]

    async def snapshot(self, handle: Handle) -> str:
        repo = self._repos[handle.handle_id]
        head, _, _ = await self._run(repo, "rev-parse", "HEAD")
        status, _, _ = await self._run(repo, "status", "--short")
        return str({"head": head.strip(), "status": status.strip()})

    async def freeze(self, handle: Handle) -> dict:
        return {"handle_id": handle.handle_id, "repo": str(self._repos[handle.handle_id])}

    async def thaw(self, frozen: dict) -> Handle:
        repo = Path(frozen["repo"]).resolve()
        handle = Handle(
            adapter_kind="git",
            adapter_id=self.adapter_id,
            metadata={"repo": str(repo)},
            handle_id=frozen["handle_id"],
        )
        self._repos[handle.handle_id] = repo
        return handle

    async def reset(self, handle: Handle) -> Handle:
        new_handle = Handle(adapter_kind="git", adapter_id=self.adapter_id, metadata=handle.metadata)
        self._repos[new_handle.handle_id] = self._repos[handle.handle_id]
        self._repos.pop(handle.handle_id, None)
        return new_handle

    async def close(self, handle: Handle) -> None:
        self._repos.pop(handle.handle_id, None)
