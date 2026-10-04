"""Tests for S3.2 — collaborative edit conflict resolution (lite-CRDT).

Verifies deterministic, coordination-free convergence of concurrent edits via
version vectors + last-writer-wins field merge.
"""

from src.audiobook_studio.collaboration.conflict import (
    VersionVector,
    merge_documents,
    resolve_field_conflict,
)


def test_version_vector_increment_and_merge():
    a = VersionVector({"s1": 1})
    b = a.increment("s1")
    assert b.counters["s1"] == 2
    merged = b.merge(VersionVector({"s1": 1, "s2": 1}))
    assert merged.counters == {"s1": 2, "s2": 1}


def test_version_vector_concurrency_detection():
    a = VersionVector({"s1": 1, "s2": 0})
    b = VersionVector({"s1": 0, "s2": 1})
    assert a.concurrent(b) is True
    assert a.dominates(VersionVector({"s1": 1})) is True
    assert a.dominates(a) is False  # equal is not dominant


def test_resolve_field_higher_rev_wins():
    val, rev = resolve_field_conflict("local", 1, "s1", "remote", 2, "s2")
    assert val == "remote" and rev == 2


def test_resolve_field_rev_tie_broken_by_site():
    # Equal revision -> lexicographically larger site wins (deterministic).
    val, _ = resolve_field_conflict("local", 1, "s1", "remote", 1, "s2")
    assert val == "remote"  # s2 > s1


def test_merge_documents_independent_fields():
    local = {"title": "A", "body": "local body"}
    remote = {"title": "A", "body": "remote body"}
    merged = merge_documents(local, remote, local_rev=1, remote_rev=2, local_site="s1", remote_site="s2")
    # body conflict -> remote wins (higher rev); title unchanged
    assert merged["body"] == "remote body"
    assert merged["title"] == "A"


def test_merge_documents_disjoint_fields_union():
    local = {"a": 1}
    remote = {"b": 2}
    merged = merge_documents(local, remote, 1, 1, "s1", "s2")
    assert merged == {"a": 1, "b": 2}


def test_merge_concurrent_same_rev_deterministic():
    # Concurrent edits at equal revision converge identically on all replicas.
    local = {"x": "L"}
    remote = {"x": "R"}
    m1 = merge_documents(local, remote, 1, 1, "s1", "s2")
    m2 = merge_documents(remote, local, 1, 1, "s2", "s1")
    assert m1 == m2  # convergence
    assert m1["x"] == "R"  # s2 > s1 tie-break
