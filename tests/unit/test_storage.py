"""Tests for storage module."""

import tempfile
from pathlib import Path

import pytest

from src.audiobook_studio.storage import (
    annotated_dir,
    audio_dir,
    audio_file_path,
    extracted_dir,
    load_chapter_annotations,
    load_extracted_text,
    load_report,
    project_dir,
    raw_dir,
    raw_file_path,
    reports_dir,
    remove_project_storage,
    save_audio,
    save_chapter_annotations,
    save_extracted_text,
    save_raw_file,
    save_report,
)


@pytest.fixture
def temp_storage():
    """Create a temporary storage root."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Patch the storage root
        import src.audiobook_studio.storage as storage_mod
        original_root = storage_mod._STORAGE_ROOT
        storage_mod._STORAGE_ROOT = Path(tmpdir)
        yield Path(tmpdir)
        storage_mod._STORAGE_ROOT = original_root


class TestPathHelpers:
    """Tests for path helper functions."""

    def test_project_dir(self, temp_storage):
        """Test project_dir returns correct path."""
        path = project_dir(42, ensure=True)
        assert path == temp_storage / "books" / "42"
        assert path.exists()
        # Check subdirectories were created
        for sub in ["raw", "extracted", "annotated", "audio", "reports"]:
            assert (path / sub).exists()

    def test_project_dir_no_ensure(self, temp_storage):
        """Test project_dir without ensure doesn't create dirs."""
        path = project_dir(42, ensure=False)
        assert path == temp_storage / "books" / "42"
        assert not path.exists()

    def test_raw_dir(self, temp_storage):
        """Test raw_dir helper."""
        path = raw_dir(42, ensure=True)
        assert path == temp_storage / "books" / "42" / "raw"
        assert path.exists()

    def test_extracted_dir(self, temp_storage):
        """Test extracted_dir helper."""
        path = extracted_dir(42, ensure=True)
        assert path == temp_storage / "books" / "42" / "extracted"
        assert path.exists()

    def test_annotated_dir(self, temp_storage):
        """Test annotated_dir helper."""
        path = annotated_dir(42, ensure=True)
        assert path == temp_storage / "books" / "42" / "annotated"
        assert path.exists()

    def test_audio_dir(self, temp_storage):
        """Test audio_dir helper."""
        path = audio_dir(42, ensure=True)
        assert path == temp_storage / "books" / "42" / "audio"
        assert path.exists()

    def test_reports_dir(self, temp_storage):
        """Test reports_dir helper."""
        path = reports_dir(42, ensure=True)
        assert path == temp_storage / "books" / "42" / "reports"
        assert path.exists()

    def test_chapter_filename(self):
        """Test _chapter_filename helper."""
        from src.audiobook_studio.storage import _chapter_filename
        assert _chapter_filename(1, ".txt") == "ch_001.txt"
        assert _chapter_filename(5, ".json") == "ch_005.json"
        assert _chapter_filename(100, ".md") == "ch_100.md"

    def test_paragraph_basename(self):
        """Test _paragraph_basename helper."""
        from src.audiobook_studio.storage import _paragraph_basename
        assert _paragraph_basename(1, 1) == "ch_001_p_001"
        assert _paragraph_basename(5, 42) == "ch_005_p_042"
        assert _paragraph_basename(100, 999) == "ch_100_p_999"


class TestRawFiles:
    """Tests for raw file operations."""

    def test_save_raw_file(self, temp_storage):
        """Test saving raw file."""
        content = b"Test PDF content"
        path = save_raw_file(42, 1, content, suffix=".pdf")
        assert path.exists()
        assert path.read_bytes() == content
        assert path.suffix == ".pdf"

    def test_save_raw_file_default_suffix(self, temp_storage):
        """Test saving raw file with default suffix."""
        content = b"Test text"
        path = save_raw_file(42, 1, content)
        assert path.suffix == ".txt"

    def test_raw_file_path(self, temp_storage):
        """Test raw_file_path returns correct path."""
        path = raw_file_path(42, 1, ".epub")
        expected = temp_storage / "books" / "42" / "raw" / "ch_001.epub"
        assert path == expected
        # Should not create file
        assert not path.exists()


class TestExtractedText:
    """Tests for extracted text operations."""

    def test_save_and_load_extracted_text(self, temp_storage):
        """Test saving and loading extracted text."""
        text = "Chapter 1 content...\n\nParagraph 2..."
        save_path = save_extracted_text(42, 1, text)
        assert save_path.exists()
        assert save_path.suffix == ".txt"

        loaded = load_extracted_text(42, 1)
        assert loaded == text

    def test_load_missing_extracted_text(self, temp_storage):
        """Test loading missing text returns None."""
        loaded = load_extracted_text(42, 999)
        assert loaded is None


class TestAnnotations:
    """Tests for annotation operations."""

    def test_save_and_load_chapter_annotations(self, temp_storage):
        """Test saving and loading annotations."""
        annotations = [
            {"paragraph_index": 1, "speaker": "旁白", "emotion": "neutral"},
            {"paragraph_index": 2, "speaker": "主角", "emotion": "happy"},
        ]
        save_path = save_chapter_annotations(42, 1, annotations)
        assert save_path.exists()
        assert save_path.suffix == ".json"

        loaded = load_chapter_annotations(42, 1)
        assert loaded == annotations

    def test_load_missing_annotations(self, temp_storage):
        """Test loading missing annotations returns None."""
        loaded = load_chapter_annotations(42, 999)
        assert loaded is None


class TestAudioFiles:
    """Tests for audio file operations."""

    def test_audio_file_path(self, temp_storage):
        """Test audio_file_path returns correct path."""
        path = audio_file_path(42, 1, 5, fmt="mp3")
        expected = temp_storage / "books" / "42" / "audio" / "ch_001_p_005.mp3"
        assert path == expected
        assert not path.exists()

    def test_audio_file_path_custom_format(self, temp_storage):
        """Test audio_file_path with custom format."""
        path = audio_file_path(42, 1, 5, fmt="wav")
        assert path.suffix == ".wav"

    def test_save_audio(self, temp_storage):
        """Test saving audio file."""
        content = b"fake audio data"
        path = save_audio(42, 1, 5, content, fmt="mp3")
        assert path.exists()
        assert path.read_bytes() == content

    def test_save_audio_creates_dir(self, temp_storage):
        """Test save_audio creates parent directories."""
        content = b"audio"
        path = save_audio(42, 1, 5, content)
        assert path.parent.exists()


class TestReports:
    """Tests for report operations."""

    def test_save_and_load_report(self, temp_storage):
        """Test saving and loading report."""
        data = {"quality_score": 0.95, "issues": [], "duration_ms": 5000}
        path = save_report(42, "quality_summary", data)
        assert path.exists()
        assert path.name == "quality_summary.json"

        loaded = load_report(42, "quality_summary")
        assert loaded == data

    def test_load_missing_report(self, temp_storage):
        """Test loading missing report returns None."""
        loaded = load_report(42, "nonexistent")
        assert loaded is None


class TestCleanup:
    """Tests for cleanup operations."""

    def test_remove_project_storage(self, temp_storage):
        """Test removing project storage."""
        # Create some files
        save_raw_file(42, 1, b"test")
        save_extracted_text(42, 1, "text")
        assert project_dir(42).exists()

        # Remove
        remove_project_storage(42)
        assert not project_dir(42).exists()

    def test_remove_nonexistent_project(self, temp_storage):
        """Test removing nonexistent project doesn't error."""
        remove_project_storage(999)
        # Should not raise


class TestMultipleProjects:
    """Tests for multiple projects."""

    def test_independent_projects(self, temp_storage):
        """Test projects are independent."""
        save_raw_file(1, 1, b"project 1")
        save_raw_file(2, 1, b"project 2")

        p1 = load_extracted_text(1, 1) is None  # raw not extracted
        p2 = load_extracted_text(2, 1) is None
        # Just verify both dirs exist independently
        assert (temp_storage / "books" / "1").exists()
        assert (temp_storage / "books" / "2").exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])