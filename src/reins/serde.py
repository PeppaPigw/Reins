from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import aiofiles


def to_primitive(value: Any) -> Any:
    if is_dataclass(value):
        return {key: to_primitive(item) for key, item in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {key: to_primitive(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_primitive(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(to_primitive(value), sort_keys=True, separators=(",", ":"))


def pretty_json(value: Any) -> str:
    return json.dumps(to_primitive(value), indent=2, sort_keys=True)


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


async def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    async with aiofiles.open(temp_path, "w", encoding="utf-8") as handle:
        await handle.write(pretty_json(value))
        await handle.flush()
        await asyncio.to_thread(os.fsync, handle.fileno())
    temp_path.replace(path)


async def read_json(path: Path) -> Any:
    async with aiofiles.open(path, "r", encoding="utf-8") as handle:
        return json.loads(await handle.read())
