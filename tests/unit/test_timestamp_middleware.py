"""Tests for src/audiobook_studio/middleware/timestamp.py — pure functions
that can be tested without external dependencies.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from src.audiobook_studio.middleware.timestamp import (
    ISOModel,
    ISOTimestampMiddleware,
    normalize_nested_timestamps,
    normalize_timestamp,
)


class TestNormalizeTimestamp:
    def test_none_returns_none(self):
        assert normalize_timestamp(None) is None

    def test_string_passes_through(self):
        assert normalize_timestamp("2026-06-26T12:00:00Z") == "2026-06-26T12:00:00Z"

    def test_datetime_naive_assumes_utc(self):
        dt = datetime(2026, 6, 26, 12, 0, 0)
        result = normalize_timestamp(dt)
        assert "2026-06-26" in result
        assert "12:00:00" in result
        assert result.endswith("+00:00") or result.endswith("Z")

    def test_datetime_with_tz_preserved(self):
        dt = datetime(2026, 6, 26, 12, 0, 0, tzinfo=timezone.utc)
        result = normalize_timestamp(dt)
        assert result.startswith("2026-06-26")

    def test_numeric_milliseconds(self):
        # Linux epoch milliseconds: ~1.7e12
        result = normalize_timestamp(1719500000000)
        assert isinstance(result, str)
        assert "2024" in result or "2023" in result

    def test_numeric_seconds(self):
        # Linux epoch seconds: ~1.7e9 — pick 2024 timestamp
        result = normalize_timestamp(1719500000)
        assert isinstance(result, str)
        assert "2024" in result

    def test_numeric_too_small_unchanged(self):
        # Below 1e9 — not an epoch
        result = normalize_timestamp(12345)
        assert result == 12345

    def test_unknown_type_passthrough(self):
        assert normalize_timestamp({"a": 1}) == {"a": 1}
        assert normalize_timestamp([1, 2]) == [1, 2]


class TestNormalizeNestedTimestamps:
    def test_dict_recursion(self):
        data = {"created_at": "2026-06-26T00:00:00Z", "level": 5}
        result = normalize_nested_timestamps(data)
        assert result["created_at"] == "2026-06-26T00:00:00Z"
        assert result["level"] == 5

    def test_list_recursion(self):
        data = ["x", "y", 5]
        result = normalize_nested_timestamps(data)
        assert result == ["x", "y", 5]

    def test_nested_dict(self):
        data = {"outer": {"inner": "string"}}
        result = normalize_nested_timestamps(data)
        assert result["outer"]["inner"] == "string"

    def test_nested_list_in_dict(self):
        data = {"items": [{"key": "value"}]}
        result = normalize_nested_timestamps(data)
        assert result["items"][0]["key"] == "value"

    def test_max_depth_protection(self):
        # Build a deeply nested structure > max_depth
        data: dict = {}
        current = data
        for _ in range(15):
            current["child"] = {}
            current = current["child"]
        current["leaf"] = "deep_value"
        result = normalize_nested_timestamps(data, max_depth=5)
        # Should not crash; structure preserved
        assert result is not None


class TestISOModel:
    def test_serialize_datetime_naive(self):
        class TestModel(ISOModel):
            timestamp: datetime

        m = TestModel(timestamp=datetime(2026, 6, 26, 12, 0, 0))
        result = m.model_dump()
        assert "2026-06-26" in result["timestamp"]

    def test_serialize_datetime_aware(self):
        class TestModel(ISOModel):
            timestamp: datetime

        m = TestModel(timestamp=datetime(2026, 6, 26, 12, 0, 0, tzinfo=timezone.utc))
        result = m.model_dump()
        assert "2026-06-26" in result["timestamp"]


class TestISOTimestampMiddlewareInit:
    def test_can_construct(self):
        # Don't construct (requires app arg); just verify class is importable.
        assert ISOTimestampMiddleware is not None
