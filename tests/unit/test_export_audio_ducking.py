"""Tests for Audio Ducking module."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.export.audio_ducking import (
    DuckingSegment,
    MixConfig,
    detect_speech_segments,
    mix_with_ducking,
    add_sfx,
)


class TestDuckingSegment:
    """Tests for DuckingSegment dataclass."""

    def test_default_segment(self):
        segment = DuckingSegment(start_ms=0, end_ms=5000)
        assert segment.start_ms == 0
        assert segment.end_ms == 5000
        assert segment.type == "speech"
        assert segment.duck_gain_db == -12.0
        assert segment.label == ""

    def test_custom_segment(self):
        segment = DuckingSegment(
            start_ms=1000,
            end_ms=6000,
            type="silence",
            duck_gain_db=0.0,
            label="pause",
        )
        assert segment.start_ms == 1000
        assert segment.end_ms == 6000
        assert segment.type == "silence"
        assert segment.duck_gain_db == 0.0
        assert segment.label == "pause"


class TestMixConfig:
    """Tests for MixConfig dataclass."""

    def test_default_config(self):
        config = MixConfig()
        assert config.bgm_path is None
        assert config.bgm_volume_db == -20.0
        assert config.duck_attack_ms == 50
        assert config.duck_release_ms == 200
        assert config.duck_threshold_db == -24.0
        assert config.duck_ratio == 4.0
        assert config.sfx_volume_db == -6.0
        assert config.silence_threshold_db == -50.0

    def test_custom_config(self):
        config = MixConfig(
            bgm_path="/path/to/bgm.mp3",
            bgm_volume_db=-15.0,
            duck_attack_ms=100,
            duck_release_ms=300,
            duck_threshold_db=-20.0,
            duck_ratio=3.0,
            sfx_volume_db=-3.0,
            silence_threshold_db=-40.0,
        )
        assert config.bgm_path == "/path/to/bgm.mp3"
        assert config.bgm_volume_db == -15.0
        assert config.duck_attack_ms == 100
        assert config.duck_release_ms == 300
        assert config.duck_threshold_db == -20.0
        assert config.duck_ratio == 3.0
        assert config.sfx_volume_db == -3.0
        assert config.silence_threshold_db == -40.0


class TestDetectSpeechSegments:
    """Tests for detect_speech_segments function."""

    def test_no_silence_detected(self):
        mock_audio_path = Path("/fake/audio.mp3")
        with patch("src.audiobook_studio.export.audio_ducking.get_duration_sync", return_value=10000), \
             patch("src.audiobook_studio.export.audio_ducking.detect_silence_sync", return_value=[]):
            segments = detect_speech_segments(mock_audio_path)

        assert len(segments) == 1
        assert segments[0].start_ms == 0
        assert segments[0].end_ms == 10000
        assert segments[0].type == "speech"
        assert segments[0].label == "speech"

    def test_with_silence_regions(self):
        mock_audio_path = Path("/fake/audio.mp3")
        silence_regions = [(2000, 3000), (6000, 7000)]

        with patch("src.audiobook_studio.export.audio_ducking.get_duration_sync", return_value=10000), \
             patch("src.audiobook_studio.export.audio_ducking.detect_silence_sync", return_value=silence_regions):
            segments = detect_speech_segments(mock_audio_path)

        # Should have: speech(0-2000), silence(2000-3000), speech(3000-6000), silence(6000-7000), speech(7000-10000)
        assert len(segments) == 5
        assert segments[0].type == "speech"
        assert segments[0].start_ms == 0
        assert segments[0].end_ms == 2000
        assert segments[1].type == "silence"
        assert segments[1].duck_gain_db == 0
        assert segments[2].type == "speech"
        assert segments[2].start_ms == 3000
        assert segments[2].end_ms == 6000
        assert segments[3].type == "silence"
        assert segments[4].type == "speech"
        assert segments[4].end_ms == 10000

    def test_custom_threshold(self):
        mock_audio_path = Path("/fake/audio.mp3")
        with patch("src.audiobook_studio.export.audio_ducking.get_duration_sync", return_value=5000), \
             patch("src.audiobook_studio.export.audio_ducking.detect_silence_sync", return_value=[]):
            segments = detect_speech_segments(mock_audio_path, silence_threshold_db=-40.0)

        assert len(segments) == 1

    def test_min_speech_filter(self):
        # Silence region that's too short should be ignored
        mock_audio_path = Path("/fake/audio.mp3")
        silence_regions = [(100, 200)]  # Only 100ms of silence

        with patch("src.audiobook_studio.export.audio_ducking.get_duration_sync", return_value=5000), \
             patch("src.audiobook_studio.export.audio_ducking.detect_silence_sync", return_value=silence_regions):
            segments = detect_speech_segments(mock_audio_path, min_speech_ms=200)

        # The short silence should not create a separate silence segment
        # Should be one long speech segment
        speech_segments = [s for s in segments if s.type == "speech"]
        assert len(speech_segments) >= 1


class TestMixWithDucking:
    """Tests for mix_with_ducking function."""

    def test_mix_without_bgm(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            speech_path = tmpdir_path / "speech.mp3"
            speech_path.write_text("dummy speech")
            output_path = tmpdir_path / "output.m4a"

            with patch("src.audiobook_studio.export.audio_ducking.get_duration_sync", return_value=5000), \
                 patch("src.audiobook_studio.export.audio_ducking.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                result = mix_with_ducking(
                    speech_path=speech_path,
                    output_path=output_path,
                    bgm_path=None,
                )

        assert result == output_path
        mock_run.assert_called_once()

    def test_mix_with_bgm(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            speech_path = tmpdir_path / "speech.mp3"
            speech_path.write_text("dummy speech")
            bgm_path = tmpdir_path / "bgm.mp3"
            bgm_path.write_text("dummy bgm")
            output_path = tmpdir_path / "output.m4a"

            with patch("src.audiobook_studio.export.audio_ducking.get_duration_sync", return_value=10000), \
                 patch("src.audiobook_studio.export.audio_ducking.detect_speech_segments") as mock_detect, \
                 patch("src.audiobook_studio.export.audio_ducking.subprocess.run") as mock_run:
                mock_detect.return_value = [
                    DuckingSegment(0, 10000, "speech", label="speech")
                ]
                mock_run.return_value = MagicMock(returncode=0)
                result = mix_with_ducking(
                    speech_path=speech_path,
                    output_path=output_path,
                    bgm_path=str(bgm_path),
                )

        assert result == output_path
        assert mock_run.call_count == 1

    def test_mix_with_custom_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            speech_path = tmpdir_path / "speech.mp3"
            speech_path.write_text("dummy speech")
            bgm_path = tmpdir_path / "bgm.mp3"
            bgm_path.write_text("dummy bgm")
            output_path = tmpdir_path / "output.m4a"

            config = MixConfig(
                bgm_volume_db=-15.0,
                duck_threshold_db=-20.0,
                duck_ratio=3.0,
                duck_attack_ms=100,
                duck_release_ms=300,
                sfx_volume_db=-3.0,
                silence_threshold_db=-40.0,
            )

            with patch("src.audiobook_studio.export.audio_ducking.get_duration_sync", return_value=10000), \
                 patch("src.audiobook_studio.export.audio_ducking.detect_speech_segments") as mock_detect, \
                 patch("src.audiobook_studio.export.audio_ducking.subprocess.run") as mock_run:
                mock_detect.return_value = [
                    DuckingSegment(0, 10000, "speech", label="speech")
                ]
                mock_run.return_value = MagicMock(returncode=0)
                result = mix_with_ducking(
                    speech_path=speech_path,
                    output_path=output_path,
                    bgm_path=str(bgm_path),
                    config=config,
                )

        assert result == output_path
        call_args = mock_run.call_args[0][0]
        # Verify config values in filter complex
        filter_complex = call_args[call_args.index("-filter_complex") + 1]
        assert "threshold=-20.0dB" in filter_complex
        assert "ratio=3.0" in filter_complex
        assert "attack=100" in filter_complex
        assert "release=300" in filter_complex

    def test_mix_with_predefined_segments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            speech_path = tmpdir_path / "speech.mp3"
            speech_path.write_text("dummy speech")
            bgm_path = tmpdir_path / "bgm.mp3"
            bgm_path.write_text("dummy bgm")
            output_path = tmpdir_path / "output.m4a"

            segments = [
                DuckingSegment(0, 3000, "speech", label="speech"),
                DuckingSegment(3000, 5000, "silence", duck_gain_db=0, label="silence"),
                DuckingSegment(5000, 10000, "speech", label="speech"),
            ]

            with patch("src.audiobook_studio.export.audio_ducking.get_duration_sync", return_value=10000), \
                 patch("src.audiobook_studio.export.audio_ducking.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                result = mix_with_ducking(
                    speech_path=speech_path,
                    output_path=output_path,
                    bgm_path=str(bgm_path),
                    ducking_segments=segments,
                )

        assert result == output_path
        mock_run.assert_called_once()

    def test_timeout_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            speech_path = tmpdir_path / "speech.mp3"
            speech_path.write_text("dummy speech")
            bgm_path = tmpdir_path / "bgm.mp3"
            bgm_path.write_text("dummy bgm")
            output_path = tmpdir_path / "output.m4a"

            import subprocess
            with patch("src.audiobook_studio.export.audio_ducking.get_duration_sync", return_value=10000), \
                 patch("src.audiobook_studio.export.audio_ducking.detect_speech_segments") as mock_detect, \
                 patch("src.audiobook_studio.export.audio_ducking.subprocess.run") as mock_run:
                mock_detect.return_value = [
                    DuckingSegment(0, 10000, "speech", label="speech")
                ]
                # First call times out, second call (fallback) succeeds
                mock_run.side_effect = [
                    subprocess.TimeoutExpired("ffmpeg", 300),
                    MagicMock(returncode=0),
                ]
                result = mix_with_ducking(
                    speech_path=speech_path,
                    output_path=output_path,
                    bgm_path=str(bgm_path),
                )

        assert result == output_path
        assert mock_run.call_count == 2


class TestAddSfx:
    """Tests for add_sfx function."""

    def test_add_sfx_basic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            speech_path = tmpdir_path / "speech.mp3"
            speech_path.write_text("dummy speech")
            sfx_path = tmpdir_path / "sfx.wav"
            sfx_path.write_text("dummy sfx")
            output_path = tmpdir_path / "output.mp3"

            with patch("src.audiobook_studio.export.audio_ducking.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                result = add_sfx(
                    speech_path=speech_path,
                    sfx_path=sfx_path,
                    output_path=output_path,
                    insert_at_ms=5000,
                    sfx_volume_db=-6.0,
                )

        assert result == output_path
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "volume=-6.0dB" in " ".join(call_args)

    def test_add_sfx_custom_position_and_volume(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            speech_path = tmpdir_path / "speech.mp3"
            speech_path.write_text("dummy speech")
            sfx_path = tmpdir_path / "sfx.wav"
            sfx_path.write_text("dummy sfx")
            output_path = tmpdir_path / "output.mp3"

            with patch("src.audiobook_studio.export.audio_ducking.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                result = add_sfx(
                    speech_path=speech_path,
                    sfx_path=sfx_path,
                    output_path=output_path,
                    insert_at_ms=10000,
                    sfx_volume_db=-3.0,
                )

        assert result == output_path
        call_args = mock_run.call_args[0][0]
        filter_complex = call_args[call_args.index("-filter_complex") + 1]
        assert "volume=-3.0dB" in filter_complex
        assert "between(t,10.0,13.0)" in filter_complex  # 10s to 13s (10000ms + 3000ms)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])