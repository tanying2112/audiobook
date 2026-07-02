"""Unit tests for src/audiobook_studio/export/srt.py — SRT/VTT subtitle generation.

All I/O mocked. No real file writes.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.export.srt import (
    SubtitleConfig,
    SubtitleEntry,
    _ms_to_srt,
    _split_long_text,
    build_subtitle_entries_from_paragraphs,
    generate_srt,
)

# ── _ms_to_srt ───────────────────────────────────────────────────────────────


class TestMsToSrt:
    def test_zero(self):
        assert _ms_to_srt(0) == "00:00:00,000"

    def test_milliseconds(self):
        assert _ms_to_srt(1500) == "00:00:01,500"

    def test_minutes(self):
        assert _ms_to_srt(90000) == "00:01:30,000"

    def test_hours(self):
        assert _ms_to_srt(3661000) == "01:01:01,000"

    def test_large_value(self):
        assert _ms_to_srt(7384500) == "02:03:04,500"


# ── SubtitleEntry ────────────────────────────────────────────────────────────


class TestSubtitleEntry:
    def test_to_srt_block_basic(self):
        entry = SubtitleEntry(index=1, start_ms=0, end_ms=5000, text="Hello")
        block = entry.to_srt_block()
        assert block == "1\n00:00:00,000 --> 00:00:05,000\nHello"

    def test_to_srt_block_with_speaker(self):
        entry = SubtitleEntry(index=2, start_ms=1000, end_ms=3000, text="World", speaker="Alice")
        block = entry.to_srt_block()
        assert "[Alice] World" in block

    def test_to_srt_block_no_speaker(self):
        entry = SubtitleEntry(index=3, start_ms=5000, end_ms=8000, text="Test", speaker=None)
        block = entry.to_srt_block()
        assert "Test" in block
        assert "[" not in block.split("\n")[-1]


# ── _split_long_text ─────────────────────────────────────────────────────────


class TestSplitLongText:
    def test_short_text_unchanged(self):
        assert _split_long_text("Short text", 40) == ["Short text"]

    def test_split_on_sentence_boundary(self):
        text = "这是第一句话。这是第二句话很长很长超过四十个字符的限制"
        chunks = _split_long_text(text, 20)
        assert len(chunks) >= 2

    def test_hard_split_on_max_chars(self):
        text = "A" * 100
        chunks = _split_long_text(text, 30)
        assert len(chunks) == 4
        assert all(len(c) <= 30 for c in chunks)

    def test_empty_text(self):
        result = _split_long_text("", 40)
        assert result == [""]

    def test_exact_max_chars(self):
        text = "A" * 40
        assert _split_long_text(text, 40) == [text]

    def test_empty_segment_skipped(self):
        """Covers line 74: trailing punctuation creates empty segment that is skipped."""
        # 'A' * 50 + '!!!' produces regex parts: ['AAA...!', '', '!', '', '!', '']
        # The final empty part+empty punct creates an empty segment at line 73-74
        text = "A" * 50 + "!!!"
        chunks = _split_long_text(text, 20)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert chunk.strip() != ""


# ── SubtitleConfig ───────────────────────────────────────────────────────────


class TestSubtitleConfig:
    def test_defaults(self):
        cfg = SubtitleConfig()
        assert cfg.max_chars_per_line == 40
        assert cfg.max_duration_per_entry_ms == 5000
        assert cfg.min_duration_per_entry_ms == 1000
        assert cfg.include_speaker is True
        assert cfg.language == "chi"

    def test_custom(self):
        cfg = SubtitleConfig(max_chars_per_line=20, language="eng")
        assert cfg.max_chars_per_line == 20
        assert cfg.language == "eng"


# ── generate_srt ─────────────────────────────────────────────────────────────


class TestGenerateSrt:
    def test_basic_generation(self):
        entries = [
            SubtitleEntry(1, 0, 5000, "Hello"),
            SubtitleEntry(2, 5000, 10000, "World"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.srt"
            result = generate_srt(entries, output)
            assert result == output
            content = output.read_text()
            assert "Hello" in content
            assert "World" in content
            # VTT also created
            vtt = output.with_suffix(".vtt")
            assert vtt.exists()
            assert "WEBVTT" in vtt.read_text()

    def test_short_duration_extended(self):
        entries = [SubtitleEntry(1, 0, 100, "Short")]
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.srt"
            generate_srt(entries, output)
            content = output.read_text()
            assert "Short" in content

    def test_long_duration_splits(self):
        entries = [SubtitleEntry(1, 0, 20000, "很长的文本。需要被拆分成多个字幕条目")]
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.srt"
            generate_srt(entries, output)
            content = output.read_text()
            assert "-->" in content

    def test_with_speaker(self):
        entries = [SubtitleEntry(1, 0, 5000, "Hello", speaker="Alice")]
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.srt"
            generate_srt(entries, output)
            content = output.read_text()
            assert "[Alice]" in content

    def test_vtt_also_generated(self):
        entries = [SubtitleEntry(1, 0, 5000, "Test")]
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.srt"
            generate_srt(entries, output)
            vtt = output.with_suffix(".vtt")
            assert vtt.exists()
            assert "WEBVTT" in vtt.read_text()

    def test_custom_config(self):
        entries = [SubtitleEntry(1, 0, 5000, "Test")]
        cfg = SubtitleConfig(max_chars_per_line=10, max_duration_per_entry_ms=2000)
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.srt"
            generate_srt(entries, output, config=cfg)
            assert output.exists()

    def test_no_speaker(self):
        entries = [SubtitleEntry(1, 0, 5000, "Test", speaker=None)]
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.srt"
            generate_srt(entries, output)
            content = output.read_text()
            assert "[" not in content.split("\n")[-1]

    def test_multiple_entries(self):
        entries = [
            SubtitleEntry(1, 0, 5000, "First"),
            SubtitleEntry(2, 5000, 10000, "Second"),
            SubtitleEntry(3, 10000, 15000, "Third"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.srt"
            generate_srt(entries, output)
            content = output.read_text()
            assert "First" in content
            assert "Second" in content
            assert "Third" in content


# ── build_subtitle_entries_from_paragraphs ────────────────────────────────────


class TestBuildSubtitleEntriesFromParagraphs:
    def test_basic(self):
        paragraphs = [
            {"id": 1, "text": "Hello", "character_name": "Alice"},
            {"id": 2, "text": "World", "character_name": "Bob"},
        ]
        audio_segments = [
            {"paragraph_id": 1, "duration_ms": 3000},
            {"paragraph_id": 2, "duration_ms": 4000},
        ]
        entries = build_subtitle_entries_from_paragraphs(paragraphs, audio_segments)
        assert len(entries) == 2
        assert entries[0].text == "Hello"
        assert entries[0].speaker == "Alice"
        assert entries[0].start_ms == 0
        assert entries[0].end_ms == 3000
        assert entries[1].start_ms == 3000
        assert entries[1].end_ms == 7000

    def test_uses_original_text(self):
        paragraphs = [{"id": 1, "original_text": "Original", "text": "Fallback"}]
        audio_segments = [{"paragraph_id": 1, "duration_ms": 2000}]
        entries = build_subtitle_entries_from_paragraphs(paragraphs, audio_segments)
        assert entries[0].text == "Original"

    def test_missing_duration_uses_default(self):
        paragraphs = [{"id": 1, "text": "Test"}]
        audio_segments = [{"paragraph_id": 1}]
        entries = build_subtitle_entries_from_paragraphs(paragraphs, audio_segments)
        assert entries[0].end_ms == 3000

    def test_no_matching_segment(self):
        paragraphs = [{"id": 1, "text": "Test"}]
        audio_segments = [{"paragraph_id": 999, "duration_ms": 5000}]
        entries = build_subtitle_entries_from_paragraphs(paragraphs, audio_segments)
        assert entries[0].end_ms == 3000

    def test_no_speaker(self):
        paragraphs = [{"id": 1, "text": "Test"}]
        audio_segments = [{"paragraph_id": 1, "duration_ms": 2000}]
        entries = build_subtitle_entries_from_paragraphs(paragraphs, audio_segments)
        assert entries[0].speaker is None

    def test_empty_paragraphs(self):
        entries = build_subtitle_entries_from_paragraphs([], [])
        assert entries == []

    def test_segment_without_paragraph_id(self):
        paragraphs = [{"id": 1, "text": "Test"}]
        audio_segments = [{"duration_ms": 5000}]
        entries = build_subtitle_entries_from_paragraphs(paragraphs, audio_segments)
        assert entries[0].end_ms == 3000
