# Migration Patterns for Template Evolution

## Overview

Reins uses a declarative JSON-based migration system to safely evolve templates, rename files, and manage breaking changes across versions. Migrations are idempotent, schema-validated, and support automatic rollback on failure.

## Core Components

### 1. Migration Engine (`src/reins/migration/engine.py`)

Orchestrates migration execution with version filtering and rollback support.

**Key Methods:**

```python
async def migrate(
    self,
    *,
    from_version: str,
    to_version: str,
    dry_run: bool = False,
) -> list[MigrationOperationResult]

def load_manifests(self) -> list[MigrationManifest]

def manifests_between(
    self,
    *,
    from_version: str,
    to_version: str,
) -> list[MigrationManifest]
```

### 2. Migration Types (`src/reins/migration/types.py`)

Four migration operation types supported:

```python
@dataclass(frozen=True)
class Migration:
    type: str                       # "rename", "delete", "safe-file-delete", "rename-dir"
    from_path: str                  # Source path (relative to repo root)
    to_path: str | None            # Destination path (for rename operations)
    allowed_hashes: list[str]      # SHA-256 hashes (for safe-file-delete)
    description: str                # Human-readable description
```

**Migration Types:**

1. **rename** - Move file from old path to new path
2. **delete** - Remove file unconditionally
3. **safe-file-delete** - Remove only if file hash matches allowed list
4. **rename-dir** - Move entire directory recursively

### 3. Version Comparison (`src/reins/migration/version.py`)

Semantic version parsing and filtering.

```python
@dataclass(frozen=True, order=True)
class SemanticVersion:
    major: int
    minor: int
    patch: int
    
    @classmethod
    def parse(cls, version_str: str) -> SemanticVersion

def versions_in_range(
    versions: list[str],
    from_version: str,
    to_version: str,
) -> list[str]
```

### 4. Migration Manifests

JSON files in `migrations/manifests/` directory.

**Schema:** `migrations/manifests/schema.json`

**Example Manifest:** `migrations/manifests/0.1.0.json`

```json
{
  "version": "0.1.0",
  "migrations": [
    {
      "type": "rename",
      "from": ".trellis/old-file.md",
      "to": ".reins/new-file.md",
      "description": "Move file to new location"
    },
    {
      "type": "safe-file-delete",
      "from": ".trellis/deprecated.md",
      "allowed_hashes": [
        "abc123def456..."
      ],
      "description": "Remove deprecated file if unmodified"
    }
  ]
}
```

## Usage Patterns

### Pattern 1: Run Migrations

```python
from pathlib import Path
from reins.migration import MigrationEngine
from reins.kernel.event.journal import EventJournal

# Initialize engine
journal = EventJournal(Path(".reins/journal.jsonl"))
engine = MigrationEngine(
    repo_root=Path.cwd(),
    journal=journal,
    run_id="migration-run-123",
)

# Run migrations from 0.0.0 to 0.1.0
results = await engine.migrate(
    from_version="0.0.0",
    to_version="0.1.0",
    dry_run=False,
)

# Check results
for result in results:
    print(f"{result.migration_type}: {result.description}")
    print(f"  Status: {result.status}")
    if result.reason:
        print(f"  Reason: {result.reason}")
```

### Pattern 2: Dry Run Before Applying

```python
# Test migrations without making changes
results = await engine.migrate(
    from_version="0.0.0",
    to_version="0.1.0",
    dry_run=True,
)

# Review what would happen
for result in results:
    if result.status == "applied":
        print(f"Would apply: {result.description}")
    elif result.status == "skipped":
        print(f"Would skip: {result.description} ({result.reason})")

# If satisfied, run for real
if all(r.status in ("applied", "skipped") for r in results):
    await engine.migrate(
        from_version="0.0.0",
        to_version="0.1.0",
        dry_run=False,
    )
```

### Pattern 3: Load and Inspect Manifests

```python
# Load all manifests
manifests = engine.load_manifests()
for manifest in manifests:
    print(f"Version {manifest.version}: {len(manifest.migrations)} migrations")

# Get manifests in version range
applicable = engine.manifests_between(
    from_version="0.0.0",
    to_version="0.2.0",
)
```

### Pattern 4: Create New Migration Manifest

```python
import json
from pathlib import Path

# Define migrations
manifest = {
    "version": "0.2.0",
    "migrations": [
        {
            "type": "rename",
            "from": ".reins/old-config.yaml",
            "to": ".reins/config.yaml",
            "description": "Rename config file"
        },
        {
            "type": "delete",
            "from": ".reins/temp-file.txt",
            "description": "Remove temporary file"
        }
    ]
}

# Validate against schema
schema_path = Path("migrations/manifests/schema.json")
schema = json.loads(schema_path.read_text())
import jsonschema
jsonschema.validate(manifest, schema)

# Write manifest
manifest_path = Path("migrations/manifests/0.2.0.json")
manifest_path.write_text(json.dumps(manifest, indent=2))
```

### Pattern 5: Safe File Deletion with Hash Check

```python
import hashlib
from pathlib import Path

# Calculate file hash
def calculate_hash(file_path: Path) -> str:
    content = file_path.read_bytes()
    return hashlib.sha256(content).hexdigest()

# Get hash of template file
template_path = Path(".reins/template.md")
template_hash = calculate_hash(template_path)

# Create safe-file-delete migration
manifest = {
    "version": "0.3.0",
    "migrations": [
        {
            "type": "safe-file-delete",
            "from": ".reins/template.md",
            "allowed_hashes": [template_hash],
            "description": "Remove template if unmodified by user"
        }
    ]
}

# This will only delete if file hash matches
# User modifications are protected
```

## Migration Types in Detail

### 1. Rename Migration

Moves a file from one path to another.

**Idempotency:** Skips if destination already exists and source is missing.

```json
{
  "type": "rename",
  "from": ".trellis/old-name.md",
  "to": ".reins/new-name.md",
  "description": "Rename file to new location"
}
```

**Behavior:**
- Creates destination directory if needed
- Moves file atomically
- Skips if already applied (destination exists, source missing)
- Fails if destination exists and source also exists

### 2. Delete Migration

Removes a file unconditionally.

**Idempotency:** Skips if file doesn't exist.

```json
{
  "type": "delete",
  "from": ".reins/deprecated.md",
  "description": "Remove deprecated file"
}
```

**Behavior:**
- Deletes file if it exists
- Skips silently if file already missing
- Does not check file content

**⚠️ Warning:** Use with caution. User modifications will be lost.

### 3. Safe File Delete Migration

Removes a file only if its hash matches the allowed list.

**Idempotency:** Skips if file doesn't exist or hash doesn't match.

```json
{
  "type": "safe-file-delete",
  "from": ".reins/template.md",
  "allowed_hashes": [
    "abc123def456...",
    "789ghi012jkl..."
  ],
  "description": "Remove template if unmodified"
}
```

**Behavior:**
- Calculates SHA-256 hash of file
- Deletes only if hash is in allowed list
- Skips if file missing
- Skips if hash doesn't match (protects user modifications)

**Use Case:** Safe removal of template files that users may have customized.

### 4. Rename Directory Migration

Moves an entire directory recursively.

**Idempotency:** Skips if destination exists and source is missing.

```json
{
  "type": "rename-dir",
  "from": ".trellis/old-dir",
  "to": ".reins/new-dir",
  "description": "Move directory to new location"
}
```

**Behavior:**
- Moves entire directory tree
- Creates parent directories if needed
- Skips if already applied
- Fails if destination exists and source also exists

## Event Sourcing

All migration operations emit events to the journal:

**Migration Events:**
- `migration.batch_started` - Migration batch begins
- `migration.operation_applied` - Single operation applied
- `migration.operation_skipped` - Operation skipped (idempotent)
- `migration.operation_failed` - Operation failed
- `migration.batch_completed` - Batch completed successfully
- `migration.batch_failed` - Batch failed, rollback initiated
- `migration.rollback_completed` - Rollback completed

**Event Example:**

```json
{
  "run_id": "migration-run-123",
  "actor": "runtime",
  "type": "migration.operation_applied",
  "payload": {
    "version": "0.1.0",
    "migration_type": "rename",
    "from_path": ".trellis/old-file.md",
    "to_path": ".reins/new-file.md",
    "description": "Move file to new location"
  }
}
```

## Rollback Behavior

If any migration operation fails, the engine automatically rolls back all applied operations in reverse order.

**Rollback Actions:**
- **rename** → Move file back to original location
- **delete** → Restore file from in-memory backup
- **safe-file-delete** → Restore file from in-memory backup
- **rename-dir** → Move directory back to original location

**Example:**

```python
# Batch of 3 migrations
# 1. rename A → B (succeeds)
# 2. delete C (succeeds)
# 3. rename D → E (fails - destination exists)

# Automatic rollback:
# - Restore C from backup
# - Move B back to A
# - Surface original error
```

**⚠️ Note:** Rollback uses in-memory backups. This works well for small template files but may not be suitable for large files.

## Version Filtering

Migrations are filtered by semantic version range.

**Rules:**
- `from_version` is **exclusive** (not included)
- `to_version` is **inclusive** (included)
- Versions are sorted by major.minor.patch

**Example:**

```python
# Manifests: 0.1.0, 0.2.0, 0.3.0, 0.4.0

# Migrate from 0.1.0 to 0.3.0
# Applies: 0.2.0, 0.3.0
# Skips: 0.1.0 (exclusive), 0.4.0 (beyond range)
results = await engine.migrate(
    from_version="0.1.0",
    to_version="0.3.0",
)
```

## Schema Validation

All manifests are validated against JSON schema before execution.

**Schema Location:** `migrations/manifests/schema.json`

**Required Fields:**
- `version` (string, semver format)
- `migrations` (array of migration objects)

**Migration Object:**
- `type` (enum: rename, delete, safe-file-delete, rename-dir)
- `from` (string, relative path)
- `to` (string, relative path, required for rename/rename-dir)
- `allowed_hashes` (array of strings, required for safe-file-delete)
- `description` (string)

**Validation Errors:**

```python
# Invalid manifest will raise jsonschema.ValidationError
try:
    manifest = engine.load_manifest(Path("migrations/manifests/bad.json"))
except jsonschema.ValidationError as e:
    print(f"Invalid manifest: {e.message}")
```

## Best Practices

### 1. Always Use Dry Run First

```python
# Test before applying
results = await engine.migrate(
    from_version="0.0.0",
    to_version="0.1.0",
    dry_run=True,
)

# Review results, then apply
if looks_good(results):
    await engine.migrate(
        from_version="0.0.0",
        to_version="0.1.0",
        dry_run=False,
    )
```

### 2. Prefer safe-file-delete Over delete

```python
# BAD: Unconditional delete (loses user modifications)
{
  "type": "delete",
  "from": ".reins/config.yaml"
}

# GOOD: Safe delete (protects user modifications)
{
  "type": "safe-file-delete",
  "from": ".reins/config.yaml",
  "allowed_hashes": ["abc123..."]
}
```

### 3. Use Descriptive Migration Descriptions

```python
# BAD: Vague description
{
  "description": "Update file"
}

# GOOD: Clear description
{
  "description": "Move config from .trellis/ to .reins/ for new directory structure"
}
```

### 4. Version Manifests Sequentially

```python
# GOOD: Sequential versions
0.1.0.json
0.2.0.json
0.3.0.json

# BAD: Gaps or non-sequential
0.1.0.json
0.5.0.json  # Gap
0.3.0.json  # Out of order
```

### 5. Test Idempotency

```python
# Run migration twice - should be safe
await engine.migrate(from_version="0.0.0", to_version="0.1.0")
await engine.migrate(from_version="0.0.0", to_version="0.1.0")

# All operations should be skipped on second run
```

### 6. Document Breaking Changes

```python
{
  "version": "1.0.0",
  "migrations": [
    {
      "type": "rename",
      "from": ".reins/old-api.py",
      "to": ".reins/new-api.py",
      "description": "BREAKING: Rename API module - update imports in user code"
    }
  ]
}
```

## Anti-Patterns

### ❌ Don't Modify Manifests After Release

```python
# BAD: Edit 0.1.0.json after it's been released
# (breaks idempotency for users who already applied it)

# GOOD: Create new manifest 0.2.0.json with additional migrations
```

### ❌ Don't Use delete for User-Modifiable Files

```python
# BAD: Unconditional delete of config file
{
  "type": "delete",
  "from": ".reins/user-config.yaml"
}

# GOOD: Safe delete with hash check
{
  "type": "safe-file-delete",
  "from": ".reins/user-config.yaml",
  "allowed_hashes": ["template-hash"]
}
```

### ❌ Don't Skip Schema Validation

```python
# BAD: Write manifest without validation
manifest_path.write_text(json.dumps(manifest))

# GOOD: Validate before writing
schema = json.loads(schema_path.read_text())
jsonschema.validate(manifest, schema)
manifest_path.write_text(json.dumps(manifest, indent=2))
```

### ❌ Don't Rely on Rollback for Large Files

```python
# BAD: Delete large files (rollback uses in-memory backup)
{
  "type": "delete",
  "from": "large-dataset.bin"  # 100MB file
}

# GOOD: Only migrate small template files
{
  "type": "delete",
  "from": ".reins/template.md"  # Small file
}
```

## Testing

See test files for examples:
- `tests/unit/test_migration_version.py` - Version comparison
- `tests/unit/test_migration_engine.py` - Engine operations
- `tests/integration/test_migration_flow.py` - End-to-end flow

## Common Scenarios

### Scenario 1: Rename Directory Structure

```json
{
  "version": "1.0.0",
  "migrations": [
    {
      "type": "rename-dir",
      "from": ".trellis",
      "to": ".reins",
      "description": "Migrate from Trellis to Reins directory structure"
    }
  ]
}
```

### Scenario 2: Remove Deprecated Templates

```json
{
  "version": "1.1.0",
  "migrations": [
    {
      "type": "safe-file-delete",
      "from": ".reins/templates/old-template.md",
      "allowed_hashes": [
        "original-template-hash"
      ],
      "description": "Remove old template if unmodified"
    }
  ]
}
```

### Scenario 3: Reorganize Spec Files

```json
{
  "version": "1.2.0",
  "migrations": [
    {
      "type": "rename",
      "from": ".reins/spec/backend/old-patterns.md",
      "to": ".reins/spec/backend/patterns/core.md",
      "description": "Reorganize backend patterns into subdirectory"
    },
    {
      "type": "rename",
      "from": ".reins/spec/backend/advanced-patterns.md",
      "to": ".reins/spec/backend/patterns/advanced.md",
      "description": "Move advanced patterns to subdirectory"
    }
  ]
}
```

### Scenario 4: Clean Up After Feature Removal

```json
{
  "version": "2.0.0",
  "migrations": [
    {
      "type": "delete",
      "from": ".reins/deprecated-feature.py",
      "description": "Remove deprecated feature (breaking change)"
    },
    {
      "type": "safe-file-delete",
      "from": ".reins/config/feature-config.yaml",
      "allowed_hashes": ["default-config-hash"],
      "description": "Remove feature config if using defaults"
    }
  ]
}
```

## References

- [Trellis Migration System](../../memo/Fromtrellis.md#part-5-template-system--updates)
- [Phase 3 Documentation](../../docs/PHASE3-COMPLETE.md)
- [Migration Engine Source](../../src/reins/migration/engine.py)
- [Migration Types Source](../../src/reins/migration/types.py)
- [Schema Definition](../../migrations/manifests/schema.json)
