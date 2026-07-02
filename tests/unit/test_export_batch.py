"""Tests for Batch Exporter module."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.export.batch_exporter import (
    ExportFormat,
    ExportJob,
    ExportProgress,
    _build_chapter_markers,
    _build_project_metadata,
    _build_subtitle_entries,
    _collect_audio_files,
    export_chapter,
    export_project,
)


class TestExportFormat:
    """Tests for ExportFormat enum."""

    def test_enum_values(self):
        assert ExportFormat.M4B.value == "m4b"
        assert ExportFormat.SRT.value == "srt"
        assert ExportFormat.VTT.value == "vtt"
        assert ExportFormat.M4B_SRT.value == "m4b_srt"
        assert ExportFormat.ALL.value == "all"


class TestExportProgress:
    """Tests for ExportProgress enum."""

    def test_enum_values(self):
        assert ExportProgress.PENDING.value == "pending"
        assert ExportProgress.CONCATENATING.value == "concatenating"
        assert ExportProgress.CHAPTERING.value == "chaptering"
        assert ExportProgress.SUBTITLES.value == "subtitles"
        assert ExportProgress.DUCKING.value == "ducking"
        assert ExportProgress.COMPRESSING.value == "compressing"
        assert ExportProgress.COMPLETE.value == "complete"
        assert ExportProgress.FAILED.value == "failed"


class TestExportJob:
    """Tests for ExportJob dataclass."""

    def test_default_job(self):
        job = ExportJob(project_id=1)
        assert job.project_id == 1
        assert job.chapter_ids is None
        assert job.formats == {ExportFormat.M4B_SRT}
        assert job.bgm_path is None
        assert job.include_cover is True
        assert job.cover_image is None
        assert job.normalize is True
        assert job.subtitle_config is None
        assert job.mix_config is None
        assert job.output_dir is None
        assert job.progress == ExportProgress.PENDING
        assert job.output_paths == {}
        assert job.error is None

    def test_custom_job(self):
        job = ExportJob(
            project_id=2,
            chapter_ids=[1, 2, 3],
            formats={ExportFormat.M4B, ExportFormat.SRT},
            bgm_path="/path/to/bgm.mp3",
            include_cover=False,
            cover_image="/path/to/cover.jpg",
            normalize=False,
        )
        assert job.project_id == 2
        assert job.chapter_ids == [1, 2, 3]
        assert job.formats == {ExportFormat.M4B, ExportFormat.SRT}
        assert job.bgm_path == "/path/to/bgm.mp3"
        assert job.include_cover is False
        assert job.cover_image == "/path/to/cover.jpg"
        assert job.normalize is False


class TestBuildChapterMarkers:
    """Tests for _build_chapter_markers function."""

    def test_build_markers_basic(self):
        # Mock chapter data
        chapter_data = [
            {
                "chapter": MagicMock(title="Chapter 1", index=1),
                "audio_segments": [
                    MagicMock(file_path="/path/seg1.mp3", duration_ms=5000),
                    MagicMock(file_path="/path/seg2.mp3", duration_ms=3000),
                ],
            },
            {
                "chapter": MagicMock(title="Chapter 2", index=2),
                "audio_segments": [
                    MagicMock(file_path="/path/seg3.mp3", duration_ms=7000),
                ],
            },
        ]

        with patch("src.audiobook_studio.export.batch_exporter.get_duration_sync") as mock_get_duration:
            mock_get_duration.side_effect = [5000, 3000, 7000]
            markers = _build_chapter_markers(chapter_data)

        assert len(markers) == 2
        assert markers[0].title == "Chapter 1"
        assert markers[0].start_ms == 0
        assert markers[0].duration_ms == 8000
        assert markers[1].title == "Chapter 2"
        assert markers[1].start_ms == 8000
        assert markers[1].duration_ms == 7000

    def test_build_markers_with_fallback_duration(self):
        # When ffprobe fails, should use seg.duration_ms
        chapter_data = [
            {
                "chapter": MagicMock(title="Chapter 1", index=1),
                "audio_segments": [
                    MagicMock(file_path="/path/seg1.mp3", duration_ms=5000),
                ],
            },
        ]

        with patch("src.audiobook_studio.export.batch_exporter.get_duration_sync") as mock_get_duration:
            mock_get_duration.side_effect = Exception("ffprobe failed")
            markers = _build_chapter_markers(chapter_data)

        assert markers[0].duration_ms == 5000

    def test_build_markers_missing_file_fallback(self):
        chapter_data = [
            {
                "chapter": MagicMock(title="Chapter 1", index=1),
                "audio_segments": [
                    MagicMock(file_path="/nonexistent/seg1.mp3", duration_ms=5000),
                ],
            },
        ]

        with patch("src.audiobook_studio.export.batch_exporter.get_duration_sync") as mock_get_duration:
            mock_get_duration.side_effect = FileNotFoundError("File not found")
            markers = _build_chapter_markers(chapter_data)

        assert markers[0].duration_ms == 5000


class TestCollectAudioFiles:
    """Tests for _collect_audio_files function."""

    def test_collect_files_basic(self):
        chapter_data = [
            {
                "audio_segments": [
                    MagicMock(file_path="/path/seg1.mp3", id=1),
                    MagicMock(file_path="/path/seg2.mp3", id=2),
                ],
            },
            {
                "audio_segments": [
                    MagicMock(file_path="/path/seg3.mp3", id=3),
                ],
            },
        ]

        with patch("pathlib.Path.exists", return_value=True):
            files = _collect_audio_files(chapter_data)

        assert len(files) == 3
        assert all("seg" in str(f) for f in files)

    def test_collect_files_skips_missing(self):
        chapter_data = [
            {
                "audio_segments": [
                    MagicMock(file_path="/path/seg1.mp3", id=1),
                    MagicMock(file_path="/path/missing.mp3", id=2),
                ],
            },
        ]

        with patch("pathlib.Path.exists", side_effect=[True, False]):
            files = _collect_audio_files(chapter_data)

        assert len(files) == 1


class TestBuildSubtitleEntries:
    """Tests for _build_subtitle_entries function."""

    def test_build_entries_basic(self):
        chapter_data = [
            {
                "paragraphs": [
                    MagicMock(
                        id=1,
                        order=1,
                        text="First paragraph",
                        original_text=None,
                        character_name="Narrator",
                    ),
                    MagicMock(
                        id=2,
                        order=2,
                        text="Second paragraph",
                        original_text=None,
                        character_name="Character",
                    ),
                ],
                "audio_segments": [
                    MagicMock(paragraph_id=1, file_path="/path/seg1.mp3", duration_ms=3000),
                    MagicMock(paragraph_id=2, file_path="/path/seg2.mp3", duration_ms=4000),
                ],
            },
        ]

        with patch(
            "src.audiobook_studio.export.batch_exporter.get_duration_sync",
            side_effect=[3000, 4000],
        ):
            entries = _build_subtitle_entries(chapter_data)

        assert len(entries) == 2
        assert entries[0].text == "First paragraph"
        assert entries[0].speaker == "Narrator"
        assert entries[0].start_ms == 0
        assert entries[0].end_ms == 3000
        assert entries[1].text == "Second paragraph"
        assert entries[1].speaker == "Character"
        assert entries[1].start_ms == 3000
        assert entries[1].end_ms == 7000

    def test_build_entries_uses_original_text(self):
        chapter_data = [
            {
                "paragraphs": [
                    MagicMock(
                        id=1,
                        order=1,
                        text=None,
                        original_text="Original text",
                        character_name="Narrator",
                    ),
                ],
                "audio_segments": [
                    MagicMock(paragraph_id=1, file_path="/path/seg1.mp3", duration_ms=2000),
                ],
            },
        ]

        with patch(
            "src.audiobook_studio.export.batch_exporter.get_duration_sync",
            return_value=2000,
        ):
            entries = _build_subtitle_entries(chapter_data)

        assert entries[0].text == "Original text"

    def test_build_entries_no_duration_fallback(self):
        chapter_data = [
            {
                "paragraphs": [
                    MagicMock(id=1, order=1, text="No audio", character_name="Narrator"),
                ],
                "audio_segments": [],
            },
        ]

        entries = _build_subtitle_entries(chapter_data)

        assert len(entries) == 1
        assert entries[0].end_ms - entries[0].start_ms == 3000  # Default fallback


class TestBuildProjectMetadata:
    """Tests for _build_project_metadata function."""

    def test_build_metadata(self):
        project = MagicMock(title="Test Book", author="Test Author", slug="test-book")
        chapter_data = [
            {"chapter": MagicMock(title="Chapter 1")},
        ]

        metadata = _build_project_metadata(chapter_data, project)

        assert metadata.title == "Test Book"
        assert metadata.artist == "Test Author"
        assert metadata.album == "Test Book"

    def test_build_metadata_with_fallbacks(self):
        project = MagicMock(title=None, author=None, slug=None)
        chapter_data = [
            {"chapter": MagicMock(title="Chapter 1")},
        ]

        metadata = _build_project_metadata(chapter_data, project)

        assert metadata.title == "Untitled Audiobook"
        assert metadata.artist == "Unknown"
        assert metadata.album == "Untitled Audiobook"


class TestExportProject:
    """Tests for export_project function."""

    def test_export_project_not_found(self):
        mock_session = MagicMock()
        mock_session.query().filter_by().first.return_value = None

        job = ExportJob(project_id=999)
        result = export_project(999, mock_session, job)

        assert result.progress == ExportProgress.FAILED
        assert "not found" in result.error

    def test_export_project_no_chapters_with_audio(self):
        mock_project = MagicMock()
        mock_project.chapters = []
        mock_session = MagicMock()
        mock_session.query().filter_by().first.return_value = mock_project

        job = ExportJob(project_id=1)
        result = export_project(1, mock_session, job)

        assert result.progress == ExportProgress.FAILED
        assert "No chapters with audio" in result.error


class TestExportChapter:
    """Tests for export_chapter function."""

    def test_export_chapter_not_found(self):
        mock_session = MagicMock()
        mock_session.query().filter_by().first.return_value = None

        result = export_chapter(1, 999, mock_session)

        assert result is None

    def test_export_chapter_no_audio_files(self):
        mock_chapter = MagicMock(title="Test Chapter", index=1)
        mock_session = MagicMock()
        mock_session.query().filter_by().first.return_value = {
            "chapter": mock_chapter,
            "paragraphs": [],
            "audio_segments": [],
        }

        with patch(
            "src.audiobook_studio.export.batch_exporter._collect_chapter_data",
            return_value={
                "chapter": mock_chapter,
                "paragraphs": [],
                "audio_segments": [],
            },
        ):
            result = export_chapter(1, 1, mock_session)

        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestExportProjectSuccess:
    """Test successful project export scenarios."""

    def test_export_project_success_m4b_only(self):
        """Test successful project export with M4B format only."""
        # Setup
        mock_session = MagicMock()

        mock_chapter = MagicMock()
        mock_chapter.id = 1
        mock_chapter.index = 1
        mock_chapter.title = "Chapter 1"

        mock_project = MagicMock()
        mock_project.id = 1
        mock_project.slug = "test-book"
        mock_project.chapters = [mock_chapter]
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_project

        from src.audiobook_studio.export.batch_exporter import ExportFormat, ExportJob

        job = ExportJob(project_id=1, formats=[ExportFormat.M4B], output_dir="/tmp/test")

        # Mock the helper functions
        with (
            patch("src.audiobook_studio.export.batch_exporter._collect_chapter_data") as mock_collect,
            patch("src.audiobook_studio.export.batch_exporter.build_m4b") as mock_build_m4b,
            patch("src.audiobook_studio.export.batch_exporter.generate_srt"),
            patch("zipfile.ZipFile"),
        ):

            mock_collect.return_value = {"chapter": mock_chapter, "audio_segments": [], "chapter_data": {}}

            # Execute
            result = export_project(1, mock_session, job)

            # Verify
            assert result.progress.name == "COMPLETE"
            assert "m4b" in result.output_paths
            mock_build_m4b.assert_called_once()

    def test_export_project_success_with_chapters(self):
        """Test successful project export with chapters containing audio."""
        # Setup
        mock_session = MagicMock()

        mock_chapter = MagicMock()
        mock_chapter.id = 1
        mock_chapter.index = 1
        mock_chapter.title = "First Chapter"

        mock_paragraph = MagicMock()
        mock_paragraph.index = 1
        mock_paragraph.text = "Test paragraph"
        mock_paragraph.order = 1

        mock_project = MagicMock()
        mock_project.id = 1
        mock_project.slug = "test-book"
        mock_project.chapters = [mock_chapter]
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_project

        from src.audiobook_studio.export.batch_exporter import ExportFormat, ExportJob

        job = ExportJob(project_id=1, formats=[ExportFormat.M4B, ExportFormat.SRT], output_dir="/tmp/test")

        # Mock the helper functions
        with (
            patch("src.audiobook_studio.export.batch_exporter._collect_chapter_data") as mock_collect,
            patch("src.audiobook_studio.export.batch_exporter.build_m4b") as mock_build_m4b,
            patch("src.audiobook_studio.export.batch_exporter.generate_srt") as mock_gen_srt,
            patch("zipfile.ZipFile"),
        ):

            mock_collect.return_value = {
                "chapter": mock_chapter,
                "paragraphs": [mock_paragraph],
                "audio_segments": [MagicMock(file_path="/fake/path.mp3", duration_ms=5000)],
                "chapter_data": {},
            }

            # Execute
            result = export_project(1, mock_session, job)

            # Verify
            assert result.progress.name == "COMPLETE"
            assert "m4b" in result.output_paths
            assert "srt" in result.output_paths
            assert mock_build_m4b.call_count >= 1
            assert mock_gen_srt.called


class TestExportChapterSuccess:
    """Test successful chapter export scenarios."""

    def test_export_chapter_success(self):
        """Test successful chapter export."""
        # Setup
        mock_session = MagicMock()

        mock_chapter = MagicMock()
        mock_chapter.id = 1
        mock_chapter.index = 1
        mock_chapter.title = "Test Chapter"

        mock_paragraph = MagicMock()
        mock_paragraph.index = 1
        mock_paragraph.text = "Test paragraph"
        mock_paragraph.order = 1

        mock_session.query.return_value.filter.return_value.first.return_value = mock_chapter

        # Mock the helper functions
        with (
            patch("src.audiobook_studio.export.batch_exporter._collect_chapter_data") as mock_collect,
            patch("src.audiobook_studio.export.batch_exporter.get_duration_sync") as mock_get_duration,
            patch("src.audiobook_studio.export.batch_exporter.build_m4b") as mock_build_m4b,
            patch("pathlib.Path.exists", return_value=True),
        ):

            seg1 = MagicMock(file_path="/fake/path1.mp3", duration_ms=3000)
            seg1.id = 1
            seg2 = MagicMock(file_path="/fake/path2.mp3", duration_ms=4000)
            seg2.id = 2

            mock_collect.return_value = {
                "chapter": mock_chapter,
                "paragraphs": [mock_paragraph],
                "audio_segments": [seg1, seg2],
            }

            mock_get_duration.side_effect = [3000, 4000]

            # Execute
            result = export_chapter(1, 1, mock_session, "/tmp/test")

            # Verify
            assert result is not None
            assert "ch01_Test_Chapter.m4b" in result or "ch01_Test Chapter.m4b" in result
            mock_build_m4b.assert_called_once()

    def test_export_chapter_missing_audio_files(self):
        """Test chapter export when audio files are missing."""
        # Setup
        mock_session = MagicMock()

        mock_chapter = MagicMock()
        mock_chapter.id = 1
        mock_chapter.index = 1
        mock_chapter.title = "Test Chapter"

        mock_paragraph = MagicMock()
        mock_paragraph.index = 1
        mock_paragraph.text = "Test paragraph"
        mock_paragraph.order = 1

        mock_session.query.return_value.filter.return_value.first.return_value = mock_chapter

        # Mock the helper functions - Path.exists returns False for missing files
        seg1 = MagicMock()
        seg1.id = 1
        seg1.file_path = "/nonexistent/path1.mp3"
        seg1.duration_ms = 3000
        seg2 = MagicMock()
        seg2.id = 2
        seg2.file_path = "/nonexistent/path2.mp3"
        seg2.duration_ms = 4000

        with (
            patch("src.audiobook_studio.export.batch_exporter._collect_chapter_data") as mock_collect,
            patch("pathlib.Path.exists", return_value=False),
        ):

            mock_collect.return_value = {
                "chapter": mock_chapter,
                "paragraphs": [mock_paragraph],
                "audio_segments": [seg1, seg2],
            }

            # Execute
            result = export_chapter(1, 1, mock_session, "/tmp/test")

            # Verify - should return None when no audio files exist
            assert result is None


class TestExportErrorHandling:
    """Test error handling in export functions."""

    def test_export_project_database_error(self):
        """Test project export handles database errors gracefully."""
        # Setup
        mock_session = MagicMock()

        mock_session.query.return_value.filter_by.return_value.first.side_effect = Exception("DB connection failed")

        from src.audiobook_studio.export.batch_exporter import ExportFormat, ExportJob

        job = ExportJob(project_id=1, formats=[ExportFormat.M4B], output_dir="/tmp/test")

        # Execute
        result = export_project(1, mock_session, job)

        # Verify
        assert result.progress.name == "FAILED"
        assert "DB connection failed" in result.error

    def test_export_project_build_error(self):
        """Test project export handles build errors gracefully."""
        # Setup
        mock_session = MagicMock()

        mock_project = MagicMock()
        mock_project.id = 1
        mock_project.slug = "test-book"
        mock_project.chapters = [MagicMock(id=1)]
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_project

        from src.audiobook_studio.export.batch_exporter import ExportFormat, ExportJob

        job = ExportJob(project_id=1, formats=[ExportFormat.M4B], output_dir="/tmp/test")

        # Mock the helper functions to raise an exception during build
        with (
            patch("src.audiobook_studio.export.batch_exporter._collect_chapter_data") as mock_collect,
            patch("src.audiobook_studio.export.batch_exporter._collect_audio_files") as mock_collect_audio,
            patch("src.audiobook_studio.export.batch_exporter.build_m4b") as mock_build_m4b,
            patch("pathlib.Path.exists", return_value=True),
        ):

            mock_collect.return_value = {
                "chapter": MagicMock(id=1, index=1, title="Chapter 1"),
                "audio_segments": [MagicMock(file_path="/fake/path.mp3", duration_ms=5000, id=1)],
                "chapter_data": {},
            }
            mock_collect_audio.return_value = [Path("/fake/path.mp3")]
            mock_build_m4b.side_effect = Exception("FFmpeg failed")

            # Execute
            result = export_project(1, mock_session, job)

            # Verify
            assert result.progress.name == "FAILED"
            assert "FFmpeg failed" in result.error
