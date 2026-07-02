"""Unit tests for src/audiobook_studio/export/audio_ducking.py — Audio ducking.

All I/O mocked. No real ffmpeg calls.
"""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from src.audiobook_studio.export.audio_ducking import (
    DuckingSegment,
    MixConfig,
    add_sfx,
    detect_speech_segments,
    mix_with_ducking,
)

# ── DuckingSegment ───────────────────────────────────────────────────────────


class TestDuckingSegment:
    def test_defaults(self):
        s = DuckingSegment(start_ms=0, end_ms=5000)
        assert s.type == "speech"
        assert s.duck_gain_db == -12.0
        assert s.label == ""

    def test_custom(self):
        s = DuckingSegment(start_ms=1000, end_ms=3000, type="silence", duck_gain_db=0, label="quiet")
        assert s.type == "silence"
        assert s.duck_gain_db == 0


# ── MixConfig ────────────────────────────────────────────────────────────────


class TestMixConfig:
    def test_defaults(self):
        cfg = MixConfig()
        assert cfg.bgm_volume_db == -20.0
        assert cfg.duck_attack_ms == 50
        assert cfg.duck_release_ms == 200
        assert cfg.duck_threshold_db == -24.0
        assert cfg.duck_ratio == 4.0
        assert cfg.silence_threshold_db == -50.0

    def test_custom(self):
        cfg = MixConfig(bgm_volume_db=-10, duck_ratio=8.0)
        assert cfg.bgm_volume_db == -10
        assert cfg.duck_ratio == 8.0


# ── detect_speech_segments ───────────────────────────────────────────────────


class TestDetectSpeechSegments:
    @patch("src.audiobook_studio.export.audio_ducking.get_duration_sync", return_value=10000)
    @patch("src.audiobook_studio.export.audio_ducking.detect_silence_sync", return_value=[])
    def test_no_silence_whole_file_speech(self, mock_silence, mock_dur):
        result = detect_speech_segments(Path("/audio.mp3"))
        assert len(result) == 1
        assert result[0].type == "speech"
        assert result[0].end_ms == 10000

    @patch("src.audiobook_studio.export.audio_ducking.get_duration_sync", return_value=10000)
    @patch("src.audiobook_studio.export.audio_ducking.detect_silence_sync")
    def test_silence_in_middle(self, mock_silence, mock_dur):
        mock_silence.return_value = [(3000, 5000)]
        result = detect_speech_segments(Path("/audio.mp3"))
        # Should have speech before, silence, speech after
        assert len(result) == 3
        assert result[0].type == "speech"
        assert result[0].end_ms == 3000
        assert result[1].type == "silence"
        assert result[2].type == "speech"

    @patch("src.audiobook_studio.export.audio_ducking.get_duration_sync", return_value=10000)
    @patch("src.audiobook_studio.export.audio_ducking.detect_silence_sync")
    def test_short_segments_filtered(self, mock_silence, mock_dur):
        # Silence too short to create a speech segment before it
        mock_silence.return_value = [(50, 100)]
        result = detect_speech_segments(Path("/audio.mp3"), min_speech_ms=200)
        # Very short speech before silence gets filtered
        types = [s.type for s in result]
        assert "speech" in types

    @patch("src.audiobook_studio.export.audio_ducking.get_duration_sync", return_value=5000)
    @patch("src.audiobook_studio.export.audio_ducking.detect_silence_sync")
    def test_multiple_silence_regions(self, mock_silence, mock_dur):
        mock_silence.return_value = [(1000, 2000), (3000, 4000)]
        result = detect_speech_segments(Path("/audio.mp3"))
        assert len(result) >= 3


# ── mix_with_ducking ─────────────────────────────────────────────────────────


class TestMixWithDucking:
    @patch("src.audiobook_studio.export.audio_ducking.subprocess.run")
    @patch("src.audiobook_studio.export.audio_ducking.get_duration_sync", return_value=10000)
    @patch("src.audiobook_studio.export.audio_ducking.detect_speech_segments")
    def test_no_bgm_post_processing(self, mock_detect, mock_dur, mock_run):
        mock_detect.return_value = [DuckingSegment(0, 10000, "speech")]
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "out.m4a"
            result = mix_with_ducking(Path("/speech.mp3"), output, bgm_path=None)
            assert result == output
            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            assert any("loudnorm" in str(c) for c in cmd)

    @patch("src.audiobook_studio.export.audio_ducking.subprocess.run")
    @patch("src.audiobook_studio.export.audio_ducking.get_duration_sync", return_value=60000)
    @patch("src.audiobook_studio.export.audio_ducking.detect_speech_segments")
    def test_with_bgm_ducking(self, mock_detect, mock_dur, mock_run):
        mock_detect.return_value = [DuckingSegment(0, 60000, "speech")]
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "out.m4a"
            result = mix_with_ducking(Path("/speech.mp3"), output, bgm_path="/bgm.mp3")
            assert result == output
            mock_run.assert_called_once()

    @patch("src.audiobook_studio.export.audio_ducking.subprocess.run")
    @patch("src.audiobook_studio.export.audio_ducking.get_duration_sync", return_value=10000)
    @patch("src.audiobook_studio.export.audio_ducking.detect_speech_segments")
    def test_ffmpeg_timeout_fallback(self, mock_detect, mock_dur, mock_run):
        mock_detect.return_value = [DuckingSegment(0, 10000, "speech")]
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "out.m4a"
            mock_run.side_effect = [
                subprocess.TimeoutExpired("ffmpeg", 300),
                MagicMock(returncode=0),
            ]
            result = mix_with_ducking(Path("/speech.mp3"), output, bgm_path="/bgm.mp3")
            assert result == output
            assert mock_run.call_count == 2

    @patch("src.audiobook_studio.export.audio_ducking.subprocess.run")
    @patch("src.audiobook_studio.export.audio_ducking.get_duration_sync", return_value=10000)
    @patch("src.audiobook_studio.export.audio_ducking.detect_speech_segments")
    def test_with_custom_config(self, mock_detect, mock_dur, mock_run):
        mock_detect.return_value = [DuckingSegment(0, 10000, "speech")]
        cfg = MixConfig(bgm_volume_db=-15, duck_ratio=6.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "out.m4a"
            mix_with_ducking(Path("/speech.mp3"), output, bgm_path="/bgm.mp3", config=cfg)
            mock_run.assert_called_once()

    @patch("src.audiobook_studio.export.audio_ducking.subprocess.run")
    @patch("src.audiobook_studio.export.audio_ducking.get_duration_sync", return_value=10000)
    def test_with_predefined_segments(self, mock_dur, mock_run):
        segments = [DuckingSegment(0, 5000, "speech"), DuckingSegment(5000, 10000, "silence")]
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "out.m4a"
            mix_with_ducking(Path("/speech.mp3"), output, bgm_path="/bgm.mp3", ducking_segments=segments)
            mock_run.assert_called_once()


# ── add_sfx ──────────────────────────────────────────────────────────────────


class TestAddSfx:
    @patch("src.audiobook_studio.export.audio_ducking.subprocess.run")
    def test_success(self, mock_run):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "out.m4a"
            result = add_sfx(Path("/speech.mp3"), Path("/sfx.mp3"), output, insert_at_ms=5000)
            assert result == output
            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            assert "ffmpeg" in cmd
            assert "overlay" in str(cmd)

    @patch("src.audiobook_studio.export.audio_ducking.subprocess.run")
    def test_ffmpeg_error_propagates(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "ffmpeg")
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "out.m4a"
            with pytest.raises(subprocess.CalledProcessError):
                add_sfx(Path("/speech.mp3"), Path("/sfx.mp3"), output)

    @patch("src.audiobook_studio.export.audio_ducking.subprocess.run")
    def test_custom_volume(self, mock_run):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "out.m4a"
            add_sfx(
                Path("/speech.mp3"),
                Path("/sfx.mp3"),
                output,
                insert_at_ms=0,
                sfx_volume_db=-12.0,
            )
            mock_run.assert_called_once()
