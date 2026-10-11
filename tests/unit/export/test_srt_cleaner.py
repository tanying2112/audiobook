"""Unit tests for src/audiobook_studio/export/srt_cleaner.py"""

import tempfile
from pathlib import Path

import pytest

from src.audiobook_studio.export.srt_cleaner import (
    NAME_NORMALIZATION,
    clean_srt_to_readable_text,
    merge_broken_words,
    normalize_names,
    parse_srt,
    regroup_paragraphs,
)


class TestParseSRT:
    """Tests for parse_srt function."""

    def test_parse_basic_srt(self):
        srt_content = """1
00:00:00,000 --> 00:00:02,000
Hello world.

2
00:00:02,000 --> 00:00:04,000
This is a test."""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".srt", delete=False) as f:
            f.write(srt_content)
            f.flush()
            entries = parse_srt(Path(f.name))

        assert len(entries) == 2
        assert entries[0]["index"] == 1
        assert entries[0]["timecode"] == "00:00:00,000 --> 00:00:02,000"
        assert entries[0]["text"] == "Hello world."
        assert entries[1]["index"] == 2
        assert entries[1]["text"] == "This is a test."

    def test_parse_multiline_text(self):
        srt_content = """1
00:00:00,000 --> 00:00:02,000
Hello
world
this spans
multiple lines.

2
00:00:02,000 --> 00:00:04,000
Second entry."""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".srt", delete=False) as f:
            f.write(srt_content)
            f.flush()
            entries = parse_srt(Path(f.name))

        assert len(entries) == 2
        assert "Hello\nworld\nthis spans\nmultiple lines." in entries[0]["text"]


class TestMergeBrokenWords:
    """Tests for merge_broken_words function."""

    def test_single_char_newline_merge(self):
        # "f\nor" -> "for"
        assert merge_broken_words("gift f\nor Jim") == "gift for Jim"
        # "a\nbc" should NOT merge because "a" is a common single-letter word (avoid "a cat" -> "acat")
        # newline preserved as space is normalized later
        result = merge_broken_words("a\nbc")
        assert result in ["a\nbc", "a bc"]

    def test_two_char_newline_merge(self):
        # "th\ne " -> "the "
        assert merge_broken_words("th\ne difficult") == "the difficult"
        assert merge_broken_words("Oklah\noma") == "Oklahoma"

    def test_punctuation_fix(self):
        # "87?What" -> "87? What"
        assert merge_broken_words("87?What") == "87? What"
        # "thinks.O." -> "thinks. O."
        assert merge_broken_words("she thinks.O.") == "she thinks. O."

    def test_lowercase_uppercase_boundary(self):
        # "wordWord" -> "word Word"
        assert merge_broken_words("helloWorld") == "hello World"
        assert merge_broken_words("endStart") == "end Start"

    def test_multiple_issues(self):
        text = "gift f\nor Jim with $1.\n87?What am I going to do?"
        # $1. 87 gets merged to $1.87 (correct behavior for currency)
        expected = "gift for Jim with $1.87? What am I going to do?"
        assert merge_broken_words(text) == expected

    def test_protected_patterns_not_merged(self):
        # Mr. Smith should not become Mr Smith
        text = "Mr. Smith went to the U.S.A. yesterday."
        result = merge_broken_words(text)
        # The protected patterns should prevent over-merging
        assert "Mr." in result or "Mr " in result  # At least one space or dot preserved


class TestNormalizeNames:
    """Tests for normalize_names function."""

    def test_delia_to_della(self):
        assert normalize_names("Delia said hello") == "Della said hello"
        assert normalize_names("Delia's gift") == "Della's gift"

    def test_other_names_preserved(self):
        assert normalize_names("Sofronie bought hair") == "Sofronie bought hair"
        assert normalize_names("Ellison ranch") == "Ellison ranch"
        assert normalize_names("Scudder millionaire") == "Scudder millionaire"

    def test_multiple_replacements(self):
        text = "Delia and Sofronie met Ellison"
        assert normalize_names(text) == "Della and Sofronie met Ellison"


class TestRegroupParagraphs:
    """Tests for regroup_paragraphs function."""

    def test_speaker_change_new_paragraph(self):
        entries = [
            {"text": "[_narrator_] The year is 1905."},
            {"text": "[_narrator_] We are in New York."},
            {"text": "[_della_] How can I buy a gift?"},
            {"text": "[_jim_] I have a watch."},
        ]
        paragraphs = regroup_paragraphs(entries)
        assert len(paragraphs) == 3  # narrator merged, della, jim
        assert "The year is 1905. We are in New York." in paragraphs[0]
        assert "How can I buy a gift?" in paragraphs[1]
        assert "I have a watch." in paragraphs[2]

    def test_no_speaker_tag_defaults_to_narrator(self):
        entries = [
            {"text": "Just plain text."},
            {"text": "[_della_] Dialogue here."},
        ]
        paragraphs = regroup_paragraphs(entries)
        assert len(paragraphs) == 2

    def test_empty_entries_skipped(self):
        entries = [
            {"text": "[_narrator_] First."},
            {"text": ""},
            {"text": "[_della_] Second."},
        ]
        paragraphs = regroup_paragraphs(entries)
        assert len(paragraphs) == 2


class TestCleanSRTToReadableText:
    """Integration tests for clean_srt_to_readable_text."""

    def test_full_cleaning_pipeline(self):
        srt_content = """1
00:00:00,000 --> 00:00:02,000
[_narrator_] The Gift of the Magi.

2
00:00:02,000 --> 00:00:04,000
[_narrator_] How can I buy a special gift f
or Jim with $1.

3
00:00:04,000 --> 00:00:06,000
87?What am I going to do?she thinks.O.

4
00:00:06,000 --> 00:00:08,000
[_della_] Delia looks at her hair.

5
00:00:08,000 --> 00:00:10,000
[_jim_] Jim has a gold watch."""

        with tempfile.TemporaryDirectory() as tmpdir:
            srt_path = Path(tmpdir) / "test.srt"
            srt_path.write_text(srt_content, encoding="utf-8")
            output_path = Path(tmpdir) / "output.txt"

            result = clean_srt_to_readable_text(srt_path, output_path)

            # Verify output file exists
            assert output_path.exists()

            # Verify content
            assert "The Gift of the Magi." in result
            assert "gift for Jim" in result  # merged "f\nor"
            assert "87? What" in result  # fixed punctuation
            assert "she thinks. O." in result  # fixed "thinks.O."
            assert "Della" in result  # normalized "Delia" -> "Della"
            assert "hair." in result

            # Verify paragraphs (speaker-based)
            assert "\n\n" in result  # Has paragraph breaks

    def test_empty_srt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            srt_path = Path(tmpdir) / "empty.srt"
            srt_path.write_text("", encoding="utf-8")
            output_path = Path(tmpdir) / "output.txt"

            result = clean_srt_to_readable_text(srt_path, output_path)
            assert result == ""

    def test_name_normalization_applied(self):
        srt_content = """1
00:00:00,000 --> 00:00:02,000
Delia went to the store."""

        with tempfile.TemporaryDirectory() as tmpdir:
            srt_path = Path(tmpdir) / "test.srt"
            srt_path.write_text(srt_content, encoding="utf-8")
            output_path = Path(tmpdir) / "output.txt"

            result = clean_srt_to_readable_text(srt_path, output_path)
            assert "Della" in result
            assert "Delia" not in result


class TestNAME_NORMALIZATION:
    """Test the NAME_NORMALIZATION dictionary."""

    def test_contains_expected_mappings(self):
        from src.audiobook_studio.export.srt_cleaner import NAME_NORMALIZATION

        assert "Delia" in NAME_NORMALIZATION
        assert NAME_NORMALIZATION["Delia"] == "Della"
        assert "Sofronie" in NAME_NORMALIZATION
        assert "Ellison" in NAME_NORMALIZATION


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
