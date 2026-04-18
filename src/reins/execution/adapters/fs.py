from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from reins.execution.adapter import Adapter, Handle, Observation


class FilesystemAdapter(Adapter):
    def __init__(self, adapter_id: str = "fs.local") -> None:
        self.adapter_id = adapter_id
        self._roots: dict[str, Path] = {}

    async def open(self, spec: dict) -> Handle:
        root = Path(spec.get("root", ".")).resolve()
        root.mkdir(parents=True, exist_ok=True)
        handle = Handle(
            adapter_kind="fs", adapter_id=self.adapter_id, metadata={"root": str(root)}
        )
        self._roots[handle.handle_id] = root
        return handle

    async def exec(self, handle: Handle, command: dict) -> Observation:
        root = self._roots[handle.handle_id]
        op = command["op"]

        # Validate path containment
        rel_path = command.get("path", "")
        target = (root / rel_path).resolve()
        if not self._is_contained(target, root):
            return Observation(
                "",
                f"path escape attempt: {rel_path} resolves outside workspace",
                1,
                effect_descriptor={"op": op, "path": rel_path, "error": "path_escape"},
            )

        if op == "read":
            return Observation(
                target.read_text(),
                "",
                0,
                effect_descriptor={"op": op, "path": str(target)},
            )
        if op == "write":
            target.parent.mkdir(parents=True, exist_ok=True)
            content = command.get("content", "")
            target.write_text(content)
            return Observation(
                str(len(content)),
                "",
                0,
                effect_descriptor={"op": op, "path": str(target)},
            )
        if op == "list":
            entries = sorted(path.name for path in target.iterdir())
            return Observation(
                "\n".join(entries),
                "",
                0,
                effect_descriptor={"op": op, "path": str(target)},
            )
        if op == "delete":
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
            return Observation(
                str(target), "", 0, effect_descriptor={"op": op, "path": str(target)}
            )
        if op == "move":
            dest_rel = command["dest"]
            destination = (root / dest_rel).resolve()
            if not self._is_contained(destination, root):
                return Observation(
                    "",
                    f"path escape attempt: {dest_rel} resolves outside workspace",
                    1,
                    effect_descriptor={
                        "op": op,
                        "dest": dest_rel,
                        "error": "path_escape",
                    },
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target), str(destination))
            return Observation(
                str(destination),
                "",
                0,
                effect_descriptor={"op": op, "path": str(target)},
            )
        if op == "exists":
            return Observation(
                str(target.exists()).lower(),
                "",
                0,
                effect_descriptor={"op": op, "path": str(target)},
            )
        return Observation(
            "",
            f"unsupported op: {op}",
            1,
            effect_descriptor={"op": op, "path": str(target)},
        )

    async def snapshot(self, handle: Handle) -> str:
        root = self._roots[handle.handle_id]
        digest = hashlib.sha256()
        for path in sorted(root.rglob("*")):
            digest.update(str(path.relative_to(root)).encode())
            digest.update(b"/" if path.is_dir() else b"")
        return digest.hexdigest()

    async def freeze(self, handle: Handle) -> dict:
        return {
            "handle_id": handle.handle_id,
            "adapter_kind": handle.adapter_kind,
            "adapter_id": handle.adapter_id,
            "root": str(self._roots[handle.handle_id]),
        }

    async def thaw(self, frozen: dict) -> Handle:
        root = Path(frozen["root"]).resolve()
        handle = Handle(
            adapter_kind=frozen.get("adapter_kind", "fs"),
            adapter_id=frozen.get("adapter_id", self.adapter_id),
            metadata={"root": str(root)},
            handle_id=frozen["handle_id"],
        )
        self._roots[handle.handle_id] = root
        return handle

    async def reset(self, handle: Handle) -> Handle:
        new_handle = Handle(
            adapter_kind="fs", adapter_id=self.adapter_id, metadata=handle.metadata
        )
        self._roots[new_handle.handle_id] = self._roots[handle.handle_id]
        self._roots.pop(handle.handle_id, None)
        return new_handle

    async def close(self, handle: Handle) -> None:
        self._roots.pop(handle.handle_id, None)

    @staticmethod
    def _is_contained(target: Path, root: Path) -> bool:
        """Check if target path is contained within root directory."""
        try:
            target.relative_to(root)
            return True
        except ValueError:
            return False
