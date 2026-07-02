"""Tests for SRT export module."""

import tempfile
from pathlib import Path

import pytest

from src.audiobook_studio.export.srt import (
    SubtitleConfig,
    SubtitleEntry,
    _ms_to_srt,
    _split_long_text,
    build_subtitle_entries_from_paragraphs,
    generate_srt,
)


class TestMsToSrt:
    """Tests for _ms_to_srt function."""

    def test_basic_conversion(self):
        """Test basic millisecond to SRT format conversion."""
        assert _ms_to_srt(0) == "00:00:00,000"
        assert _ms_to_srt(1000) == "00:00:01,000"
        assert _ms_to_srt(60000) == "00:01:00,000"
        assert _ms_to_srt(3600000) == "01:00:00,000"
        assert _ms_to_srt(3661000) == "01:01:01,000"

    def test_millisecond_precision(self):
        """Test millisecond precision."""
        assert _ms_to_srt(1234) == "00:00:01,234"
        assert _ms_to_srt(59999) == "00:00:59,999"
        assert _ms_to_srt(61000) == "00:01:01,000"


class TestSplitLongText:
    """Tests for _split_long_text function."""

    def test_short_text(self):
        """Test short text is returned as-is."""
        text = "Short text"
        result = _split_long_text(text, 40)
        assert result == ["Short text"]

    def test_exact_length(self):
        """Test text at exact max length."""
        text = "A" * 40
        result = _split_long_text(text, 40)
        assert result == [text]

    def test_long_text_splitting(self):
        """Test long text gets split."""
        text = "This is a very long text that should be split into multiple parts because it exceeds the maximum character limit"
        result = _split_long_text(text, 20)
        assert len(result) > 1
        assert all(len(chunk) <= 20 for chunk in result)

    def test_chinese_text_splitting(self):
        """Test Chinese text splitting on sentence boundaries."""
        text = "这是第一句话。这是第二句话！这是第三句话？"
        result = _split_long_text(text, 10)
        assert len(result) >= 3


class TestSubtitleEntry:
    """Tests for SubtitleEntry dataclass."""

    def test_create_entry(self):
        """Test creating a subtitle entry."""
        entry = SubtitleEntry(
            index=1,
            start_ms=0,
            end_ms=5000,
            text="Hello world",
            speaker="Narrator",
        )
        assert entry.index == 1
        assert entry.start_ms == 0
        assert entry.end_ms == 5000
        assert entry.text == "Hello world"
        assert entry.speaker == "Narrator"

    def test_to_srt_block_with_speaker(self):
        """Test SRT block generation with speaker."""
        entry = SubtitleEntry(
            index=1,
            start_ms=0,
            end_ms=5000,
            text="Hello world",
            speaker="Narrator",
        )
        block = entry.to_srt_block()
        assert "1" in block
        assert "00:00:00,000 --> 00:00:05,000" in block
        assert "[Narrator] Hello world" in block

    def test_to_srt_block_without_speaker(self):
        """Test SRT block generation without speaker."""
        entry = SubtitleEntry(
            index=2,
            start_ms=5000,
            end_ms=10000,
            text="Hello world",
        )
        block = entry.to_srt_block()
        assert "2" in block
        assert "00:00:05,000 --> 00:00:10,000" in block
        assert "Hello world" in block
        assert "[" not in block


class TestSubtitleConfig:
    """Tests for SubtitleConfig dataclass."""

    def test_default_config(self):
        """Test default configuration."""
        config = SubtitleConfig()
        assert config.max_chars_per_line == 40
        assert config.max_duration_per_entry_ms == 5000
        assert config.min_duration_per_entry_ms == 1000
        assert config.include_speaker is True
        assert config.language == "chi"

    def test_custom_config(self):
        """Test custom configuration."""
        config = SubtitleConfig(
            max_chars_per_line=50,
            max_duration_per_entry_ms=10000,
            include_speaker=False,
            language="eng",
        )
        assert config.max_chars_per_line == 50
        assert config.max_duration_per_entry_ms == 10000
        assert config.include_speaker is False
        assert config.language == "eng"


class TestGenerateSrt:
    """Tests for generate_srt function."""

    def test_generate_srt_basic(self):
        """Test basic SRT generation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test.srt"
            entries = [
                SubtitleEntry(1, 0, 3000, "First subtitle", "Speaker1"),
                SubtitleEntry(2, 3000, 6000, "Second subtitle", "Speaker2"),
                SubtitleEntry(3, 6000, 9000, "Third subtitle"),
            ]

            result = generate_srt(entries, output_path)
            assert result == output_path
            assert output_path.exists()

            content = output_path.read_text(encoding="utf-8")
            assert "1" in content
            assert "00:00:00,000 --> 00:00:03,000" in content
            assert "[Speaker1] First subtitle" in content
            assert "[Speaker2] Second subtitle" in content
            assert "Third subtitle" in content

            # Check VTT was also created
            vtt_path = output_path.with_suffix(".vtt")
            assert vtt_path.exists()
            vtt_content = vtt_path.read_text(encoding="utf-8")
            assert "WEBVTT" in vtt_content

    def test_generate_srt_short_duration_extended(self):
        """Test short durations are extended to minimum."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test.srt"
            config = SubtitleConfig(min_duration_per_entry_ms=1000)

            # Entry with 500ms duration - should be extended to 1000ms
            entries = [
                SubtitleEntry(1, 0, 500, "Very short"),
            ]

            result = generate_srt(entries, output_path, config)
            content = output_path.read_text(encoding="utf-8")
            # End time should be 1000ms (extended)
            assert "00:00:00,000 --> 00:00:01,000" in content

    def test_generate_srt_long_duration_split(self):
        """Test long durations are split into multiple entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test.srt"
            config = SubtitleConfig(
                max_duration_per_entry_ms=2000,
                max_chars_per_line=10,
            )

            # Entry with 6000ms duration - should be split
            entries = [
                SubtitleEntry(1, 0, 6000, "This is a very long text that needs splitting"),
            ]

            result = generate_srt(entries, output_path, config)
            content = output_path.read_text(encoding="utf-8")

            # Should have multiple entries now
            lines = content.strip().split("\n")
            # Each entry has 3 lines (index, time, text) + blank line
            assert len(lines) > 3

    def test_generate_srt_creates_directories(self):
        """Test that output directories are created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "subdir" / "test.srt"
            entries = [SubtitleEntry(1, 0, 3000, "Test")]

            result = generate_srt(entries, output_path)
            assert result == output_path
            assert output_path.exists()


class TestBuildSubtitleEntries:
    """Tests for build_subtitle_entries_from_paragraphs function."""

    def test_build_entries_basic(self):
        """Test building entries from paragraphs and audio segments."""
        paragraphs = [
            {"id": 1, "text": "First paragraph", "character_name": "Narrator"},
            {"id": 2, "text": "Second paragraph", "character_name": "Character"},
        ]
        audio_segments = [
            {"paragraph_id": 1, "duration_ms": 3000},
            {"paragraph_id": 2, "duration_ms": 4000},
        ]

        entries = build_subtitle_entries_from_paragraphs(paragraphs, audio_segments)

        assert len(entries) == 2
        assert entries[0].text == "First paragraph"
        assert entries[0].speaker == "Narrator"
        assert entries[0].start_ms == 0
        assert entries[0].end_ms == 3000
        assert entries[1].text == "Second paragraph"
        assert entries[1].speaker == "Character"
        assert entries[1].start_ms == 3000
        assert entries[1].end_ms == 7000

    def test_build_entries_missing_duration(self):
        """Test default duration when audio segment missing."""
        paragraphs = [
            {"id": 1, "text": "No audio segment"},
        ]
        audio_segments = []

        entries = build_subtitle_entries_from_paragraphs(paragraphs, audio_segments)

        assert len(entries) == 1
        # Default duration is 3000ms
        assert entries[0].end_ms - entries[0].start_ms == 3000

    def test_build_entries_original_text_fallback(self):
        """Test using original_text when text missing."""
        paragraphs = [
            {"id": 1, "original_text": "Original text content"},
        ]
        audio_segments = [
            {"paragraph_id": 1, "duration_ms": 2000},
        ]

        entries = build_subtitle_entries_from_paragraphs(paragraphs, audio_segments)
        assert entries[0].text == "Original text content"

    def test_build_entries_skips_invalid_segments(self):
        """Test segments without paragraph_id are skipped."""
        paragraphs = [
            {"id": 1, "text": "Valid"},
        ]
        audio_segments = [
            {"duration_ms": 3000},  # Missing paragraph_id
            {"paragraph_id": 1, "duration_ms": 2000},
        ]

        entries = build_subtitle_entries_from_paragraphs(paragraphs, audio_segments)
        assert len(entries) == 1
        assert entries[0].text == "Valid"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
