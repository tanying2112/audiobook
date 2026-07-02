"""Extended tests for Batch Exporter to achieve 80%+ coverage."""

from pathlib import Path
from unittest.mock import MagicMock, patch

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

    def test_enum_all_values(self):
        """Test all enum values."""
        assert ExportFormat.M4B == "m4b"
        assert ExportFormat.SRT == "srt"
        assert ExportFormat.VTT == "vtt"
        assert ExportFormat.M4B_SRT == "m4b_srt"
        assert ExportFormat.ALL == "all"

    def test_enum_string_comparison(self):
        """Test enum string comparison."""
        assert ExportFormat.M4B.value == "m4b"
        assert ExportFormat.ALL.value == "all"


class TestExportProgress:
    """Tests for ExportProgress enum."""

    def test_enum_values(self):
        """Test all enum values."""
        assert ExportProgress.PENDING.value == "pending"
        assert ExportProgress.CONCATENATING.value == "concatenating"
        assert ExportProgress.CHAPTERING.value == "chaptering"
        assert ExportProgress.SUBTITLES.value == "subtitles"
        assert ExportProgress.DUCKING.value == "ducking"
        assert ExportProgress.COMPRESSING.value == "compressing"
        assert ExportProgress.COMPLETE.value == "complete"
        assert ExportProgress.FAILED.value == "failed"


class TestExportJobExtended:
    """Extended tests for ExportJob dataclass."""

    def test_job_with_mix_config(self):
        """Test job with mix config."""
        from src.audiobook_studio.export.audio_ducking import MixConfig

        job = ExportJob(
            project_id=1,
            mix_config=MixConfig(bgm_volume_db=-10.0),
        )
        assert job.mix_config.bgm_volume_db == -10.0

    def test_job_with_subtitle_config(self):
        """Test job with subtitle config."""
        from src.audiobook_studio.export.srt import SubtitleConfig

        job = ExportJob(
            project_id=1,
            subtitle_config=SubtitleConfig(max_chars_per_line=40),
        )
        assert job.subtitle_config.max_chars_per_line == 40

    def test_job_single_format(self):
        """Test job with single format."""
        job = ExportJob(project_id=1, formats={ExportFormat.M4B})
        assert ExportFormat.M4B in job.formats
        assert ExportFormat.SRT not in job.formats

    def test_job_all_formats(self):
        """Test job with ALL format."""
        _ = ExportJob(project_id=1, formats={ExportFormat.ALL})


class TestBuildChapterMarkers:
    """Extended tests for _build_chapter_markers."""

    def test_build_markers_multiple_chapters(self):
        """Test building markers for multiple chapters."""
        chapter_data = [
            {
                "chapter": MagicMock(title="Chapter 1", index=1),
                "audio_segments": [MagicMock(file_path="/path/seg1.mp3", duration_ms=1000)],
            },
            {
                "chapter": MagicMock(title="Chapter 2", index=2),
                "audio_segments": [MagicMock(file_path="/path/seg2.mp3", duration_ms=2000)],
            },
        ]

        with patch(
            "src.audiobook_studio.export.batch_exporter.get_duration_sync",
            return_value=1000,
        ):
            markers = _build_chapter_markers(chapter_data)

        assert len(markers) == 2
        assert markers[0].start_ms == 0
        assert markers[1].start_ms == 1000

    def test_build_markers_missing_path(self):
        """Test marker building when file path does not exist."""
        chapter_data = [
            {
                "chapter": MagicMock(title="Chapter 1", index=1),
                "audio_segments": [MagicMock(file_path="/nonexistent/seg.mp3", duration_ms=5000)],
            },
        ]

        with patch("pathlib.Path.exists", return_value=False):
            markers = _build_chapter_markers(chapter_data)

        assert markers[0].duration_ms == 5000

    def test_build_markers_no_duration_field(self):
        """Test marker building when duration_ms is None."""
        chapter_data = [
            {
                "chapter": MagicMock(title="Chapter 1", index=1),
                "audio_segments": [MagicMock(file_path="/path/seg.mp3", duration_ms=None)],
            },
        ]

        with patch("pathlib.Path.exists", return_value=False):
            markers = _build_chapter_markers(chapter_data)

        assert markers[0].duration_ms == 3000  # Fallback


class TestCollectAudioFilesExtended:
    """Extended tests for _collect_audio_files."""

    def test_collect_files_empty_segments(self):
        """Test collecting files from empty segments."""
        chapter_data = [{"audio_segments": []}]
        files = _collect_audio_files(chapter_data)
        assert files == []

    def test_collect_files_sorted_by_id(self):
        """Test that files are sorted by segment id."""
        seg3 = MagicMock(file_path="/path/seg3.mp3", id=3)
        seg1 = MagicMock(file_path="/path/seg1.mp3", id=1)
        seg2 = MagicMock(file_path="/path/seg2.mp3", id=2)

        chapter_data = [{"audio_segments": [seg3, seg1, seg2]}]

        with patch("pathlib.Path.exists", return_value=True):
            files = _collect_audio_files(chapter_data)

        assert len(files) == 3


class TestBuildSubtitleEntriesExtended:
    """Extended tests for _build_subtitle_entries."""

    def test_build_entries_with_character_name(self):
        """Test entries with character names."""
        chapter_data = [
            {
                "paragraphs": [
                    MagicMock(
                        id=1,
                        order=1,
                        text="Line",
                        original_text=None,
                        character_name="Alice",
                    ),
                ],
                "audio_segments": [
                    MagicMock(paragraph_id=1, file_path="/path/seg.mp3", duration_ms=4000),
                ],
            },
        ]

        with patch(
            "src.audiobook_studio.export.batch_exporter.get_duration_sync",
            return_value=4000,
        ):
            entries = _build_subtitle_entries(chapter_data)

        assert entries[0].speaker == "Alice"

    def test_build_entries_char_name_none(self):
        """Test entries when character_name is None."""
        chapter_data = [
            {
                "paragraphs": [
                    MagicMock(
                        id=1,
                        order=1,
                        text="Line",
                        original_text=None,
                        character_name=None,
                    ),
                ],
                "audio_segments": [
                    MagicMock(paragraph_id=1, file_path="/path/seg.mp3", duration_ms=2000),
                ],
            },
        ]

        with patch(
            "src.audiobook_studio.export.batch_exporter.get_duration_sync",
            return_value=2000,
        ):
            entries = _build_subtitle_entries(chapter_data)

        assert entries[0].speaker is None

    def test_build_entries_missing_segment_file(self):
        """Test entries when segment file path does not exist."""
        chapter_data = [
            {
                "paragraphs": [
                    MagicMock(
                        id=1,
                        order=1,
                        text="Line",
                        original_text=None,
                        character_name="Narrator",
                    ),
                ],
                "audio_segments": [
                    MagicMock(paragraph_id=1, file_path="/missing/seg.mp3", duration_ms=3000),
                ],
            },
        ]

        with patch("pathlib.Path.exists", return_value=False):
            entries = _build_subtitle_entries(chapter_data)

        assert entries[0].end_ms - entries[0].start_ms == 3000


class TestBuildProjectMetadataExtended:
    """Extended tests for _build_project_metadata."""

    def test_build_metadata_normal(self):
        """Test normal metadata building."""
        project = MagicMock(title="Test Book", author="Test Author", slug="test-book")
        chapter_data = [{"chapter": MagicMock(title="Chapter 1")}]

        metadata = _build_project_metadata(chapter_data, project)

        assert metadata.title == "Test Book"
        assert metadata.artist == "Test Author"


class TestExportProjectExtended:
    """Extended tests for export_project function."""

    def test_export_project_success_m4b_only(self, tmp_path):
        """Test successful M4B-only export."""
        mock_project = MagicMock(id=1, slug="test-book", title="Test", author="Author")
        mock_chapter = MagicMock(id=1, index=1, title="Chapter 1")
        mock_segment = MagicMock(
            id=1,
            paragraph_id=1,
            file_path=str(tmp_path / "seg.mp3"),
            duration_ms=3000,
            is_current=True,
        )

        (tmp_path / "seg.mp3").write_bytes(b"fake audio")

        mock_session = MagicMock()
        mock_session.query().filter_by().first.return_value = mock_project
        mock_project.chapters = [mock_chapter]

        with patch("src.audiobook_studio.export.batch_exporter._collect_chapter_data") as mock_collect:
            mock_collect.return_value = {
                "chapter": mock_chapter,
                "paragraphs": [],
                "audio_segments": [mock_segment],
            }
            with patch("src.audiobook_studio.export.batch_exporter._collect_audio_files") as mock_audio:
                mock_audio.return_value = [Path(tmp_path / "seg.mp3")]
                with patch("src.audiobook_studio.export.batch_exporter" "._build_chapter_markers") as mock_markers:
                    mock_markers.return_value = MagicMock()
                    with patch("src.audiobook_studio.export.batch_exporter" "._build_project_metadata") as mock_meta:
                        mock_meta.return_value = MagicMock()
                        with patch("src.audiobook_studio.export.batch_exporter" ".build_m4b"):
                            job = ExportJob(project_id=1, formats={ExportFormat.M4B})
                            result = export_project(1, mock_session, job)

        assert result.progress == ExportProgress.COMPLETE

    def test_export_project_with_bgm(self, tmp_path):
        """Test export with BGM mixing."""
        mock_project = MagicMock(id=1, slug="test-book", title="Test", author="Author")
        mock_chapter = MagicMock(id=1, index=1, title="Chapter 1")
        mock_segment = MagicMock(
            id=1,
            paragraph_id=1,
            file_path=str(tmp_path / "seg.mp3"),
            duration_ms=3000,
            is_current=True,
        )

        (tmp_path / "seg.mp3").write_bytes(b"fake audio")
        bgm_file = tmp_path / "bgm.mp3"
        bgm_file.write_bytes(b"fake bgm")

        mock_session = MagicMock()
        mock_session.query().filter_by().first.return_value = mock_project
        mock_project.chapters = [mock_chapter]

        with patch("src.audiobook_studio.export.batch_exporter._collect_chapter_data") as mock_collect:
            mock_collect.return_value = {
                "chapter": mock_chapter,
                "paragraphs": [],
                "audio_segments": [mock_segment],
            }
            with patch("src.audiobook_studio.export.batch_exporter._collect_audio_files") as mock_audio:
                mock_audio.return_value = [Path(tmp_path / "seg.mp3")]
                with patch("src.audiobook_studio.export.batch_exporter" "._build_chapter_markers") as mock_markers:
                    mock_markers.return_value = MagicMock()
                    with patch("src.audiobook_studio.export.batch_exporter" "._build_project_metadata") as mock_meta:
                        mock_meta.return_value = MagicMock()
                        with patch("src.audiobook_studio.export.batch_exporter" ".build_m4b"):
                            with patch("src.audiobook_studio.export.batch_exporter" ".mix_with_ducking"):
                                with patch("subprocess.run"):
                                    job = ExportJob(
                                        project_id=1,
                                        formats={ExportFormat.M4B},
                                        bgm_path=str(bgm_file),
                                    )
                                    result = export_project(1, mock_session, job)

        assert result.progress == ExportProgress.COMPLETE

    def test_export_project_srt_only(self, tmp_path):
        """Test SRT-only export."""
        mock_project = MagicMock(id=1, slug="test-book", title="Test", author="Author")
        mock_chapter = MagicMock(id=1, index=1, title="Chapter 1")
        mock_segment = MagicMock(
            id=1,
            paragraph_id=1,
            file_path=str(tmp_path / "seg.mp3"),
            duration_ms=3000,
            is_current=True,
        )
        mock_paragraph = MagicMock(id=1, order=1, text="Test", original_text=None, character_name=None)

        (tmp_path / "seg.mp3").write_bytes(b"fake audio")

        mock_session = MagicMock()
        mock_session.query().filter_by().first.return_value = mock_project
        mock_project.chapters = [mock_chapter]

        with patch("src.audiobook_studio.export.batch_exporter._collect_chapter_data") as mock_collect:
            mock_collect.return_value = {
                "chapter": mock_chapter,
                "paragraphs": [mock_paragraph],
                "audio_segments": [mock_segment],
            }
            with patch("src.audiobook_studio.export.batch_exporter._collect_audio_files") as mock_audio:
                mock_audio.return_value = []
                with patch("src.audiobook_studio.export.batch_exporter" "._build_subtitle_entries") as mock_entries:
                    mock_entries.return_value = MagicMock()
                    with patch("src.audiobook_studio.export.batch_exporter" ".generate_srt"):
                        job = ExportJob(project_id=1, formats={ExportFormat.SRT})
                        result = export_project(1, mock_session, job)

        assert result.progress == ExportProgress.COMPLETE

    def test_export_project_exception_handling(self, tmp_path):
        """Test exception handling in export_project."""
        mock_project = MagicMock(id=1)
        mock_session = MagicMock()
        mock_session.query().filter_by().first.return_value = mock_project

        with patch("src.audiobook_studio.export.batch_exporter._collect_chapter_data") as mock_collect:
            mock_collect.side_effect = RuntimeError("Unexpected error")
            job = ExportJob(project_id=1)
            result = export_project(1, mock_session, job)

        assert result.progress == ExportProgress.FAILED
        assert result.error is not None


class TestExportChapterExtended:
    """Extended tests for export_chapter function."""

    def test_export_chapter_with_audio(self, tmp_path):
        """Test successful chapter export."""
        mock_chapter = MagicMock(id=1, index=1, title="Test Chapter")
        mock_segment = MagicMock(id=1, file_path=str(tmp_path / "seg.mp3"), duration_ms=5000, is_current=True)
        (tmp_path / "seg.mp3").write_bytes(b"fake audio")

        mock_session = MagicMock()
        mock_session.query().filter_by().first.return_value = MagicMock()

        with patch("src.audiobook_studio.export.batch_exporter._collect_chapter_data") as mock_collect:
            mock_collect.return_value = {
                "chapter": mock_chapter,
                "paragraphs": [],
                "audio_segments": [mock_segment],
            }
            with patch("src.audiobook_studio.export.batch_exporter.build_m4b") as mock_build:
                mock_build.return_value = MagicMock()
                result = export_chapter(1, 1, mock_session, output_dir=str(tmp_path / "out"))

        assert result is not None

    def test_export_chapter_all_audio_missing(self, tmp_path):
        """Test chapter export when all audio files are missing."""
        mock_chapter = MagicMock(id=1, index=1, title="Test Chapter")
        mock_segment = MagicMock(
            id=1,
            file_path=str(tmp_path / "missing.mp3"),
            duration_ms=5000,
            is_current=True,
        )

        mock_session = MagicMock()
        mock_session.query().filter_by().first.return_value = mock_chapter

        with patch("src.audiobook_studio.export.batch_exporter._collect_chapter_data") as mock_collect:
            mock_collect.return_value = {
                "chapter": mock_chapter,
                "paragraphs": [],
                "audio_segments": [mock_segment],
            }
            result = export_chapter(1, 1, mock_session, output_dir=str(tmp_path / "out"))

        assert result is None


class TestExportJobProgress:
    """Tests for ExportJob progress tracking."""

    def test_progress_states(self):
        """Test all progress states."""
        for state in [
            ExportProgress.CONCATENATING,
            ExportProgress.SUBTITLES,
            ExportProgress.DUCKING,
        ]:
            job = ExportJob(project_id=1)
            job.progress = state
            assert job.progress == state


class TestExportJobCoverImage:
    """Tests for cover image handling."""

    def test_job_with_cover_image(self, tmp_path):
        """Test job with cover image."""
        cover = tmp_path / "cover.jpg"
        cover.write_bytes(b"fake image")

        job = ExportJob(
            project_id=1,
            include_cover=True,
            cover_image=str(cover),
        )

        assert job.include_cover is True
        assert job.cover_image == str(cover)
