"""SKILL.md discovery and parsing.

Scans directories for SKILL.md files and extracts metadata.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from reins.skill.catalog import SkillDescriptor


@dataclass
class SkillManifest:
    """Parsed SKILL.md manifest."""

    skill_id: str
    name: str
    description: str
    version: str
    source_path: Path
    content: str
    metadata: dict[str, str | list[str]]


class SkillDiscovery:
    """Discovers and parses SKILL.md files from directories."""

    def __init__(self, search_paths: list[Path]) -> None:
        self.search_paths = search_paths

    def discover(self) -> list[Path]:
        """Discover all SKILL.md files in search paths."""
        skill_files: list[Path] = []

        for search_path in self.search_paths:
            if not search_path.exists():
                continue

            # Find all SKILL.md files recursively
            for skill_file in search_path.rglob("SKILL.md"):
                skill_files.append(skill_file)

        return skill_files

    def parse(self, skill_file: Path) -> SkillManifest | None:
        """Parse a SKILL.md file and extract metadata.

        Expected format:
        ```markdown
        # Skill Name

        Description of the skill.

        ## Metadata

        - **skill_id**: unique-skill-id
        - **version**: 1.0.0
        - **tags**: tag1, tag2, tag3
        - **required_tools**: tool1, tool2
        - **trust_tier**: 2
        - **capabilities**: cap1, cap2

        ## Usage

        ...
        ```
        """
        if not skill_file.exists():
            return None

        content = skill_file.read_text(encoding="utf-8")

        # Extract title (first # heading)
        title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if not title_match:
            return None
        name = title_match.group(1).strip()

        # Extract description (text between title and ## Metadata)
        desc_match = re.search(
            r"^#\s+.+?\n\n(.+?)(?=\n##|\Z)", content, re.MULTILINE | re.DOTALL
        )
        description = desc_match.group(1).strip() if desc_match else ""

        # Extract metadata section
        metadata = self._parse_metadata_section(content)

        # Generate skill_id from metadata or derive from path
        skill_id_raw = metadata.get("skill_id", "")
        if isinstance(skill_id_raw, list):
            skill_id = skill_id_raw[0] if skill_id_raw else ""
        else:
            skill_id = skill_id_raw
        if not skill_id:
            # Derive from directory name
            skill_id = skill_file.parent.name

        # Get version
        version = metadata.get("version", "1.0.0")
        if isinstance(version, list):
            version = version[0] if version else "1.0.0"

        return SkillManifest(
            skill_id=str(skill_id),
            name=name,
            description=description,
            version=version,
            source_path=skill_file,
            content=content,
            metadata=metadata,
        )

    def _parse_metadata_section(self, content: str) -> dict[str, str | list[str]]:
        """Parse the ## Metadata section from SKILL.md."""
        metadata: dict[str, str | list[str]] = {}

        # Find metadata section
        metadata_match = re.search(
            r"##\s+Metadata\s*\n(.+?)(?=\n##|\Z)", content, re.MULTILINE | re.DOTALL
        )

        if not metadata_match:
            return metadata

        metadata_text = metadata_match.group(1)

        # Parse bullet points: - **key**: value
        for line in metadata_text.split("\n"):
            line = line.strip()
            if not line.startswith("-"):
                continue

            # Match: - **key**: value
            match = re.match(r"-\s+\*\*(.+?)\*\*:\s*(.+)", line)
            if not match:
                continue

            key = match.group(1).strip()
            value = match.group(2).strip()

            # Check if value is a comma-separated list
            if "," in value:
                metadata[key] = [v.strip() for v in value.split(",")]
            else:
                metadata[key] = value

        return metadata

    def to_descriptor(self, manifest: SkillManifest) -> SkillDescriptor:
        """Convert a SkillManifest to a SkillDescriptor."""
        # Calculate manifest hash
        manifest_hash = hashlib.sha256(manifest.content.encode()).hexdigest()[:16]

        # Extract metadata fields
        tags = manifest.metadata.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]

        required_tools = manifest.metadata.get("required_tools", [])
        if isinstance(required_tools, str):
            required_tools = [required_tools]

        required_protocols = manifest.metadata.get("required_protocols", [])
        if isinstance(required_protocols, str):
            required_protocols = [required_protocols]

        outputs = manifest.metadata.get("outputs", [])
        if isinstance(outputs, str):
            outputs = [outputs]

        capabilities = manifest.metadata.get("capabilities", [])
        if isinstance(capabilities, str):
            capabilities = [capabilities]

        dependencies = manifest.metadata.get("dependencies", [])
        if isinstance(dependencies, str):
            dependencies = [dependencies]

        # Parse trust_tier
        trust_tier_str = manifest.metadata.get("trust_tier", "0")
        if isinstance(trust_tier_str, list):
            trust_tier_str = trust_tier_str[0] if trust_tier_str else "0"
        trust_tier = int(trust_tier_str)

        # Get approval profile
        approval_profile = manifest.metadata.get("approval_profile", "default")
        if isinstance(approval_profile, list):
            approval_profile = approval_profile[0] if approval_profile else "default"

        return SkillDescriptor(
            skill_id=manifest.skill_id,
            source=str(manifest.source_path),
            version=manifest.version,
            manifest_hash=manifest_hash,
            name=manifest.name,
            description=manifest.description,
            tags=tags,
            required_tools=required_tools,
            required_protocols=required_protocols,
            outputs=outputs,
            trust_tier=trust_tier,
            approval_profile=approval_profile,
            allowed_capabilities=capabilities,
            evaluator_hooks=[],
            compatible_surfaces=[],
            dependencies=dependencies,
        )

    def scan_and_parse(self) -> list[SkillDescriptor]:
        """Discover and parse all SKILL.md files, returning descriptors."""
        skill_files = self.discover()
        descriptors: list[SkillDescriptor] = []

        for skill_file in skill_files:
            manifest = self.parse(skill_file)
            if manifest:
                descriptor = self.to_descriptor(manifest)
                descriptors.append(descriptor)

        return descriptors
