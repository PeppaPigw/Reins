from __future__ import annotations

import hashlib

from reins.kernel.reducer.state import StateSnapshot
from reins.serde import canonical_json, to_primitive

INTEGRITY_HASH_FIELD = "_integrity_hash"


def compute_snapshot_hash(snapshot: StateSnapshot) -> str:
    """Compute a SHA-256 hash of the snapshot's state content."""
    content = to_primitive(snapshot)
    content.pop(INTEGRITY_HASH_FIELD, None)
    content.pop("reins_version", None)
    return hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()


def validate_snapshot_integrity(data: dict, expected_hash: str | None) -> bool:
    """Validate snapshot data against an expected integrity hash."""
    if expected_hash is None:
        return False
    content = dict(data)
    content.pop(INTEGRITY_HASH_FIELD, None)
    content.pop("reins_version", None)
    computed = hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()
    return computed == expected_hash
