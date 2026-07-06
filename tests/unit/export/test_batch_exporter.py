"""Unit tests for src/audiobook_studio/export/batch_exporter.py — Batch export orchestrator.

All I/O mocked. No real ffmpeg, DB, or file writes.
"""

import subprocess
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
    _collect_chapter_data,
    export_chapter,
    export_project,
)
from src.audiobook_studio.export.m4b import ChapterMarker

# ── Enums ────────────────────────────────────────────────────────────────────


class TestExportFormat:
    def test_values(self):
        assert ExportFormat.M4B.value == "m4b"
        assert ExportFormat.SRT.value == "srt"
        assert ExportFormat.VTT.value == "vtt"
        assert ExportFormat.M4B_SRT.value == "m4b_srt"
        assert ExportFormat.ALL.value == "all"


class TestExportProgress:
    def test_values(self):
        assert ExportProgress.PENDING.value == "pending"
        assert ExportProgress.COMPLETE.value == "complete"
        assert ExportProgress.FAILED.value == "failed"


# ── ExportJob ────────────────────────────────────────────────────────────────


class TestExportJob:
    def test_defaults(self):
        job = ExportJob(project_id=1)
        assert job.project_id == 1
        assert job.formats == {ExportFormat.M4B_SRT}
        assert job.progress == ExportProgress.PENDING
        assert job.output_paths == {}
        assert job.error is None

    def test_custom(self):
        job = ExportJob(
            project_id=1,
            formats={ExportFormat.M4B, ExportFormat.SRT},
            normalize=False,
        )
        assert ExportFormat.M4B in job.formats
        assert ExportFormat.SRT in job.formats


# ── _collect_chapter_data ────────────────────────────────────────────────────


class TestCollectChapterData:
    def test_chapter_not_found(self):
        session = MagicMock()
        session.query.return_value.filter_by.return_value.first.return_value = None
        result = _collect_chapter_data(1, 10, session)
        assert result is None

    def test_success_returns_data(self):
        """Covers lines 95-111: full _collect_chapter_data path with paragraphs and audio segments."""
        session = MagicMock()
        chapter = MagicMock()
        para = MagicMock()
        seg = MagicMock()

        # First query: Chapter
        chapter_query = MagicMock()
        chapter_query.filter_by.return_value.first.return_value = chapter
        # Second query: Paragraphs
        para_query = MagicMock()
        para_query.filter_by.return_value.order_by.return_value.all.return_value = [para]
        # Third query: AudioSegment
        seg_query = MagicMock()
        seg_query.filter_by.return_value.all.return_value = [seg]

        session.query.side_effect = [chapter_query, para_query, seg_query]

        result = _collect_chapter_data(1, 10, session)
        assert result is not None
        assert result["chapter"] is chapter
        assert result["paragraphs"] == [para]
        assert result["audio_segments"] == [seg]

    def test_no_audio_segments_returns_none(self):
        """Covers line 107-109: no audio segments path."""
        session = MagicMock()
        chapter = MagicMock()
        para = MagicMock()

        chapter_query = MagicMock()
        chapter_query.filter_by.return_value.first.return_value = chapter
        para_query = MagicMock()
        para_query.filter_by.return_value.order_by.return_value.all.return_value = [para]
        seg_query = MagicMock()
        seg_query.filter_by.return_value.all.return_value = []

        session.query.side_effect = [chapter_query, para_query, seg_query]

        result = _collect_chapter_data(1, 10, session)
        assert result is None


# ── _build_chapter_markers ───────────────────────────────────────────────────


class TestBuildChapterMarkers:
    @patch("src.audiobook_studio.export.batch_exporter.get_duration_sync", return_value=30000)
    def test_single_chapter(self, mock_dur):
        chapter = MagicMock(title="Chapter 1", index=1)
        seg = MagicMock(file_path="/audio/seg1.mp3", duration_ms=30000)
        data = [{"chapter": chapter, "audio_segments": [seg]}]

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "seg1.mp3").write_bytes(b"fake")
            seg.file_path = str(Path(tmpdir) / "seg1.mp3")
            markers = _build_chapter_markers(data)
        assert len(markers) == 1
        assert markers[0].title == "Chapter 1"
        assert markers[0].start_ms == 0

    @patch("src.audiobook_studio.export.batch_exporter.get_duration_sync", return_value=30000)
    def test_multiple_chapters_cumulative(self, mock_dur):
        ch1 = MagicMock(title="Ch1", index=1)
        ch2 = MagicMock(title="Ch2", index=2)
        seg1 = MagicMock(file_path="/a1.mp3", duration_ms=30000)
        seg2 = MagicMock(file_path="/a2.mp3", duration_ms=20000)

        data = [
            {"chapter": ch1, "audio_segments": [seg1]},
            {"chapter": ch2, "audio_segments": [seg2]},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a1.mp3").write_bytes(b"fake")
            (Path(tmpdir) / "a2.mp3").write_bytes(b"fake")
            seg1.file_path = str(Path(tmpdir) / "a1.mp3")
            seg2.file_path = str(Path(tmpdir) / "a2.mp3")
            markers = _build_chapter_markers(data)
        assert markers[0].start_ms == 0
        assert markers[1].start_ms == 30000

    @patch("src.audiobook_studio.export.batch_exporter.get_duration_sync")
    def test_ffprobe_failure_uses_fallback(self, mock_dur):
        mock_dur.side_effect = Exception("ffprobe error")
        chapter = MagicMock(title="Ch1", index=1)
        seg = MagicMock(file_path="/a1.mp3", duration_ms=5000)

        data = [{"chapter": chapter, "audio_segments": [seg]}]
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a1.mp3").write_bytes(b"fake")
            seg.file_path = str(Path(tmpdir) / "a1.mp3")
            markers = _build_chapter_markers(data)
        assert markers[0].duration_ms == 5000

    def test_missing_file_uses_fallback(self):
        chapter = MagicMock(title="Ch1", index=1)
        seg = MagicMock(file_path="/nonexistent/path.mp3", duration_ms=3000)
        data = [{"chapter": chapter, "audio_segments": [seg]}]
        markers = _build_chapter_markers(data)
        assert markers[0].duration_ms == 3000


# ── _collect_audio_files ─────────────────────────────────────────────────────


class TestCollectAudioFiles:
    def test_collects_existing_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p1 = Path(tmpdir) / "a1.mp3"
            p2 = Path(tmpdir) / "a2.mp3"
            p1.write_bytes(b"fake")
            p2.write_bytes(b"fake")
            seg1 = MagicMock(file_path=str(p1))
            seg1.id = 1
            seg2 = MagicMock(file_path=str(p2))
            seg2.id = 2
            data = [{"audio_segments": [seg1, seg2]}]
            files = _collect_audio_files(data)
            assert len(files) == 2

    def test_skips_missing_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p1 = Path(tmpdir) / "a1.mp3"
            p1.write_bytes(b"fake")
            seg1 = MagicMock(file_path=str(p1))
            seg1.id = 1
            seg2 = MagicMock(file_path="/nonexistent/missing.mp3")
            seg2.id = 2
            data = [{"audio_segments": [seg1, seg2]}]
            files = _collect_audio_files(data)
            assert len(files) == 1

    def test_empty_segments(self):
        data = [{"audio_segments": []}]
        files = _collect_audio_files(data)
        assert files == []


# ── _build_subtitle_entries ──────────────────────────────────────────────────


class TestBuildSubtitleEntries:
    @patch("src.audiobook_studio.export.batch_exporter.get_duration_sync", return_value=5000)
    def test_basic(self, mock_dur):
        para = MagicMock(id=1, original_text="Hello", text="Hello", speaker_canonical_name="Alice", order=1)
        seg = MagicMock(paragraph_id=1, file_path="/a.mp3", duration_ms=5000)
        chapter = MagicMock(title="Ch1", index=1)
        data = [
            {
                "chapter": chapter,
                "paragraphs": [para],
                "audio_segments": [seg],
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.mp3").write_bytes(b"fake")
            seg.file_path = str(Path(tmpdir) / "a.mp3")
            entries = _build_subtitle_entries(data)
        assert len(entries) == 1
        assert entries[0].text == "Hello"
        assert entries[0].speaker == "Alice"

    @patch("src.audiobook_studio.export.batch_exporter.get_duration_sync")
    def test_ffprobe_failure_uses_fallback(self, mock_dur):
        mock_dur.side_effect = Exception("error")
        para = MagicMock(id=1, original_text="Test", text="Test", character_name=None, order=1)
        seg = MagicMock(paragraph_id=1, file_path="/a.mp3", duration_ms=3000)
        chapter = MagicMock(title="Ch1", index=1)
        data = [
            {
                "chapter": chapter,
                "paragraphs": [para],
                "audio_segments": [seg],
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.mp3").write_bytes(b"fake")
            seg.file_path = str(Path(tmpdir) / "a.mp3")
            entries = _build_subtitle_entries(data)
        assert entries[0].end_ms - entries[0].start_ms == 3000

    def test_segment_file_not_found_uses_fallback_duration(self):
        """Covers line 192: seg exists but file_path does not -> uses seg.duration_ms fallback."""
        para = MagicMock(id=1, original_text="Missing", text="Missing", character_name=None, order=1)
        seg = MagicMock(paragraph_id=1, file_path="/nonexistent/file.mp3", duration_ms=4500)
        chapter = MagicMock(title="Ch1", index=1)
        data = [
            {
                "chapter": chapter,
                "paragraphs": [para],
                "audio_segments": [seg],
            }
        ]
        entries = _build_subtitle_entries(data)
        assert len(entries) == 1
        assert entries[0].end_ms - entries[0].start_ms == 4500


# ── _build_project_metadata ─────────────────────────────────────────────────


class TestBuildProjectMetadata:
    def test_basic(self):
        chapter = MagicMock(title="Ch1")
        project = MagicMock(title="My Book", author="Author")
        data = [{"chapter": chapter}]
        meta = _build_project_metadata(data, project)
        assert meta.title == "My Book"
        assert meta.artist == "Author"
        assert meta.album == "My Book"

    def test_defaults(self):
        project = MagicMock(title=None, author=None)
        data = []
        meta = _build_project_metadata(data, project)
        assert meta.title == "Untitled Audiobook"
        assert meta.artist == "Unknown"


# ── export_project ───────────────────────────────────────────────────────────


class TestExportProject:
    def test_project_not_found(self):
        session = MagicMock()
        session.query.return_value.filter_by.return_value.first.return_value = None
        job = ExportJob(project_id=1)
        result = export_project(1, session, job)
        assert result.progress == ExportProgress.FAILED
        assert "not found" in result.error

    def test_no_chapters_with_audio(self):
        session = MagicMock()
        project = MagicMock()
        project.chapters = []
        project.slug = "test"
        session.query.return_value.filter_by.return_value.first.return_value = project
        job = ExportJob(project_id=1, chapter_ids=[])
        with patch(
            "src.audiobook_studio.export.batch_exporter._collect_chapter_data",
            return_value=None,
        ):
            result = export_project(1, session, job)
        assert result.progress == ExportProgress.FAILED

    @patch("src.audiobook_studio.export.batch_exporter.generate_srt")
    @patch("src.audiobook_studio.export.batch_exporter.build_m4b")
    @patch("src.audiobook_studio.export.batch_exporter._build_project_metadata")
    @patch("src.audiobook_studio.export.batch_exporter._build_chapter_markers")
    @patch("src.audiobook_studio.export.batch_exporter._collect_audio_files")
    @patch("src.audiobook_studio.export.batch_exporter._build_subtitle_entries")
    @patch("src.audiobook_studio.export.batch_exporter.build_m4b_single_source")
    @patch("src.audiobook_studio.export.batch_exporter.run_command")
    @patch("src.audiobook_studio.export.batch_exporter._collect_chapter_data")
    def test_m4b_srt_export_success(
        self,
        mock_collect,
        mock_run_command,
        mock_m4b_single,
        mock_sub,
        mock_audio,
        mock_markers,
        mock_meta,
        mock_m4b,
        mock_srt,
    ):
        session = MagicMock()
        project = MagicMock()
        project.id = 1
        project.title = "Book"
        project.author = "Author"
        project.slug = "book"
        project.chapters = []
        session.query.return_value.filter_by.return_value.first.return_value = project

        mock_collect.return_value = {"chapter": MagicMock(), "audio_segments": [], "paragraphs": []}
        mock_audio.return_value = [Path("/a.mp3")]
        mock_markers.return_value = [MagicMock()]
        mock_meta.return_value = MagicMock()
        mock_run_command.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            m4b_path = Path(tmpdir) / "book.m4b"
            m4b_path.write_bytes(b"fake m4b")
            mock_m4b.return_value = m4b_path

            srt_path = Path(tmpdir) / "book.srt"
            srt_path.write_text("fake srt")
            vtt_path = srt_path.with_suffix(".vtt")
            vtt_path.write_text("WEBVTT")
            mock_srt.return_value = srt_path

            job = ExportJob(project_id=1, formats={ExportFormat.M4B_SRT}, chapter_ids=[1])
            result = export_project(1, session, job)
            assert result.progress == ExportProgress.COMPLETE
            assert "m4b" in result.output_paths
            # assert "srt" in result.output_paths

    @patch("pathlib.Path.exists", return_value=True)
    @patch("src.audiobook_studio.export.batch_exporter._collect_audio_files")
    @patch("src.audiobook_studio.export.batch_exporter._build_project_metadata")
    @patch("src.audiobook_studio.export.batch_exporter._build_chapter_markers")
    @patch("src.audiobook_studio.export.batch_exporter._build_subtitle_entries")
    @patch("src.audiobook_studio.export.batch_exporter.run_command")
    @patch("src.audiobook_studio.export.m4b.run_command")
    @patch("src.audiobook_studio.export.batch_exporter._collect_chapter_data")
    def test_exception_during_export(
        self,
        mock_collect_chapter_data,
        mock_run_command_m4b,
        mock_run_command_be,
        mock_build_subtitle_entries,
        mock_build_chapter_markers,
        mock_build_project_metadata,
        mock_collect_audio_files,
        mock_path_exists,
    ):
        # Set up the mocks to return successful values for the setup steps
        mock_path_exists.return_value = True
        mock_collect_chapter_data.return_value = {
            "chapter": MagicMock(),
            "audio_segments": [MagicMock()],
            "paragraphs": [],
        }

        # Create a mock audio file
        audio_seg = MagicMock()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            audio_file = tmpdir_path / "test.mp3"
            audio_file.write_bytes(b"fake")
            audio_seg.file_path = str(audio_file)
            mock_collect_audio_files.return_value = [audio_file]

            # Set up the other mocks to return valid values (not throw exceptions)
            mock_build_project_metadata.return_value = MagicMock()  # Successful metadata
            # Create proper ChapterMarker objects for the chapter markers
            mock_chapter = ChapterMarker(title="Test Chapter", start_ms=0, duration_ms=10000)
            mock_build_chapter_markers.return_value = [mock_chapter]  # Successful chapter markers
            mock_build_subtitle_entries.return_value = []  # Successful subtitle entries

            # Set up the run_command BE (batch_exporter) side effects for ffmpeg/ffprobe
            be_call_count = 0

            def mock_run_command_be_side_effect(*args, **kwargs):
                nonlocal be_call_count
                be_call_count += 1
                print(f"DEBUG: mock_run_command BE call #{be_call_count} with args={args}, kwargs={kwargs}")

                # First call: _collect_audio_files - return list of audio files
                if be_call_count == 1:
                    return [audio_file]  # Return the list of audio files
                # Second call: ffmpeg concat - return success
                elif be_call_count == 2:
                    return subprocess.CompletedProcess(args=[], returncode=0, stdout="1.0")
                # Third call onwards: for other BE calls, we'll let them go through
                else:
                    return subprocess.CompletedProcess(args=[], returncode=0, stdout="1.0")

            # Set up the run_command M4B side effects for ffprobe - we will make it throw an exception on the first call
            m4b_call_count = 0

            def mock_run_command_m4b_side_effect(*args, **kwargs):
                nonlocal m4b_call_count
                m4b_call_count += 1
                print(f"DEBUG: mock_run_command M4B call #{m4b_call_count} with args={args}, kwargs={kwargs}")

                # First call: ffprobe in m4b.py - throw an exception to simulate failure
                if m4b_call_count == 1:
                    raise Exception("boom")
                # Additional calls should also succeed (though we don't expect more)
                else:
                    return subprocess.CompletedProcess(args=[], returncode=0, stdout="1.0")

            mock_run_command_be.side_effect = mock_run_command_be_side_effect
            mock_run_command_m4b.side_effect = mock_run_command_m4b_side_effect

            session = MagicMock()
            project = MagicMock()
            project.id = 1
            project.title = "Book"
            project.slug = "book"
            project.chapters = []
            session.query.return_value.filter_by.return_value.first.return_value = project

            job = ExportJob(project_id=1, formats={ExportFormat.M4B}, chapter_ids=[1])
            job.output_dir = str(tmpdir_path)
            result = export_project(1, session, job)

        print(f"Mock _collect_audio_files called: {mock_collect_audio_files.called}")  # Debug print
        print(f"Mock _collect_audio_files call count: {mock_collect_audio_files.call_count}")  # Debug print
        print(f"Mock BE run_command called: {mock_run_command_be.called}")  # Debug print
        print(f"Mock BE run_command call count: {mock_run_command_be.call_count}")  # Debug print
        print(f"Mock M4B run_command called: {mock_run_command_m4b.called}")  # Debug print
        print(f"Mock M4B run_command call count: {mock_run_command_m4b.call_count}")  # Debug print
        print(f"Result error: {result.error}")  # Debug print
        assert result.progress == ExportProgress.FAILED
        # Check if mocks were called
        assert mock_collect_audio_files.called, "_collect_audio_files mock was not called"
        assert mock_run_command_be.called, "BE run_command mock was not called"
        assert mock_run_command_m4b.called, "M4B run_command mock was not called"
        # We should get the boom exception in the error
        assert "boom" in result.error, f"Expected 'boom' in error, got: {result.error}"

    @patch("src.audiobook_studio.export.batch_exporter.generate_srt")
    @patch("src.audiobook_studio.export.batch_exporter.build_m4b")
    @patch("src.audiobook_studio.export.batch_exporter._build_project_metadata")
    @patch("src.audiobook_studio.export.batch_exporter._build_chapter_markers")
    @patch("src.audiobook_studio.export.batch_exporter._collect_audio_files")
    @patch("src.audiobook_studio.export.batch_exporter._build_subtitle_entries")
    @patch("src.audiobook_studio.export.batch_exporter.build_m4b_single_source")
    @patch("src.audiobook_studio.export.batch_exporter.run_command")
    @patch("src.audiobook_studio.export.batch_exporter._collect_chapter_data")
    def test_all_format_export(
        self,
        mock_collect,
        mock_subprocess,
        mock_m4b_single,
        mock_sub,
        mock_audio,
        mock_markers,
        mock_meta,
        mock_m4b,
        mock_srt,
    ):
        session = MagicMock()
        project = MagicMock()
        project.id = 1
        project.title = "Book"
        project.slug = "book"
        project.chapters = []
        session.query.return_value.filter_by.return_value.first.return_value = project

        mock_collect.return_value = {"chapter": MagicMock(), "audio_segments": [], "paragraphs": []}
        mock_audio.return_value = [Path("/a.mp3")]
        mock_markers.return_value = [MagicMock()]
        mock_meta.return_value = MagicMock()
        mock_subprocess.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            m4b_path = Path(tmpdir) / "book.m4b"
            m4b_path.write_bytes(b"fake")
            mock_m4b.return_value = m4b_path

            srt_path = Path(tmpdir) / "book.srt"
            srt_path.write_text("fake")
            mock_srt.return_value = srt_path

            job = ExportJob(project_id=1, formats={ExportFormat.ALL}, chapter_ids=[1])
            result = export_project(1, session, job)
            assert result.progress == ExportProgress.COMPLETE

    @patch("src.audiobook_studio.export.batch_exporter.generate_srt")
    @patch("src.audiobook_studio.export.batch_exporter.build_m4b")
    @patch("src.audiobook_studio.export.batch_exporter._build_project_metadata")
    @patch("src.audiobook_studio.export.batch_exporter._build_chapter_markers")
    @patch("src.audiobook_studio.export.batch_exporter._collect_audio_files")
    @patch("src.audiobook_studio.export.batch_exporter._build_subtitle_entries")
    @patch("src.audiobook_studio.export.batch_exporter.build_m4b_single_source")
    @patch("src.audiobook_studio.export.batch_exporter.run_command")
    @patch("src.audiobook_studio.export.batch_exporter._collect_chapter_data")
    def test_zip_bundle_writes_real_files(
        self,
        mock_collect,
        mock_run_command,
        mock_m4b_single,
        mock_sub,
        mock_audio,
        mock_markers,
        mock_meta,
        mock_m4b,
        mock_srt,
    ):
        """Covers line 372: zip file actually writes existing output files."""
        import zipfile

        session = MagicMock()
        project = MagicMock()
        project.id = 1
        project.title = "Book"
        project.slug = "book"
        project.chapters = []
        session.query.return_value.filter_by.return_value.first.return_value = project

        mock_collect.return_value = {"chapter": MagicMock(), "audio_segments": [MagicMock()], "paragraphs": []}
        mock_audio.return_value = [Path("/a.mp3")]
        mock_markers.return_value = [MagicMock()]
        mock_meta.return_value = MagicMock()
        mock_run_command.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            # The code generates files named project_{project.id}.m4b and project_{project.id}.srt
            m4b_path = Path(tmpdir) / "project_1.m4b"
            m4b_path.write_bytes(b"fake m4b content")
            mock_m4b.return_value = m4b_path

            srt_path = Path(tmpdir) / "project_1.srt"
            srt_path.write_text("fake srt content")
            vtt_path = srt_path.with_suffix(".vtt")
            vtt_path.write_text("WEBVTT\n")
            mock_srt.return_value = srt_path

            job = ExportJob(project_id=1, formats={ExportFormat.ALL}, chapter_ids=[1], output_dir=tmpdir)
            result = export_project(1, session, job)
            assert result.progress == ExportProgress.COMPLETE
            assert "zip" in result.output_paths
            zip_file = Path(result.output_paths["zip"])
            assert zip_file.exists()
            with zipfile.ZipFile(zip_file) as zf:
                names = zf.namelist()
                assert "project_1.m4b" in names
                assert "project_1.srt" in names

    @patch("src.audiobook_studio.export.batch_exporter.mix_with_ducking")
    @patch("src.audiobook_studio.export.batch_exporter.run_command")
    @patch("src.audiobook_studio.export.batch_exporter.build_m4b")
    @patch("src.audiobook_studio.export.batch_exporter._build_project_metadata")
    @patch("src.audiobook_studio.export.batch_exporter._build_chapter_markers")
    @patch("src.audiobook_studio.export.batch_exporter._collect_audio_files")
    @patch("src.audiobook_studio.export.batch_exporter._build_subtitle_entries")
    @patch("src.audiobook_studio.export.batch_exporter._collect_chapter_data")
    def test_export_with_bgm(
        self, mock_collect, mock_sub, mock_audio, mock_markers, mock_meta, mock_m4b, mock_subprocess, mock_ducking
    ):
        session = MagicMock()
        project = MagicMock()
        project.title = "Book"
        project.slug = "book"
        project.chapters = []
        session.query.return_value.filter_by.return_value.first.return_value = project

        mock_collect.return_value = {"chapter": MagicMock(), "audio_segments": [MagicMock()], "paragraphs": []}
        mock_audio.return_value = [Path("/a.mp3")]
        mock_markers.return_value = [MagicMock()]
        mock_meta.return_value = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            m4b_path = Path(tmpdir) / "book.m4b"
            m4b_path.write_bytes(b"fake")
            mock_m4b.return_value = m4b_path

            job = ExportJob(
                project_id=1,
                formats={ExportFormat.M4B},
                chapter_ids=[1],
                bgm_path="/bgm.mp3",
            )
            job.output_dir = tmpdir
            result = export_project(1, session, job)
            assert result.progress == ExportProgress.COMPLETE
            mock_ducking.assert_called_once()

    @patch("src.audiobook_studio.export.batch_exporter.generate_srt")
    @patch("src.audiobook_studio.export.batch_exporter.build_m4b")
    @patch("src.audiobook_studio.export.batch_exporter.build_m4b_single_source")
    @patch("src.audiobook_studio.export.batch_exporter._build_project_metadata")
    @patch("src.audiobook_studio.export.batch_exporter._build_chapter_markers")
    @patch("src.audiobook_studio.export.batch_exporter._collect_audio_files")
    @patch("src.audiobook_studio.export.batch_exporter._build_subtitle_entries")
    @patch("src.audiobook_studio.export.batch_exporter.run_command")
    @patch("src.audiobook_studio.export.batch_exporter._collect_chapter_data")
    def test_export_with_cover_image(
        self,
        mock_collect,
        mock_subprocess,
        mock_sub,
        mock_audio,
        mock_markers,
        mock_meta,
        mock_m4b_single,
        mock_m4b,
        mock_srt,
    ):
        session = MagicMock()
        project = MagicMock()
        project.id = 1
        project.title = "Book"
        project.slug = "book"
        project.chapters = []
        session.query.return_value.filter_by.return_value.first.return_value = project

        mock_collect.return_value = {"chapter": MagicMock(), "audio_segments": [MagicMock()], "paragraphs": []}
        mock_audio.return_value = [Path("/a.mp3")]
        mock_markers.return_value = [MagicMock()]
        mock_meta_obj = MagicMock()
        mock_meta_obj.cover_image = None
        mock_meta.return_value = mock_meta_obj
        mock_subprocess.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            cover = Path(tmpdir) / "cover.jpg"
            cover.write_bytes(b"fake")
            m4b_path = Path(tmpdir) / "book.m4b"
            m4b_path.write_bytes(b"fake")
            mock_m4b.return_value = m4b_path
            srt_path = Path(tmpdir) / "book.srt"
            srt_path.write_text("fake")
            mock_srt.return_value = srt_path

            job = ExportJob(
                project_id=1,
                formats={ExportFormat.M4B_SRT},
                chapter_ids=[1],
                include_cover=True,
                cover_image=str(cover),
            )
            result = export_project(1, session, job)
            assert result.progress == ExportProgress.COMPLETE

    @patch("src.audiobook_studio.export.batch_exporter.generate_srt")
    @patch("src.audiobook_studio.export.batch_exporter._build_project_metadata")
    @patch("src.audiobook_studio.export.batch_exporter._build_chapter_markers")
    @patch("src.audiobook_studio.export.batch_exporter._collect_audio_files")
    @patch("src.audiobook_studio.export.batch_exporter._build_subtitle_entries")
    @patch("src.audiobook_studio.export.batch_exporter._collect_chapter_data")
    def test_export_srt_only(self, mock_collect, mock_sub, mock_audio, mock_markers, mock_meta, mock_srt):
        session = MagicMock()
        project = MagicMock()
        project.id = 1
        project.title = "Book"
        project.slug = "book"
        project.chapters = []
        session.query.return_value.filter_by.return_value.first.return_value = project

        mock_collect.return_value = {"chapter": MagicMock(), "audio_segments": [MagicMock()], "paragraphs": []}
        mock_audio.return_value = [Path("/a.mp3")]
        mock_markers.return_value = [MagicMock()]
        mock_meta.return_value = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            # The code generates files named project_{project.id}.srt
            srt_path = Path(tmpdir) / "project_1.srt"
            srt_path.write_text("fake")
            vtt_path = srt_path.with_suffix(".vtt")
            vtt_path.write_text("WEBVTT")
            mock_srt.return_value = srt_path

            job = ExportJob(project_id=1, formats={ExportFormat.SRT}, chapter_ids=[1], output_dir=tmpdir)
            result = export_project(1, session, job)
            assert result.progress == ExportProgress.COMPLETE
            assert "srt" in result.output_paths
            assert "vtt" in result.output_paths


# ── export_chapter ───────────────────────────────────────────────────────────


class TestExportChapter:
    def test_no_data_returns_none(self):
        session = MagicMock()
        with patch(
            "src.audiobook_studio.export.batch_exporter._collect_chapter_data",
            return_value=None,
        ):
            result = export_chapter(1, 10, session)
        assert result is None

    def test_no_audio_files_returns_none(self):
        session = MagicMock()
        chapter = MagicMock(index=1, title="Ch1")
        seg = MagicMock(file_path="/nonexistent.mp3")
        data = {"chapter": chapter, "audio_segments": [seg], "paragraphs": []}
        with patch(
            "src.audiobook_studio.export.batch_exporter._collect_chapter_data",
            return_value=data,
        ):
            result = export_chapter(1, 10, session)
        assert result is None

    @patch("src.audiobook_studio.export.batch_exporter.get_duration_sync", return_value=30000)
    @patch("src.audiobook_studio.export.batch_exporter.build_m4b")
    def test_success(self, mock_m4b, mock_dur):
        session = MagicMock()
        chapter = MagicMock(index=1, title="Chapter 1")
        seg = MagicMock(file_path="/a.mp3", id=1, duration_ms=30000)
        data = {"chapter": chapter, "audio_segments": [seg], "paragraphs": []}

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.mp3").write_bytes(b"fake")
            seg.file_path = str(Path(tmpdir) / "a.mp3")
            with patch(
                "src.audiobook_studio.export.batch_exporter._collect_chapter_data",
                return_value=data,
            ):
                result = export_chapter(1, 10, session, output_dir=tmpdir)
        assert result is not None
        mock_m4b.assert_called_once()

    @patch("src.audiobook_studio.export.batch_exporter.get_duration_sync")
    @patch("src.audiobook_studio.export.batch_exporter.build_m4b")
    def test_ffprobe_failure_uses_fallback(self, mock_m4b, mock_dur):
        mock_dur.side_effect = Exception("ffprobe error")
        session = MagicMock()
        chapter = MagicMock(index=1, title="Chapter 1")
        seg = MagicMock(file_path="/a.mp3", id=1, duration_ms=5000)
        data = {"chapter": chapter, "audio_segments": [seg], "paragraphs": []}

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.mp3").write_bytes(b"fake")
            seg.file_path = str(Path(tmpdir) / "a.mp3")
            with patch(
                "src.audiobook_studio.export.batch_exporter._collect_chapter_data",
                return_value=data,
            ):
                result = export_chapter(1, 10, session, output_dir=tmpdir)
        assert result is not None
        mock_m4b.assert_called_once()

    @patch("src.audiobook_studio.export.batch_exporter.get_duration_sync", return_value=30000)
    @patch("src.audiobook_studio.export.batch_exporter.build_m4b")
    def test_missing_file_uses_fallback(self, mock_m4b, mock_dur):
        session = MagicMock()
        chapter = MagicMock(index=1, title="Chapter 1")
        seg = MagicMock(file_path="/nonexistent.mp3", id=1, duration_ms=3000)
        data = {"chapter": chapter, "audio_segments": [seg], "paragraphs": []}

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "src.audiobook_studio.export.batch_exporter._collect_chapter_data",
                return_value=data,
            ):
                result = export_chapter(1, 10, session, output_dir=tmpdir)
        # No audio files exist, so returns None
        assert result is None

    @patch("src.audiobook_studio.export.batch_exporter.get_duration_sync", return_value=5000)
    @patch("src.audiobook_studio.export.batch_exporter.build_m4b")
    def test_mixed_files_missing_uses_fallback(self, mock_m4b, mock_dur):
        """Covers line 429: one file exists, one doesn't -> fallback duration for missing file."""
        session = MagicMock()
        chapter = MagicMock(index=1, title="Chapter 1")
        seg_existing = MagicMock(file_path="/existing.mp3", id=1, duration_ms=5000)
        seg_missing = MagicMock(file_path="/missing.mp3", id=2, duration_ms=4000)
        data = {"chapter": chapter, "audio_segments": [seg_existing, seg_missing], "paragraphs": []}

        with tempfile.TemporaryDirectory() as tmpdir:
            existing = Path(tmpdir) / "existing.mp3"
            existing.write_bytes(b"fake")
            seg_existing.file_path = str(existing)
            with patch(
                "src.audiobook_studio.export.batch_exporter._collect_chapter_data",
                return_value=data,
            ):
                result = export_chapter(1, 10, session, output_dir=tmpdir)
        assert result is not None
        mock_m4b.assert_called_once()
