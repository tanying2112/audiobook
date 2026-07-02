"""Tests for Batch Exporter module."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.export.batch_exporter import (
    ExportFormat,
    ExportJob,
    ExportProgress,
    export_chapter,
    export_project,
)


def test_export_project_not_found():
    """Test export when project doesn't exist."""
    mock_session = MagicMock()
    mock_session.query.return_value.filter_by.return_value.first.return_value = None

    job = ExportJob(project_id=999, formats={ExportFormat.M4B})

    result = export_project(999, mock_session, job)

    assert result.progress == ExportProgress.FAILED
    assert "not found" in result.error.lower()


def test_export_project_no_chapters():
    """Test export when project has no chapters."""
    mock_session = MagicMock()
    mock_project = MagicMock()
    mock_project.id = 1
    mock_project.slug = "test-book"
    mock_project.chapters = []

    mock_session.query.return_value.filter_by.return_value.first.return_value = mock_project

    job = ExportJob(project_id=1, formats={ExportFormat.M4B})

    result = export_project(1, mock_session, job)

    assert result.progress == ExportProgress.FAILED
    assert "no chapters with audio segments" in result.error.lower()


def test_export_project_with_chapters_no_audio():
    """Test export when chapters exist but have no audio segments."""
    mock_session = MagicMock()
    mock_project = MagicMock()
    mock_project.id = 1
    mock_project.slug = "test-book"

    mock_chapter = MagicMock()
    mock_chapter.id = 1
    mock_project.chapters = [mock_chapter]

    mock_session.query.return_value.filter_by.return_value.first.return_value = mock_project

    job = ExportJob(project_id=1, formats={ExportFormat.M4B})

    with patch("src.audiobook_studio.export.batch_exporter._collect_chapter_data") as mock_collect:
        mock_collect.return_value = None  # No audio data

        result = export_project(1, mock_session, job)

        assert result.progress == ExportProgress.FAILED
        assert "no chapters with audio segments" in result.error.lower()


def test_export_project_success_m4b_only():
    """Test successful export with M4B format only."""
    mock_session = MagicMock()
    mock_project = MagicMock()
    mock_project.id = 1
    mock_project.slug = "test-book"

    mock_chapter = MagicMock()
    mock_chapter.id = 1
    mock_chapter.index = 1

    mock_project.chapters = [mock_chapter]
    mock_session.query.return_value.filter_by.return_value.first.return_value = mock_project

    with (
        patch("src.audiobook_studio.export.batch_exporter._collect_chapter_data") as mock_collect,
        patch("src.audiobook_studio.export.batch_exporter._collect_audio_files") as mock_audio_files,
        patch("src.audiobook_studio.export.batch_exporter._build_chapter_markers") as mock_markers,
        patch("src.audiobook_studio.export.batch_exporter._build_project_metadata") as mock_metadata,
        patch("src.audiobook_studio.export.batch_exporter.build_m4b") as mock_build_m4b,
        patch("src.audiobook_studio.export.batch_exporter.Path") as mock_path_class,
        patch("src.audiobook_studio.export.batch_exporter.logger"),
    ):

        mock_chapter_data = {
            "chapter": mock_chapter,
            "audio_segments": [MagicMock(file_path="/fake/path.mp3", id=1)],
            "chapter_data": {},
        }
        mock_collect.return_value = mock_chapter_data

        mock_audio_files.return_value = [Path("/fake/path.mp3")]
        mock_markers.return_value = []
        mock_metadata.return_value = MagicMock()

        mock_path_instance = MagicMock()
        mock_path_instance.__truediv__.return_value = mock_path_instance
        mock_path_instance.exists.return_value = False
        mock_path_instance.mkdir = MagicMock()
        mock_path_class.return_value = mock_path_instance

        job = ExportJob(project_id=1, formats={ExportFormat.M4B}, output_dir="/tmp/test")

        result = export_project(1, mock_session, job)

        assert result.progress == ExportProgress.COMPLETE
        assert result.error is None
        assert "m4b" in result.output_paths
        assert mock_build_m4b.called


def test_export_chapter_not_found():
    """Test export chapter when chapter doesn't exist."""
    with patch("src.audiobook_studio.export.batch_exporter._collect_chapter_data") as mock_collect:
        mock_collect.return_value = None

        result = export_chapter(1, 999, MagicMock())

        assert result is None


def test_export_chapter_no_audio_data():
    """Test export chapter when no audio data is collected."""
    with patch("src.audiobook_studio.export.batch_exporter._collect_chapter_data") as mock_collect:
        mock_collect.return_value = None

        result = export_chapter(1, 1, MagicMock())

        assert result is None


def test_export_chapter_no_audio_files_exist():
    """Test export chapter when audio files don't exist on filesystem."""
    with (
        patch("src.audiobook_studio.export.batch_exporter._collect_chapter_data") as mock_collect,
        patch("src.audiobook_studio.export.batch_exporter.Path") as mock_path_class,
    ):

        mock_collect.return_value = {
            "chapter": MagicMock(id=1, index=1, title="Test Chapter"),
            "audio_segments": [MagicMock(file_path="/fake/path.mp3", id=1)],
        }

        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = False
        mock_path_class.return_value = mock_path_instance

        result = export_chapter(1, 1, MagicMock())

        assert result is None


def test_export_chapter_success():
    """Test successful chapter export."""
    with (
        patch("src.audiobook_studio.export.batch_exporter._collect_chapter_data") as mock_collect,
        patch("src.audiobook_studio.export.batch_exporter.get_duration_sync") as mock_get_duration,
        patch("src.audiobook_studio.export.batch_exporter.Path") as mock_path_class,
        patch("src.audiobook_studio.export.batch_exporter.build_m4b") as mock_build_m4b,
    ):

        mock_chapter = MagicMock()
        mock_chapter.id = 1
        mock_chapter.index = 1
        mock_chapter.title = "Test Chapter"

        mock_audio_segment = MagicMock()
        mock_audio_segment.file_path = "/fake/path.mp3"
        mock_audio_segment.id = 1
        mock_audio_segment.duration_ms = 5000

        mock_paragraph = MagicMock()
        mock_paragraph.order = 0

        mock_collect.return_value = {
            "chapter": mock_chapter,
            "audio_segments": [mock_audio_segment],
            "paragraphs": [mock_paragraph],
        }

        # Mock Path behavior - return proper output path
        def path_div(*args, **kwargs):
            result = MagicMock()
            result.__str__.return_value = f"/tmp/output/ch01_Test_Chapter.m4b"
            result.exists.return_value = True
            return result

        mock_path_instance = MagicMock()
        mock_path_instance.__truediv__.side_effect = path_div
        mock_path_instance.exists.return_value = True
        mock_path_instance.__str__.return_value = "/fake/path.mp3"
        mock_path_class.return_value = mock_path_instance

        mock_get_duration.return_value = 5000

        result = export_chapter(1, 1, MagicMock(), "/tmp/output")

        assert result is not None
        assert "ch01" in result.lower()
        assert "m4b" in result.lower()
        assert mock_build_m4b.called


def test_export_chapter_with_fallback_duration():
    """Test chapter export with duration fallback when probing fails."""
    with (
        patch("src.audiobook_studio.export.batch_exporter._collect_chapter_data") as mock_collect,
        patch("src.audiobook_studio.export.batch_exporter.get_duration_sync") as mock_get_duration,
        patch("src.audiobook_studio.export.batch_exporter.Path") as mock_path_class,
        patch("src.audiobook_studio.export.batch_exporter.build_m4b") as mock_build_m4b,
    ):

        mock_chapter = MagicMock()
        mock_chapter.id = 1
        mock_chapter.index = 1
        mock_chapter.title = "Test Chapter"

        mock_audio_segment = MagicMock()
        mock_audio_segment.file_path = "/fake/path.mp3"
        mock_audio_segment.id = 1
        mock_audio_segment.duration_ms = 3000

        mock_paragraph = MagicMock()
        mock_paragraph.order = 0

        mock_collect.return_value = {
            "chapter": mock_chapter,
            "audio_segments": [mock_audio_segment],
            "paragraphs": [mock_paragraph],
        }

        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = True
        mock_path_instance.__str__.return_value = "/fake/path.mp3"
        mock_path_class.return_value = mock_path_instance

        mock_get_duration.side_effect = Exception("Probe failed")

        result = export_chapter(1, 1, MagicMock(), "/tmp/output")

        assert result is not None
        assert mock_build_m4b.called
