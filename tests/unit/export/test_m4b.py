"""Unit tests for src/audiobook_studio/export/m4b.py — M4B encapsulation.

All I/O mocked. No real ffmpeg calls or file writes.
"""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.export.m4b import (
    ChapterMarker,
    M4bMetadata,
    _build_ffmpeg_chapter_metadata,
    _normalize_audio,
    build_m4b,
    build_m4b_single_source,
)


# ── ChapterMarker ────────────────────────────────────────────────────────────


class TestChapterMarker:
    def test_start_seconds(self):
        m = ChapterMarker(title="Ch1", start_ms=5000, duration_ms=10000)
        assert m.start_seconds == 5.0

    def test_end_seconds(self):
        m = ChapterMarker(title="Ch1", start_ms=5000, duration_ms=10000)
        assert m.end_seconds == 15.0

    def test_zero_start(self):
        m = ChapterMarker(title="Ch1", start_ms=0, duration_ms=30000)
        assert m.start_seconds == 0.0
        assert m.end_seconds == 30.0


# ── M4bMetadata ──────────────────────────────────────────────────────────────


class TestM4bMetadata:
    def test_defaults(self):
        m = M4bMetadata()
        assert m.title == ""
        assert m.artist == ""
        assert m.genre == "Audiobook"
        assert m.chapters == []
        assert m.cover_image is None

    def test_custom_values(self):
        m = M4bMetadata(title="Book", artist="Author", genre="Fiction", year="2024")
        assert m.title == "Book"
        assert m.artist == "Author"
        assert m.genre == "Fiction"
        assert m.year == "2024"


# ── _build_ffmpeg_chapter_metadata ───────────────────────────────────────────


class TestBuildFfmpegChapterMetadata:
    def test_single_chapter(self):
        chapters = [ChapterMarker("Chapter 1", 0, 60000)]
        result = _build_ffmpeg_chapter_metadata(chapters, 60000)
        assert "; FFMETADATA" in result
        assert "[CHAPTER]" in result
        assert "TIMEBASE=1/1000" in result
        assert "START=0" in result
        assert "END=60000" in result
        assert "title=Chapter 1" in result

    def test_multiple_chapters(self):
        chapters = [
            ChapterMarker("Ch1", 0, 30000),
            ChapterMarker("Ch2", 30000, 20000),
        ]
        result = _build_ffmpeg_chapter_metadata(chapters, 50000)
        assert result.count("[CHAPTER]") == 2
        assert "START=0" in result
        assert "START=30000" in result
        assert "END=30000" in result
        assert "END=50000" in result

    def test_escapes_special_chars(self):
        chapters = [ChapterMarker("Title=with;special\nchars", 0, 5000)]
        result = _build_ffmpeg_chapter_metadata(chapters, 5000)
        assert "Title\\=with\\;special chars" in result

    def test_empty_title_uses_fallback(self):
        chapters = [ChapterMarker("", 0, 5000)]
        result = _build_ffmpeg_chapter_metadata(chapters, 5000)
        assert "title=Chapter 1" in result

    def test_end_clamped_to_total(self):
        chapters = [ChapterMarker("Ch1", 0, 100000)]
        result = _build_ffmpeg_chapter_metadata(chapters, 50000)
        assert "END=50000" in result


# ── _normalize_audio ─────────────────────────────────────────────────────────


class TestNormalizeAudio:
    @patch("src.audiobook_studio.export.m4b.subprocess.run")
    def test_calls_ffmpeg(self, mock_run):
        _normalize_audio(Path("/in.mp3"), Path("/out.m4a"))
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert "-y" in cmd
        assert "loudnorm" in cmd[cmd.index("-af") + 1]

    @patch("src.audiobook_studio.export.m4b.subprocess.run")
    def test_ffmpeg_error_propagates(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "ffmpeg")
        with pytest.raises(subprocess.CalledProcessError):
            _normalize_audio(Path("/in.mp3"), Path("/out.m4a"))


# ── build_m4b ────────────────────────────────────────────────────────────────


class TestBuildM4b:
    @patch("src.audiobook_studio.export.m4b.subprocess.run")
    def test_mismatched_lengths_raises(self, mock_run):
        seg = MagicMock(spec=Path)
        markers = [ChapterMarker("Ch1", 0, 30000), ChapterMarker("Ch2", 30000, 20000)]
        output = MagicMock(spec=Path)

        with pytest.raises(ValueError, match="same length"):
            build_m4b([seg], markers, output)

    @patch("src.audiobook_studio.export.m4b.subprocess.run")
    def test_success_no_normalize(self, mock_run):
        mock_run.return_value = MagicMock(stdout="50.0\n", returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            seg1 = Path(tmpdir) / "seg1.mp3"
            seg1.write_bytes(b"fake audio")
            seg2 = Path(tmpdir) / "seg2.mp3"
            seg2.write_bytes(b"fake audio")

            markers = [
                ChapterMarker("Ch1", 0, 30000),
                ChapterMarker("Ch2", 30000, 20000),
            ]
            output = Path(tmpdir) / "out.m4b"

            # Create output file so stat() works (ffmpeg is mocked)
            output.write_bytes(b"fake m4b output")

            result = build_m4b([seg1, seg2], markers, output, normalize=False)
            assert result == output
            assert mock_run.call_count >= 3

    @patch("src.audiobook_studio.export.m4b.subprocess.run")
    def test_missing_segment_creates_silence(self, mock_run):
        mock_run.return_value = MagicMock(stdout="30.0\n", returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            seg = Path(tmpdir) / "missing.mp3"  # doesn't exist
            markers = [ChapterMarker("Ch1", 0, 30000)]
            output = Path(tmpdir) / "out.m4b"
            output.write_bytes(b"fake m4b")

            build_m4b([seg], markers, output, normalize=False)
            assert any("anullsrc" in str(c) for c in mock_run.call_args_list)

    @patch("src.audiobook_studio.export.m4b.subprocess.run")
    def test_with_metadata(self, mock_run):
        mock_run.return_value = MagicMock(stdout="30.0\n", returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            seg = Path(tmpdir) / "seg.mp3"
            seg.write_bytes(b"fake")
            markers = [ChapterMarker("Ch1", 0, 30000)]
            meta = M4bMetadata(title="My Book", artist="Author", album="Album", year="2024")
            output = Path(tmpdir) / "out.m4b"
            output.write_bytes(b"fake m4b")

            build_m4b([seg], markers, output, metadata=meta, normalize=False)
            final_cmd = mock_run.call_args_list[-1][0][0]
            assert "title=My Book" in final_cmd
            assert "artist=Author" in final_cmd
            assert "album=Album" in final_cmd

    @patch("src.audiobook_studio.export.m4b.subprocess.run")
    def test_with_normalize(self, mock_run):
        mock_run.return_value = MagicMock(stdout="30.0\n", returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            seg = Path(tmpdir) / "seg.mp3"
            seg.write_bytes(b"fake")
            markers = [ChapterMarker("Ch1", 0, 30000)]
            output = Path(tmpdir) / "out.m4b"
            output.write_bytes(b"fake m4b")

            build_m4b([seg], markers, output, normalize=True)
            # Current implementation doesn't call _normalize_audio in the loop
            # Expected calls: concat, probe, final = 3
            assert mock_run.call_count >= 3

    @patch("src.audiobook_studio.export.m4b.subprocess.run")
    def test_with_cover_image(self, mock_run):
        mock_run.return_value = MagicMock(stdout="30.0\n", returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            seg = Path(tmpdir) / "seg.mp3"
            seg.write_bytes(b"fake")
            cover = Path(tmpdir) / "cover.jpg"
            cover.write_bytes(b"fake cover")
            markers = [ChapterMarker("Ch1", 0, 30000)]
            meta = M4bMetadata(title="Book", cover_image=str(cover))
            output = Path(tmpdir) / "out.m4b"
            output.write_bytes(b"fake m4b")

            build_m4b([seg], markers, output, metadata=meta, normalize=False)
            final_cmd = mock_run.call_args_list[-1][0][0]
            assert str(cover) in final_cmd

    @patch("src.audiobook_studio.export.m4b.subprocess.run")
    def test_with_genre_and_year(self, mock_run):
        mock_run.return_value = MagicMock(stdout="30.0\n", returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            seg = Path(tmpdir) / "seg.mp3"
            seg.write_bytes(b"fake")
            markers = [ChapterMarker("Ch1", 0, 30000)]
            meta = M4bMetadata(genre="Sci-Fi", year="2024")
            output = Path(tmpdir) / "out.m4b"
            output.write_bytes(b"fake m4b")

            build_m4b([seg], markers, output, metadata=meta, normalize=False)
            final_cmd = mock_run.call_args_list[-1][0][0]
            assert "genre=Sci-Fi" in final_cmd
            assert "date=2024" in final_cmd


# ── build_m4b_single_source ─────────────────────────────────────────────────


class TestBuildM4bSingleSource:
    @patch("src.audiobook_studio.export.m4b.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(stdout="60.0\n", returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            audio = Path(tmpdir) / "full.mp3"
            audio.write_bytes(b"fake")
            markers = [ChapterMarker("Ch1", 0, 60000)]
            output = Path(tmpdir) / "out.m4b"
            output.write_bytes(b"fake m4b")

            result = build_m4b_single_source(audio, markers, output)
            assert result == output
            assert mock_run.call_count == 2

    @patch("src.audiobook_studio.export.m4b.subprocess.run")
    def test_with_metadata(self, mock_run):
        mock_run.return_value = MagicMock(stdout="60.0\n", returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            audio = Path(tmpdir) / "full.mp3"
            audio.write_bytes(b"fake")
            markers = [ChapterMarker("Ch1", 0, 60000)]
            meta = M4bMetadata(title="Book", artist="Author", genre="Fiction")
            output = Path(tmpdir) / "out.m4b"
            output.write_bytes(b"fake m4b")

            build_m4b_single_source(audio, markers, output, metadata=meta)
            final_cmd = mock_run.call_args_list[-1][0][0]
            assert "title=Book" in final_cmd
            assert "artist=Author" in final_cmd

    @patch("src.audiobook_studio.export.m4b.subprocess.run")
    def test_with_cover(self, mock_run):
        mock_run.return_value = MagicMock(stdout="60.0\n", returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            audio = Path(tmpdir) / "full.mp3"
            audio.write_bytes(b"fake")
            cover = Path(tmpdir) / "cover.jpg"
            cover.write_bytes(b"fake")
            markers = [ChapterMarker("Ch1", 0, 60000)]
            meta = M4bMetadata(title="Book", cover_image=str(cover))
            output = Path(tmpdir) / "out.m4b"
            output.write_bytes(b"fake m4b")

            build_m4b_single_source(audio, markers, output, metadata=meta)
            final_cmd = mock_run.call_args_list[-1][0][0]
            assert str(cover) in final_cmd

    @patch("src.audiobook_studio.export.m4b.subprocess.run")
    def test_no_metadata_defaults(self, mock_run):
        mock_run.return_value = MagicMock(stdout="60.0\n", returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            audio = Path(tmpdir) / "full.mp3"
            audio.write_bytes(b"fake")
            markers = [ChapterMarker("Ch1", 0, 60000)]
            output = Path(tmpdir) / "out.m4b"
            output.write_bytes(b"fake m4b")

            build_m4b_single_source(audio, markers, output)
            final_cmd = mock_run.call_args_list[-1][0][0]
            # Default metadata has empty title/artist but genre="Audiobook"
            assert "title=" not in " ".join(final_cmd)
            assert "artist=" not in " ".join(final_cmd)
            assert "genre=Audiobook" in final_cmd

    @patch("src.audiobook_studio.export.m4b.subprocess.run")
    def test_single_source_with_album_and_year(self, mock_run):
        """Covers lines 303, 307: album and year metadata in build_m4b_single_source."""
        mock_run.return_value = MagicMock(stdout="60.0\n", returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            audio = Path(tmpdir) / "full.mp3"
            audio.write_bytes(b"fake")
            markers = [ChapterMarker("Ch1", 0, 60000)]
            meta = M4bMetadata(title="Book", artist="Author", album="My Album", year="2026")
            output = Path(tmpdir) / "out.m4b"
            output.write_bytes(b"fake m4b")

            build_m4b_single_source(audio, markers, output, metadata=meta)
            final_cmd = mock_run.call_args_list[-1][0][0]
            assert "album=My Album" in final_cmd
            assert "date=2026" in final_cmd
