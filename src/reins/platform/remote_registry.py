"""Remote and local spec registry helpers.

This module keeps registry fetching intentionally small and dependency-free so
CLI commands can install specs from local paths today while still supporting
simple remote URL forms such as ``github:`` and ``npm:`` when networking is
available.
"""

from __future__ import annotations

import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable
from urllib.error import URLError
from urllib.request import urlopen


class RemoteRegistryError(RuntimeError):
    """Raised when a remote or local registry cannot be resolved."""


@dataclass(frozen=True)
class RemoteSpecAsset:
    """A single spec asset resolved from a registry source."""

    relative_path: str
    content: str
    source: str


@dataclass(frozen=True)
class RemoteRegistryResponse:
    """A resolved set of spec files from a registry source."""

    source: str
    assets: list[RemoteSpecAsset]


class RemoteSpecRegistry:
    """Resolve spec files from local paths or lightweight remote sources."""

    TEXT_EXTENSIONS = {
        ".md",
        ".markdown",
        ".yaml",
        ".yml",
        ".json",
        ".txt",
    }

    def fetch(
        self,
        reference: str,
        *,
        remote: str | None = None,
    ) -> RemoteRegistryResponse:
        """Fetch spec assets from ``reference`` and optional ``remote`` base.

        ``reference`` is interpreted as:
        - a local file or directory path
        - a relative child path when ``remote`` points at a local directory
        - a direct URL or custom shorthand (``github:``, ``npm:``)
        """

        source = self._resolve_source(reference, remote=remote)
        if isinstance(source, Path) and source.is_file():
            asset = RemoteSpecAsset(
                relative_path=source.name,
                content=source.read_text(encoding="utf-8"),
                source=str(source),
            )
            return RemoteRegistryResponse(source=str(source), assets=[asset])
        if isinstance(source, Path) and source.is_dir():
            assets = self._read_local_directory(source)
            return RemoteRegistryResponse(source=str(source), assets=assets)

        url = self._coerce_remote_url(str(source))
        return RemoteRegistryResponse(source=url, assets=self._read_remote(url))

    def _resolve_source(self, reference: str, *, remote: str | None) -> Path | str:
        if remote:
            remote_path = Path(remote)
            if remote_path.exists():
                base = remote_path.resolve()
                if reference in {".", "./", "/"}:
                    return base
                candidate = base / reference
                if candidate.exists():
                    return candidate.resolve()
                if base.is_file():
                    return base
                raise RemoteRegistryError(
                    f"Spec '{reference}' not found under local registry {base}."
                )

            if remote.startswith(("http://", "https://", "github:", "npm:")):
                if reference in {".", "./", "/"}:
                    return remote
                return f"{remote.rstrip('/')}/{reference.lstrip('/')}"

            return remote

        reference_path = Path(reference)
        if reference_path.exists():
            return reference_path.resolve()

        if reference.startswith(("http://", "https://", "github:", "npm:")):
            return reference

        raise RemoteRegistryError(f"Could not resolve registry source: {reference}")

    def _read_local_directory(self, root: Path) -> list[RemoteSpecAsset]:
        assets: list[RemoteSpecAsset] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.name.startswith("."):
                continue
            if path.suffix.lower() not in self.TEXT_EXTENSIONS:
                continue
            assets.append(
                RemoteSpecAsset(
                    relative_path=path.relative_to(root).as_posix(),
                    content=path.read_text(encoding="utf-8"),
                    source=str(path),
                )
            )
        if not assets:
            raise RemoteRegistryError(f"No spec assets found in {root}")
        return assets

    def _read_remote(self, url: str) -> list[RemoteSpecAsset]:
        try:
            with urlopen(url) as response:  # noqa: S310 - user-requested fetch surface
                payload = response.read()
                content_type = response.headers.get("content-type", "")
        except URLError as exc:
            raise RemoteRegistryError(f"Failed to fetch remote registry {url}: {exc}") from exc

        text = payload.decode("utf-8")
        if "json" in content_type or url.endswith(".json"):
            assets = self._parse_manifest(text, base_url=url)
            if assets:
                return assets

        relative_name = PurePosixPath(url.split("?", 1)[0]).name or "remote-spec.md"
        return [RemoteSpecAsset(relative_path=relative_name, content=text, source=url)]

    def _parse_manifest(self, text: str, *, base_url: str) -> list[RemoteSpecAsset]:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return []

        if not isinstance(data, dict):
            return []

        files = data.get("files")
        if isinstance(files, dict):
            return [
                RemoteSpecAsset(relative_path=path, content=str(content), source=f"{base_url}#{path}")
                for path, content in sorted(files.items())
                if isinstance(path, str)
            ]

        paths = data.get("paths")
        nested_base = data.get("base_url")
        if isinstance(paths, list) and isinstance(nested_base, str):
            assets: list[RemoteSpecAsset] = []
            for raw_path in paths:
                if not isinstance(raw_path, str):
                    continue
                target_url = f"{nested_base.rstrip('/')}/{raw_path.lstrip('/')}"
                assets.extend(self._read_remote(target_url))
            return assets

        return []

    def _coerce_remote_url(self, reference: str) -> str:
        if reference.startswith(("http://", "https://")):
            return reference
        if reference.startswith("github:"):
            return self._github_to_raw_url(reference)
        if reference.startswith("npm:"):
            return self._npm_to_unpkg_url(reference)
        guessed_type, _ = mimetypes.guess_type(reference)
        if guessed_type:
            return reference
        raise RemoteRegistryError(f"Unsupported registry reference: {reference}")

    def _github_to_raw_url(self, reference: str) -> str:
        body = reference.removeprefix("github:")
        ref = "main"
        if "@" in body:
            body, ref = body.rsplit("@", 1)
        parts = [part for part in body.split("/") if part]
        if len(parts) < 3:
            raise RemoteRegistryError(
                "GitHub references must look like github:user/repo/path[@ref]"
            )
        owner, repo, *path_parts = parts
        path = "/".join(path_parts)
        return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"

    def _npm_to_unpkg_url(self, reference: str) -> str:
        body = reference.removeprefix("npm:")
        version = ""
        if "@" in body[1:]:
            body, version = body.rsplit("@", 1)
            version = f"@{version}"
        if body.startswith("@"):
            package_parts = body.split("/", 2)
            if len(package_parts) < 2:
                raise RemoteRegistryError(
                    "Scoped npm references must look like npm:@scope/package[/path][@version]"
                )
            package = "/".join(package_parts[:2])
            suffix = package_parts[2] if len(package_parts) == 3 else ""
        else:
            package_parts = body.split("/", 1)
            package = package_parts[0]
            suffix = package_parts[1] if len(package_parts) == 2 else ""
        base = f"https://unpkg.com/{package}{version}"
        if suffix:
            return f"{base}/{suffix}"
        return f"{base}/"


def copy_assets_to_directory(
    assets: Iterable[RemoteSpecAsset],
    *,
    output_dir: Path,
) -> list[Path]:
    """Write fetched assets to ``output_dir`` and return touched paths."""

    written: list[Path] = []
    for asset in assets:
        target = output_dir / asset.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(asset.content, encoding="utf-8")
        written.append(target)
    return written
