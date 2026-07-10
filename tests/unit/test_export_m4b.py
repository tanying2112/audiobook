"""Tests for M4B export module."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.export.m4b import (
    ChapterMarker,
    M4bMetadata,
    _build_ffmpeg_chapter_metadata,
    build_m4b,
    build_m4b_single_source,
)


class TestChapterMarker:
    """Tests for ChapterMarker dataclass."""

    def test_chapter_marker_creation(self):
        marker = ChapterMarker(
            title="Chapter 1",
            start_ms=0,
            duration_ms=300000,
        )
        assert marker.title == "Chapter 1"
        assert marker.start_ms == 0
        assert marker.duration_ms == 300000
        assert marker.start_seconds == 0.0
        assert marker.end_seconds == 300.0

    def test_chapter_marker_properties(self):
        marker = ChapterMarker(
            title="Chapter 2",
            start_ms=300000,
            duration_ms=250000,
        )
        assert marker.start_seconds == 300.0
        assert marker.end_seconds == 550.0


class TestM4bMetadata:
    """Tests for M4bMetadata dataclass."""

    def test_default_metadata(self):
        meta = M4bMetadata()
        assert meta.title == ""
        assert meta.artist == ""
        assert meta.album == ""
        assert meta.genre == "Audiobook"
        assert meta.year == ""
        assert meta.cover_image is None
        assert meta.chapters == []

    def test_custom_metadata(self):
        chapters = [ChapterMarker("Ch1", 0, 100000)]
        meta = M4bMetadata(
            title="Test Book",
            artist="Test Author",
            album="Test Album",
            year="2024",
            chapters=chapters,
        )
        assert meta.title == "Test Book"
        assert meta.artist == "Test Author"
        assert meta.album == "Test Album"
        assert meta.year == "2024"
        assert len(meta.chapters) == 1


class TestBuildFFmpegChapterMetadata:
    """Tests for _build_ffmpeg_chapter_metadata function."""

    def test_basic_metadata(self):
        chapters = [
            ChapterMarker("Chapter 1", 0, 300000),
            ChapterMarker("Chapter 2", 300000, 250000),
        ]
        total_duration = 550000

        result = _build_ffmpeg_chapter_metadata(chapters, total_duration)

        assert "; FFMETADATA" in result
        assert "[CHAPTER]" in result
        assert "TIMEBASE=1/1000" in result
        assert "START=0" in result
        assert "END=300000" in result
        assert "title=Chapter 1" in result
        assert "START=300000" in result
        assert "END=550000" in result
        assert "title=Chapter 2" in result

    def test_empty_chapters(self):
        chapters = []
        total_duration = 0

        result = _build_ffmpeg_chapter_metadata(chapters, total_duration)

        assert result == "; FFMETADATA"

    def test_special_characters_escaped(self):
        chapters = [
            ChapterMarker("Chapter = 1", 0, 100000),
            ChapterMarker("Chapter; 2", 100000, 100000),
        ]
        total_duration = 200000

        result = _build_ffmpeg_chapter_metadata(chapters, total_duration)

        assert "title=Chapter \\= 1" in result
        assert "title=Chapter\\; 2" in result


class TestBuildM4b:
    """Tests for build_m4b function."""

    def test_build_m4b_basic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            # Create mock audio segment files
            seg1 = tmpdir_path / "seg1.mp3"
            seg2 = tmpdir_path / "seg2.mp3"
            seg1.write_text("dummy audio 1")
            seg2.write_text("dummy audio 2")

            chapters = [
                ChapterMarker("Chapter 1", 0, 10000),
                ChapterMarker("Chapter 2", 10000, 15000),
            ]
            output_path = tmpdir_path / "output.m4b"

            # Mock subprocess.run to avoid needing ffmpeg
            def mock_run_side_effect(*args, **kwargs):
                # For the final ffmpeg command that creates output.m4b, create the file
                cmd = args[0] if args else []
                if isinstance(cmd, list) and str(output_path) in " ".join(cmd):
                    output_path.write_text("dummy m4b")
                return MagicMock(stdout="10.5", returncode=0)

            with patch(
                "src.audiobook_studio.export.m4b.subprocess.run",
                side_effect=mock_run_side_effect,
            ) as mock_run:
                build_m4b(
                    audio_segments=[seg1, seg2],
                    chapter_markers=chapters,
                    output_path=output_path,
                    normalize=False,
                )

            # Verify ffmpeg was called
            assert mock_run.call_count >= 3  # concat, probe, final m4b

    def test_build_m4b_single_segment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            seg1 = tmpdir_path / "seg1.mp3"
            seg1.write_text("dummy audio")

            chapters = [ChapterMarker("Chapter 1", 0, 10000)]
            output_path = tmpdir_path / "output.m4b"

            def mock_run_side_effect(*args, **kwargs):
                cmd = args[0] if args else []
                if isinstance(cmd, list) and str(output_path) in " ".join(cmd):
                    output_path.write_text("dummy m4b")
                return MagicMock(stdout="10.0", returncode=0)

            with patch(
                "src.audiobook_studio.export.m4b.subprocess.run",
                side_effect=mock_run_side_effect,
            ) as mock_run:
                build_m4b(
                    audio_segments=[seg1],
                    chapter_markers=chapters,
                    output_path=output_path,
                    normalize=False,
                )

            assert mock_run.call_count >= 3

    def test_build_m4b_segments_mismatch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            seg1 = tmpdir_path / "seg1.mp3"
            seg1.write_text("dummy audio")

            chapters = [
                ChapterMarker("Chapter 1", 0, 10000),
                ChapterMarker("Chapter 2", 10000, 10000),
            ]
            output_path = tmpdir_path / "output.m4b"

            with pytest.raises(ValueError, match="must have same length"):
                build_m4b(
                    audio_segments=[seg1],
                    chapter_markers=chapters,
                    output_path=output_path,
                )

    def test_build_m4b_with_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            seg1 = tmpdir_path / "seg1.mp3"
            seg1.write_text("dummy audio")

            chapters = [ChapterMarker("Chapter 1", 0, 10000)]
            output_path = tmpdir_path / "output.m4b"
            metadata = M4bMetadata(
                title="Test Title",
                artist="Test Author",
                album="Test Album",
            )

            def mock_run_side_effect(*args, **kwargs):
                cmd = args[0] if args else []
                if isinstance(cmd, list) and str(output_path) in " ".join(cmd):
                    output_path.write_text("dummy m4b")
                return MagicMock(stdout="10.0", returncode=0)

            with patch(
                "src.audiobook_studio.export.m4b.subprocess.run",
                side_effect=mock_run_side_effect,
            ) as mock_run:
                build_m4b(
                    audio_segments=[seg1],
                    chapter_markers=chapters,
                    output_path=output_path,
                    metadata=metadata,
                    normalize=False,
                )

            # Verify metadata passed to ffmpeg
            call_args_list = mock_run.call_args_list
            final_cmd = call_args_list[-1][0][0]  # Last call is the final ffmpeg
            assert "-metadata" in final_cmd
            assert "title=Test Title" in final_cmd
            assert "artist=Test Author" in final_cmd


class TestBuildM4bSingleSource:
    """Tests for build_m4b_single_source function."""

    def test_build_m4b_single_source_basic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            full_audio = tmpdir_path / "full.mp3"
            full_audio.write_text("dummy full audio")

            chapters = [
                ChapterMarker("Chapter 1", 0, 100000),
                ChapterMarker("Chapter 2", 100000, 100000),
            ]
            output_path = tmpdir_path / "output.m4b"

            with patch("src.audiobook_studio.export.m4b.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout="200.0", returncode=0)
                build_m4b_single_source(
                    full_audio_path=full_audio,
                    chapter_markers=chapters,
                    output_path=output_path,
                )

            assert mock_run.call_count >= 2  # probe + final m4b

    def test_build_m4b_single_source_with_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            full_audio = tmpdir_path / "full.mp3"
            full_audio.write_text("dummy full audio")

            chapters = [ChapterMarker("Chapter 1", 0, 100000)]
            output_path = tmpdir_path / "output.m4b"
            metadata = M4bMetadata(title="Single Source Book", artist="Author")

            with patch("src.audiobook_studio.export.m4b.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout="100.0", returncode=0)
                build_m4b_single_source(
                    full_audio_path=full_audio,
                    chapter_markers=chapters,
                    output_path=output_path,
                    metadata=metadata,
                )

            call_args_list = mock_run.call_args_list
            final_cmd = call_args_list[-1][0][0]
            assert "title=Single Source Book" in final_cmd


class TestBuildM4bMissingFiles:
    """Tests for build_m4b with missing audio files."""

    def test_missing_segment_creates_silence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            # seg1 exists, seg2 doesn't
            seg1 = tmpdir_path / "seg1.mp3"
            seg1.write_text("dummy audio")
            seg2 = tmpdir_path / "seg2.mp3"  # Doesn't exist

            chapters = [
                ChapterMarker("Chapter 1", 0, 10000),
                ChapterMarker("Chapter 2", 10000, 10000),
            ]
            output_path = tmpdir_path / "output.m4b"

            def mock_run_side_effect(*args, **kwargs):
                cmd = args[0] if args else []
                if isinstance(cmd, list) and str(output_path) in " ".join(cmd):
                    output_path.write_text("dummy m4b")
                return MagicMock(stdout="20.0", returncode=0)

            with patch(
                "src.audiobook_studio.export.m4b.subprocess.run",
                side_effect=mock_run_side_effect,
            ) as mock_run:
                build_m4b(
                    audio_segments=[seg1, seg2],
                    chapter_markers=chapters,
                    output_path=output_path,
                    normalize=False,
                )

            # Should have called ffmpeg to create silence
            calls = [str(call) for call in mock_run.call_args_list]
            assert any("anullsrc" in str(call) for call in calls)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
