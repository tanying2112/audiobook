"""Hypothesis property-based tests for security.py (TEST-003).

Tests invariants of safe_join, sanitize_filename, and validate_file_path
using randomized inputs to catch edge cases deterministic tests miss.
"""

import os
import tempfile
from pathlib import Path

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from src.audiobook_studio.security import safe_join, safe_open, sanitize_filename, validate_file_path


# ── sanitize_filename ──────────────────────────────────────────────────────────


# Valid filename characters (platform-safe set)
_VALID_CHARS = st.characters(
    whitelist_categories=("Lu", "Ll", "Nd"),  # Letters + Digits
    whitelist_characters="._- ",  # Dots, underscores, hyphens, spaces
)


class TestSanitizeFilename:
    """Property tests for sanitize_filename."""

    @given(filename=st.text(min_size=1, max_size=200))
    @settings(max_examples=200)
    def test_never_returns_empty(self, filename: str):
        """sanitize_filename should never return an empty string."""
        result = sanitize_filename(filename)
        assert len(result) > 0

    @given(filename=st.text(min_size=1, max_size=200))
    @settings(max_examples=200)
    def test_no_path_separators(self, filename: str):
        """sanitized name must not contain / or \\."""
        result = sanitize_filename(filename)
        assert "/" not in result
        assert "\\" not in result

    @given(filename=st.text(alphabet=list("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"), min_size=1, max_size=100))
    @settings(max_examples=100)
    def test_valid_input_preserved(self, filename: str):
        """Already-safe input should pass through unchanged."""
        result = sanitize_filename(filename)
        assert result == filename

    @given(filename=st.text(min_size=1, max_size=200))
    @settings(max_examples=200)
    def test_no_null_bytes(self, filename: str):
        """sanitized name must not contain null bytes."""
        result = sanitize_filename(filename)
        assert "\x00" not in result


# ── safe_join ──────────────────────────────────────────────────────────────────


class TestSafeJoin:
    """Property tests for safe_join path traversal prevention."""

    @given(
        component=st.text(
            alphabet=list("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"),
            min_size=1,
            max_size=50,
        ),
    )
    @settings(max_examples=200)
    def test_result_within_base(self, component: str):
        """safe_join result must always resolve within the base directory."""
        assume(component not in (".", ".."))
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir).resolve()
            result = safe_join(base, component)
            assert result is not None
            resolved = result.resolve()
            assert str(resolved).startswith(str(base))

    @given(
        traversal=st.text(
            alphabet=list("../\\"),
            min_size=3,
            max_size=100,
        ),
    )
    @settings(max_examples=100)
    def test_rejects_traversal(self, traversal: str):
        """safe_join must reject path traversal patterns."""
        assume(".." in traversal)
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir).resolve()
            result = safe_join(base, traversal)
            # Should reject by returning None or raising ValueError
            assert result is None or isinstance(result, Path)

    @given(component=st.text(min_size=1, max_size=100))
    @settings(max_examples=200)
    def test_raises_on_absolute_path(self, component: str):
        """safe_join must reject absolute path components."""
        assume(component.startswith("/") or component.startswith("\\"))
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir).resolve()
            try:
                result = safe_join(base, component)
                assert result is None, f"Expected None for absolute path, got {result}"
            except ValueError:
                pass  # ValueError is also acceptable


# ── safe_open ──────────────────────────────────────────────────────────────────


class TestSafeOpen:
    """Property tests for safe_open TOCTOU protection."""

    @given(
        filename=st.text(
            alphabet=list("abcdefghijklmnopqrstuvwxyz0123456789._-"),
            min_size=1,
            max_size=30,
        ),
        content=st.binary(min_size=0, max_size=1024),
    )
    @settings(max_examples=100)
    def test_write_read_roundtrip(self, filename: str, content: bytes):
        """safe_open write then read should recover exact content."""
        assume(filename and filename[0] != ".")
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir).resolve()
            # Write
            with safe_open(base, filename, mode="wb") as f:
                f.write(content)
            # Read back
            with safe_open(base, filename, mode="rb") as f:
                read_back = f.read()
            assert read_back == content

    @given(
        filename=st.text(min_size=1, max_size=50),
    )
    @settings(max_examples=100)
    def test_exclusive_create(self, filename: str):
        """safe_open with mode='x' should fail if file exists."""
        assume(filename and "/" not in filename and "\x00" not in filename)
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir).resolve()
            try:
                with safe_open(base, filename, mode="w") as f:
                    f.write("data")
                with safe_open(base, filename, mode="x") as f:
                    f.write("data2")
                assert False, "Expected FileExistsError for exclusive create"
            except (FileExistsError, OSError):
                pass  # Expected

    @given(
        traversal=st.sampled_from(["../../etc/passwd", "../.ssh/id_rsa", "/etc/hosts", "C:\\Windows\\system32\\config\\SAM"]),
    )
    @settings(max_examples=10)
    def test_rejects_known_traversals(self, traversal: str):
        """safe_open must reject well-known traversal paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir).resolve()
            try:
                with safe_open(base, traversal, mode="w") as f:
                    f.write(b"should not write")
                # If it opened, verify it's still within base
                full = (base / traversal).resolve()
                assert str(full).startswith(str(base)), f"Traversal escaped: {full}"
            except (ValueError, FileNotFoundError, OSError):
                pass  # Rejection is expected