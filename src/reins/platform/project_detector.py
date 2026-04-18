"""Project type detection for `reins init`."""

from __future__ import annotations

import json
import tomllib
from enum import Enum
from pathlib import Path
from typing import Iterable


class ProjectType(str, Enum):
    """Supported project types for initialization."""

    FRONTEND = "frontend"
    BACKEND = "backend"
    FULLSTACK = "fullstack"


class ProjectDetector:
    """Detect project type from repository files and layout."""

    PACKAGE_ROOTS = ("packages", "apps", "services", "libs", "modules")

    FRONTEND_DEPENDENCIES = {
        "react",
        "next",
        "vite",
        "vue",
        "svelte",
        "@angular/core",
    }
    BACKEND_PYTHON_DEPENDENCIES = {
        "fastapi",
        "flask",
        "django",
        "aiohttp",
        "typer",
        "uvicorn",
    }

    def detect(self, repo_root: Path) -> ProjectType:
        """Detect the project type for a repository."""
        has_frontend = self._has_frontend_markers(repo_root)
        has_backend = self._has_backend_markers(repo_root)

        if has_frontend and has_backend:
            return ProjectType.FULLSTACK
        if has_frontend:
            return ProjectType.FRONTEND
        del has_backend
        return ProjectType.BACKEND

    def resolve(self, repo_root: Path, project_type: str | None) -> ProjectType:
        """Resolve a manual override or fall back to auto-detection."""
        if project_type is None:
            return self.detect(repo_root)
        return ProjectType(project_type)

    def detect_packages(self, repo_root: Path) -> list[str]:
        """Detect package names from common monorepo layouts."""
        packages: set[str] = set()

        package_json = repo_root / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
            workspaces = data.get("workspaces", [])
            if isinstance(workspaces, list):
                packages.update(self._expand_workspace_globs(repo_root, workspaces))
            elif isinstance(workspaces, dict):
                workspace_packages = workspaces.get("packages", [])
                if isinstance(workspace_packages, list):
                    packages.update(self._expand_workspace_globs(repo_root, workspace_packages))

        for root_name in self.PACKAGE_ROOTS:
            root = repo_root / root_name
            if not root.exists():
                continue
            for child in root.iterdir():
                if child.is_dir() and not child.name.startswith("."):
                    packages.add(child.name)

        return sorted(packages)

    def infer_package(self, repo_root: Path, file_paths: Iterable[str | Path]) -> str | None:
        """Infer the most likely package for a set of file paths."""
        detected = self.detect_packages(repo_root)
        if not detected:
            return None

        package_dirs = self._package_directories(repo_root, detected)
        counts: dict[str, int] = {package: 0 for package in detected}

        for file_path in file_paths:
            path = Path(file_path)
            candidate = (repo_root / path).resolve() if not path.is_absolute() else path.resolve()
            for package, directories in package_dirs.items():
                if any(candidate.is_relative_to(directory) for directory in directories):
                    counts[package] += 1

        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if not ranked or ranked[0][1] == 0:
            return None
        return ranked[0][0]

    def resolve_package(
        self,
        repo_root: Path,
        package: str | None = None,
        *,
        file_paths: Iterable[str | Path] = (),
    ) -> str | None:
        """Resolve an explicit or inferred package name."""
        if package:
            return package
        inferred = self.infer_package(repo_root, file_paths)
        if inferred:
            return inferred
        detected = self.detect_packages(repo_root)
        return detected[0] if len(detected) == 1 else None

    def _has_frontend_markers(self, repo_root: Path) -> bool:
        package_json = repo_root / "package.json"
        if package_json.exists():
            data = json.loads(package_json.read_text(encoding="utf-8"))
            dependencies = set((data.get("dependencies") or {}).keys())
            dev_dependencies = set((data.get("devDependencies") or {}).keys())
            if self.FRONTEND_DEPENDENCIES & (dependencies | dev_dependencies):
                return True

        marker_paths = (
            repo_root / "src" / "components",
            repo_root / "app",
            repo_root / "pages",
            repo_root / "frontend",
        )
        return any(path.exists() for path in marker_paths)

    def _has_backend_markers(self, repo_root: Path) -> bool:
        if any(
            (repo_root / marker).exists()
            for marker in (
                "requirements.txt",
                "setup.py",
                "manage.py",
                "backend",
                "api",
            )
        ):
            return True

        pyproject_path = repo_root / "pyproject.toml"
        if pyproject_path.exists():
            data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
            project = data.get("project", {})
            dependencies = set(project.get("dependencies", []))
            lowered = {dependency.lower() for dependency in dependencies}
            if any(
                name in dependency
                for dependency in lowered
                for name in self.BACKEND_PYTHON_DEPENDENCIES
            ):
                return True
            return True

        return any(path.suffix == ".py" for path in repo_root.rglob("*.py"))

    def _expand_workspace_globs(self, repo_root: Path, patterns: list[str]) -> set[str]:
        packages: set[str] = set()
        for pattern in patterns:
            for match in repo_root.glob(pattern):
                if match.is_dir() and not match.name.startswith("."):
                    packages.add(match.name)
        return packages

    def _package_directories(
        self,
        repo_root: Path,
        packages: list[str],
    ) -> dict[str, list[Path]]:
        package_dirs: dict[str, list[Path]] = {package: [] for package in packages}
        for root_name in self.PACKAGE_ROOTS:
            root = repo_root / root_name
            if not root.exists():
                continue
            for package in packages:
                candidate = (root / package).resolve()
                if candidate.exists():
                    package_dirs[package].append(candidate)
        for package in packages:
            direct = (repo_root / package).resolve()
            if direct.exists():
                package_dirs[package].append(direct)
        return package_dirs
