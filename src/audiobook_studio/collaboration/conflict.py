"""Collaborative edit conflict resolution — S3.2 (lite-CRDT).

Dependency-free, deterministic conflict resolution for concurrent edits to the
same document by multiple sites. This is a pragmatic stand-in for a full
CRDT / operational-transform library:

- :class:`VersionVector` tracks per-site counters and can detect *concurrency*
  (neither vector dominates the other).
- :func:`resolve_field_conflict` applies deterministic last-writer-wins: the
  higher revision wins; ties are broken by lexicographically-larger site id so
  all replicas converge to the same value without coordination.
- :func:`merge_documents` merges two document revisions field-by-field.

When sites exchange version vectors, this guarantees convergence for the common
cases (independent fields merge cleanly; conflicting fields resolve LWW). A full
CRDT/OT implementation (e.g. Automerge/Yjs) is recommended for production
rich-text collaboration and is noted as future work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class VersionVector:
    """Per-site monotonic counters (site_id -> counter)."""

    counters: Dict[str, int] = field(default_factory=dict)

    def increment(self, site: str) -> "VersionVector":
        new = dict(self.counters)
        new[site] = new.get(site, 0) + 1
        return VersionVector(new)

    def merge(self, other: "VersionVector") -> "VersionVector":
        merged = dict(self.counters)
        for k, v in other.counters.items():
            merged[k] = max(merged.get(k, 0), v)
        return VersionVector(merged)

    def dominates(self, other: "VersionVector") -> bool:
        """True if every counter here >= other's (i.e. happened-after)."""
        for k, v in other.counters.items():
            if self.counters.get(k, 0) < v:
                return False
        # Ensure we are not equal (dominates implies strictly >= and at least one >)
        if self.counters == other.counters:
            return False
        return True

    def concurrent(self, other: "VersionVector") -> bool:
        return not self.dominates(other) and not other.dominates(self)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, VersionVector):
            return NotImplemented
        return self.counters == other.counters


def resolve_field_conflict(
    local_val: Any,
    local_rev: int,
    local_site: str,
    remote_val: Any,
    remote_rev: int,
    remote_site: str,
) -> Tuple[Any, int]:
    """Deterministic last-writer-wins for a single field.

    Higher revision wins; on a tie the lexicographically larger site id wins,
    guaranteeing all replicas converge to the same value.
    """
    if remote_rev > local_rev:
        return remote_val, remote_rev
    if remote_rev < local_rev:
        return local_val, local_rev
    # Tie: deterministic by site id.
    if remote_site > local_site:
        return remote_val, remote_rev
    return local_val, local_rev


def merge_documents(
    local: Dict[str, Any],
    remote: Dict[str, Any],
    local_rev: int,
    remote_rev: int,
    local_site: str,
    remote_site: str,
) -> Dict[str, Any]:
    """Merge two document revisions field-by-field (S3.2 conflict resolution)."""
    merged: Dict[str, Any] = {}
    for key in set(local) | set(remote):
        lv = local.get(key, None)
        rv = remote.get(key, None)
        if key in local and key not in remote:
            merged[key] = lv
        elif key in remote and key not in local:
            merged[key] = rv
        else:
            value, _ = resolve_field_conflict(
                lv, local_rev, local_site, rv, remote_rev, remote_site
            )
            merged[key] = value
    return merged
