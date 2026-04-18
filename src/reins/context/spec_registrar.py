"""Spec registrar — imports specs from filesystem and emits events.

The registrar is responsible for:
1. Scanning .reins/spec/ directory for spec files
2. Parsing YAML manifests
3. Validating spec structure
4. Trust verification (only system/admin can register)
5. Emitting SpecRegisteredEvent to journal
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from reins.kernel.event.journal import EventJournal
from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.event.spec_events import (
    SPEC_REGISTERED,
    SpecRegisteredEvent,
)
from reins.kernel.types import Actor


class SpecValidationError(Exception):
    """Raised when spec validation fails."""

    pass


class SpecRegistrar:
    """Imports specs from filesystem and registers them in the event journal.

    Specs are stored as YAML files with frontmatter containing metadata
    and content containing the actual spec text.
    """

    def __init__(self, journal: EventJournal, run_id: str) -> None:
        self._journal = journal
        self._run_id = run_id

    async def import_from_directory(
        self,
        spec_dir: Path,
        registered_by: str = "system",
    ) -> list[str]:
        """Import all specs from a directory tree.

        Args:
            spec_dir: Root directory containing spec files (e.g., .reins/spec/)
            registered_by: Who is registering these specs (system/admin/user:id)

        Returns:
            List of spec_ids that were registered

        Raises:
            SpecValidationError: If any spec fails validation
        """
        if not spec_dir.exists():
            raise SpecValidationError(f"Spec directory does not exist: {spec_dir}")

        if not spec_dir.is_dir():
            raise SpecValidationError(f"Not a directory: {spec_dir}")

        # Trust check: only system/admin can register specs
        if not self._verify_trust(registered_by):
            raise SpecValidationError(
                f"Untrusted source: {registered_by}. Only system/admin can register specs."
            )

        spec_ids: list[str] = []

        # Recursively find all .yaml and .yml files
        for spec_file in spec_dir.rglob("*.yaml"):
            spec_id = await self._import_spec_file(spec_file, spec_dir, registered_by)
            if spec_id:
                spec_ids.append(spec_id)

        for spec_file in spec_dir.rglob("*.yml"):
            spec_id = await self._import_spec_file(spec_file, spec_dir, registered_by)
            if spec_id:
                spec_ids.append(spec_id)

        return spec_ids

    async def _import_spec_file(
        self,
        spec_file: Path,
        spec_dir: Path,
        registered_by: str,
    ) -> str | None:
        """Import a single spec file.

        Returns:
            spec_id if successful, None if skipped
        """
        try:
            # Read and parse YAML
            content = spec_file.read_text(encoding="utf-8")
            data = yaml.safe_load(content)

            if not isinstance(data, dict):
                raise SpecValidationError(f"Invalid YAML structure in {spec_file}")

            # Validate required fields
            self._validate_spec_data(data, spec_file)

            # Generate spec_id from file path relative to spec_dir
            relative_path = spec_file.relative_to(spec_dir)
            spec_id = self._generate_spec_id(relative_path)

            # Extract metadata
            spec_type = data.get("spec_type", "standing_law")
            scope = data.get("scope", "workspace")
            applicability = data.get("applicability", {})
            required_capabilities = data.get("required_capabilities", [])
            visibility_tier = data.get("visibility_tier", 1)
            precedence = data.get("precedence", 100)
            spec_content = data.get("content", "")

            # Estimate token count
            token_count = self._estimate_tokens(spec_content)

            # Create event
            event_data = SpecRegisteredEvent(
                spec_id=spec_id,
                spec_type=spec_type,
                scope=scope,
                content=spec_content,
                applicability=applicability,
                required_capabilities=required_capabilities,
                visibility_tier=visibility_tier,
                precedence=precedence,
                source_path=str(spec_file),
                registered_by=registered_by,
                token_count=token_count,
            )

            # Emit to journal
            envelope = EventEnvelope(
                run_id=self._run_id,
                actor=Actor.runtime,
                type=SPEC_REGISTERED,
                payload=self._event_to_payload(event_data),
            )

            await self._journal.append(envelope)

            return spec_id

        except yaml.YAMLError as e:
            raise SpecValidationError(f"YAML parse error in {spec_file}: {e}")
        except Exception as e:
            raise SpecValidationError(f"Failed to import {spec_file}: {e}")

    def _validate_spec_data(self, data: dict[str, Any], spec_file: Path) -> None:
        """Validate spec data structure.

        Required fields:
        - content: str (the actual spec text)

        Optional fields with defaults:
        - spec_type: str (default: 'standing_law')
        - scope: str (default: 'workspace')
        - applicability: dict (default: {})
        - required_capabilities: list (default: [])
        - visibility_tier: int (default: 1)
        - precedence: int (default: 100)
        """
        if "content" not in data:
            raise SpecValidationError(
                f"Missing required field 'content' in {spec_file}"
            )

        if not isinstance(data["content"], str):
            raise SpecValidationError(
                f"Field 'content' must be a string in {spec_file}"
            )

        # Validate spec_type if present
        if "spec_type" in data:
            valid_types = ["standing_law", "task_contract", "spec_shard"]
            if data["spec_type"] not in valid_types:
                raise SpecValidationError(
                    f"Invalid spec_type '{data['spec_type']}' in {spec_file}. "
                    f"Must be one of: {valid_types}"
                )

        # Validate visibility_tier if present
        if "visibility_tier" in data:
            tier = data["visibility_tier"]
            if not isinstance(tier, int) or tier < 0 or tier > 3:
                raise SpecValidationError(
                    f"Invalid visibility_tier {tier} in {spec_file}. Must be 0-3."
                )

        # Validate precedence if present
        if "precedence" in data:
            if not isinstance(data["precedence"], int):
                raise SpecValidationError(
                    f"Field 'precedence' must be an integer in {spec_file}"
                )

        # Validate required_capabilities if present
        if "required_capabilities" in data:
            if not isinstance(data["required_capabilities"], list):
                raise SpecValidationError(
                    f"Field 'required_capabilities' must be a list in {spec_file}"
                )

        # Validate applicability if present
        if "applicability" in data:
            if not isinstance(data["applicability"], dict):
                raise SpecValidationError(
                    f"Field 'applicability' must be a dict in {spec_file}"
                )

    def _generate_spec_id(self, relative_path: Path) -> str:
        """Generate spec_id from file path.

        Examples:
            backend/error-handling.yaml -> backend.error-handling
            frontend/components/button.yaml -> frontend.components.button
        """
        # Remove extension
        path_without_ext = relative_path.with_suffix("")

        # Convert path separators to dots
        spec_id = str(path_without_ext).replace("/", ".").replace("\\", ".")

        # Normalize: lowercase, replace spaces/underscores with hyphens
        spec_id = spec_id.lower()
        spec_id = re.sub(r"[_\s]+", "-", spec_id)

        return spec_id

    def _verify_trust(self, registered_by: str) -> bool:
        """Verify that the source is trusted to register specs.

        Only 'system' and 'admin' are trusted sources.
        User-registered specs go to a staging area (future feature).
        """
        return registered_by in ("system", "admin")

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count using 4-chars-per-token heuristic."""
        return max(1, len(text) // 4)

    def _event_to_payload(self, event: SpecRegisteredEvent) -> dict[str, Any]:
        """Convert SpecRegisteredEvent to payload dict."""
        return {
            "spec_id": event.spec_id,
            "spec_type": event.spec_type,
            "scope": event.scope,
            "content": event.content,
            "applicability": event.applicability,
            "required_capabilities": event.required_capabilities,
            "visibility_tier": event.visibility_tier,
            "precedence": event.precedence,
            "source_path": event.source_path,
            "registered_by": event.registered_by,
            "token_count": event.token_count,
        }
