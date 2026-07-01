"""Enhanced tests for Batch Exporter module to improve coverage."""

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


class TestExportProject:
    """Test project export functionality."""

    def test_export_project_not_found(self):
        """Test export when project doesn't exist."""
        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = None
        
        job = ExportJob(project_id=999, formats={ExportFormat.M4B})
        
        result = export_project(999, mock_session, job)
        
        assert result.progress == ExportProgress.FAILED
        assert "not found" in result.error

    def test_export_project_no_chapters(self):
        """Test export when project has no chapters."""
        mock_session = MagicMock()
        mock_project = MagicMock()
        mock_project.id = 1
        mock_project.slug = "test-book"
        mock_project.chapters = []  # No chapters
        
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_project
        
        job = ExportJob(project_id=1, formats={ExportFormat.M4B})
        
        result = export_project(1, mock_session, job)
        
        assert result.progress == ExportProgress.FAILED
        assert "No chapters with audio segments found" in result.error

    def test_export_project_with_chapters_no_audio(self):
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
        
        with patch('src.audiobook_studio.export.batch_exporter._collect_chapter_data') as mock_collect:
            mock_collect.return_value = None  # No audio data
            
            result = export_project(1, mock_session, job)
            
            assert result.progress == ExportProgress.FAILED
            assert "No chapters with audio segments found" in result.error

    @patch('src.audiobook_studio.export.batch_exporter._collect_chapter_data')
    @patch('src.audiobook_studio.export.batch_exporter._collect_audio_files')
    @patch('src.audiobook_studio.export.batch_exporter._build_chapter_markers')
    @patch('src.audiobook_studio.export.batch_exporter._build_project_metadata')
    @patch('src.audiobook_studio.export.batch_exporter.build_m4b')
    @patch('src.audiobook_studio.export.batch_exporter.generate_srt')
    @patch('pathlib.Path')
    def test_export_project_success_m4b_and_srt(
        self, mock_path_class, mock_gen_srt, mock_build_m4b,
        mock_metadata, mock_markers, mock_audio_files, mock_collect
    ):
        """Test successful export with both M4B and SRT formats."""
        # Setup
        mock_session = MagicMock()
        mock_project = MagicMock()
        mock_project.id = 1
        mock_project.slug = "test-book"
        
        mock_chapter = MagicMock()
        mock_chapter.id = 1
        mock_chapter.index = 1
        
        mock_project.chapters = [mock_chapter]
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_project

        # Mock data collection
        mock_paragraph = MagicMock()
        mock_paragraph.id = 1
        mock_paragraph.order = 1
        mock_paragraph.text = "Test paragraph"
        mock_paragraph.original_text = None
        mock_paragraph.character_name = "Narrator"

        mock_chapter_data = {
            "chapter": mock_chapter,
            "audio_segments": [MagicMock(file_path="/fake/path.mp3", id=1)],
            "chapter_data": {},
            "paragraphs": [mock_paragraph]
        }
        mock_collect.return_value = mock_chapter_data
        
        # Mock file operations
        mock_audio_files.return_value = [Path("/fake/path.mp3")]
        mock_markers.return_value = []
        mock_metadata.return_value = MagicMock()

        # Mock Path behavior - use real Path but mock methods
        mock_path_instance = MagicMock()
        mock_path_instance.__truediv__.return_value = mock_path_instance
        mock_path_instance.exists.return_value = False
        mock_path_instance.mkdir = MagicMock()
        mock_path_instance.__str__.return_value = "/tmp/test/output.m4b"
        mock_path_class.return_value = mock_path_instance

        job = ExportJob(
            project_id=1,
            formats={ExportFormat.M4B, ExportFormat.SRT},
            output_dir="/tmp/test"
        )
        
        result = export_project(1, mock_session, job)
        
        # Verify success
        assert result.progress == ExportProgress.COMPLETE
        assert result.error is None
        assert "m4b" in result.output_paths
        assert "srt" in result.output_paths
        
        # Verify function calls
        assert mock_build_m4b.called
        assert mock_gen_srt.called

    @patch('src.audiobook_studio.export.batch_exporter._collect_chapter_data')
    @patch('src.audiobook_studio.export.batch_exporter._collect_audio_files')
    @patch('src.audiobook_studio.export.batch_exporter._build_chapter_markers')
    @patch('src.audiobook_studio.export.batch_exporter._build_project_metadata')
    @patch('src.audiobook_studio.export.batch_exporter.build_m4b')
    @patch('pathlib.Path')
    def test_export_project_m4b_only(
        self, mock_path_class, mock_build_m4b, mock_metadata,
        mock_markers, mock_audio_files, mock_collect
    ):
        """Test successful export with M4B format only."""
        # Setup
        mock_session = MagicMock()
        mock_project = MagicMock()
        mock_project.id = 1
        mock_project.slug = "test-book"
        
        mock_chapter = MagicMock()
        mock_chapter.id = 1
        mock_chapter.index = 1
        
        mock_project.chapters = [mock_chapter]
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_project

        # Mock data collection
        mock_paragraph = MagicMock()
        mock_paragraph.id = 1
        mock_paragraph.order = 1
        mock_paragraph.text = "Test paragraph"
        mock_paragraph.original_text = None
        mock_paragraph.character_name = "Narrator"

        mock_chapter_data = {
            "chapter": mock_chapter,
            "audio_segments": [MagicMock(file_path="/fake/path.mp3", id=1)],
            "chapter_data": {},
            "paragraphs": [mock_paragraph]
        }
        mock_collect.return_value = mock_chapter_data
        
        # Mock file operations
        mock_audio_files.return_value = [Path("/fake/path.mp3")]
        mock_markers.return_value = []
        mock_metadata.return_value = MagicMock()

        # Mock Path behavior - use real Path but mock methods
        mock_path_instance = MagicMock()
        mock_path_instance.__truediv__.return_value = mock_path_instance
        mock_path_instance.exists.return_value = False
        mock_path_instance.mkdir = MagicMock()
        mock_path_instance.__str__.return_value = "/tmp/test/output.m4b"
        mock_path_class.return_value = mock_path_instance

        job = ExportJob(
            project_id=1,
            formats={ExportFormat.M4B},
            output_dir="/tmp/test"
        )
        
        result = export_project(1, mock_session, job)
        
        # Verify success
        assert result.progress == ExportProgress.COMPLETE
        assert result.error is None
        assert "m4b" in result.output_paths
        
        # Verify M4B was built
        assert mock_build_m4b.called


class TestExportChapter:
    """Test chapter export functionality."""

    def test_export_chapter_not_found(self):
        """Test export chapter when chapter doesn't exist."""
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None
        
        result = export_chapter(1, 999, mock_session)
        
        assert result is None

    def test_export_chapter_no_audio_data(self):
        """Test export chapter when no audio data is collected."""
        mock_session = MagicMock()
        
        with patch('src.audiobook_studio.export.batch_exporter._collect_chapter_data') as mock_collect:
            mock_collect.return_value = None
            
            result = export_chapter(1, 1, mock_session)
            
            assert result is None

    def test_export_chapter_no_audio_files_exist(self):
        """Test export chapter when audio files don't exist on filesystem."""
        mock_session = MagicMock()
        
        mock_chapter = MagicMock()
        mock_chapter.id = 1
        mock_chapter.index = 1
        
        with patch('src.audiobook_studio.export.batch_exporter._collect_chapter_data') as mock_collect, \
             patch('src.audiobook_studio.export.batch_exporter.Path') as mock_path_class:
            
            mock_collect.return_value = {
                "chapter": mock_chapter,
                "audio_segments": [MagicMock(file_path="/fake/path.mp3", id=1)]
            }
            
            # Mock Path to simulate file doesn't exist
            mock_path_instance = MagicMock()
            mock_path_instance.exists.return_value = False
            mock_path_class.return_value = mock_path_instance
            
            result = export_chapter(1, 1, mock_session)
            
            assert result is None

    @patch('src.audiobook_studio.export.batch_exporter.get_duration_sync')
    @patch('src.audiobook_studio.export.batch_exporter.Path')
    @patch('src.audiobook_studio.export.batch_exporter.build_m4b')
    def test_export_chapter_success(
        self, mock_build_m4b, mock_path_class, mock_get_duration
    ):
        """Test successful chapter export."""
        mock_session = MagicMock()

        mock_chapter = MagicMock()
        mock_chapter.id = 1
        mock_chapter.index = 1
        mock_chapter.title = "Test Chapter"

        mock_audio_segment = MagicMock()
        mock_audio_segment.file_path = "/fake/path.mp3"
        mock_audio_segment.id = 1
        mock_audio_segment.duration_ms = 5000

        with patch('src.audiobook_studio.export.batch_exporter._collect_chapter_data') as mock_collect:
            mock_collect.return_value = {
                "chapter": mock_chapter,
                "audio_segments": [mock_audio_segment]
            }

            # Mock Path behavior - return proper path for output
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

            result = export_chapter(1, 1, mock_session, "/tmp/output")

            assert result is not None
            assert "Test_Chapter.m4b" in result or "Test Chapter.m4b" in result
            assert mock_build_m4b.called

    @patch('src.audiobook_studio.export.batch_exporter.get_duration_sync')
    @patch('src.audiobook_studio.export.batch_exporter.Path')
    @patch('src.audiobook_studio.export.batch_exporter.build_m4b')
    def test_export_chapter_with_fallback_duration(
        self, mock_build_m4b, mock_path_class, mock_get_duration
    ):
        """Test chapter export with duration fallback when probing fails."""
        mock_session = MagicMock()
        
        mock_chapter = MagicMock()
        mock_chapter.id = 1
        mock_chapter.index = 1
        mock_chapter.title = "Test Chapter"
        
        mock_audio_segment = MagicMock()
        mock_audio_segment.file_path = "/fake/path.mp3"
        mock_audio_segment.id = 1
        mock_audio_segment.duration_ms = 3000  # This should be used as fallback
        
        with patch('src.audiobook_studio.export.batch_exporter._collect_chapter_data') as mock_collect:
            mock_collect.return_value = {
                "chapter": mock_chapter,
                "audio_segments": [mock_audio_segment]
            }
            
            # Mock Path behavior
            mock_path_instance = MagicMock()
            mock_path_instance.__truediv__.return_value = mock_path_instance
            mock_path_instance.exists.return_value = True
            mock_path_instance.__str__.return_value = "/fake/path.mp3"
            mock_path_class.return_value = mock_path_instance
            
            # Simulate duration probe failure
            mock_get_duration.side_effect = Exception("Probe failed")
            
            result = export_chapter(1, 1, mock_session, "/tmp/output")
            
            assert result is not None
            assert mock_build_m4b.called
            # Should have used the fallback duration (3000ms)

