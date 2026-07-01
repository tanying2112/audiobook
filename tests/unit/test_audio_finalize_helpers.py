"""Targeted tests for src/audiobook_studio/pipeline/audio_finalize.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.pipeline.audio_finalize import (
    AudioFinalizer,
    DEFAULT_SFX_LIBRARY_PATH,
    finalize_audio,
)
from src.audiobook_studio.schemas.audio_finalize import (
    AudioFinalizeParams,
    AudioFinalizeResult,
)


def make_params(**overrides) -> AudioFinalizeParams:
    """Build a default AudioFinalizeParams."""
    return AudioFinalizeParams(**overrides)


class TestAudioFinalizerInit:
    def test_default_init(self):
        f = AudioFinalizer()
        assert f.mock_mode is False
        assert f.sfx_library_path == DEFAULT_SFX_LIBRARY_PATH

    def test_init_with_mock(self):
        f = AudioFinalizer(mock_mode=True)
        assert f.mock_mode is True

    def test_init_with_custom_sfx_path(self, tmp_path):
        f = AudioFinalizer(sfx_library_path=tmp_path)
        assert f.sfx_library_path == tmp_path


class TestAudioFinalizerMockMode:
    def test_finalize_mock_creates_output(self, tmp_path):
        f = AudioFinalizer(mock_mode=True)
        inp = tmp_path / "in.mp3"
        inp.write_bytes(b"\x00" * 100)
        out = tmp_path / "out.mp3"

        params = make_params()
        result = f.finalize(
            input_path=inp,
            output_path=out,
            params=params,
        )
        assert isinstance(result, AudioFinalizeResult)
        assert out.exists()
        assert result.duration_ms == 10000  # mock duration

    def test_finalize_mock_no_sfx(self, tmp_path):
        f = AudioFinalizer(mock_mode=True)
        inp = tmp_path / "in.mp3"
        inp.write_bytes(b"\x00" * 100)
        out = tmp_path / "out.mp3"
        result = f.finalize(
            input_path=inp,
            output_path=out,
            params=make_params(),
            sfx_tags=["ambient_cheerful"],
        )
        # sfx_applied is signalled via params.apply_sfx and sfx_tags truthy
        assert result.sfx_applied is True

    def test_finalize_mock_metadata_skip(self, tmp_path):
        """metadata_embedded only true when metadata_title also set."""
        f = AudioFinalizer(mock_mode=True)
        inp = tmp_path / "in.mp3"
        inp.write_bytes(b"\x00" * 100)
        out = tmp_path / "out.mp3"
        params = make_params(embed_metadata=True)
        # metadata_embedded False: no metadata_title
        result = f.finalize(
            input_path=inp,
            output_path=out,
            params=params,
        )
        assert result.metadata_embedded is False

    def test_finalize_mock_metadata_present(self, tmp_path):
        f = AudioFinalizer(mock_mode=True)
        inp = tmp_path / "in.mp3"
        inp.write_bytes(b"\x00" * 100)
        out = tmp_path / "out.mp3"
        params = make_params(metadata_title="Chapter 1", metadata_album="红楼梦")
        result = f.finalize(
            input_path=inp,
            output_path=out,
            params=params,
        )
        assert result.metadata_embedded is True


class TestRealModeMissingInput:
    def test_real_mode_missing_input_returns_error_result(self, tmp_path):
        f = AudioFinalizer(mock_mode=False)
        inp = tmp_path / "does_not_exist.mp3"
        out = tmp_path / "out.mp3"
        result = f.finalize(
            input_path=inp,
            output_path=out,
            params=make_params(),
        )
        # Returns result with error, no crash
        assert "Input file not found" in (result.errors[0] if result.errors else "")


class TestBuildLoudnormFilter:
    def test_loudnorm_filter_string(self):
        f = AudioFinalizer(mock_mode=True)
        params = make_params(
            loudnorm_target_i=-18.0,
            loudnorm_target_lra=8.0,
            loudnorm_target_tp=-1.5,
        )
        result = f._build_loudnorm_filter(params)
        assert "loudnorm=" in result
        assert "I=-18.0" in result
        assert "LRA=8.0" in result
        assert "TP=-1.5" in result


class TestBuildFadeFilter:
    def test_fade_in_only(self):
        f = AudioFinalizer(mock_mode=True)
        params = make_params(
            fade_in_ms=1000, fade_out_ms=0, fade_shape="tri"
        )
        result = f._build_fade_filter(params)
        assert "afade=t=in" in result
        assert "st=0" in result
        assert "d=1.0" in result

    def test_fade_out_with_placeholder(self):
        f = AudioFinalizer(mock_mode=True)
        params = make_params(
            fade_in_ms=0, fade_out_ms=2000, fade_shape="sin"
        )
        result = f._build_fade_filter(params)
        assert "afade=t=out" in result
        assert "PLACEHOLDER" in result
        assert "d=2.0" in result

    def test_fade_both(self):
        f = AudioFinalizer(mock_mode=True)
        params = make_params(
            fade_in_ms=500, fade_out_ms=500, fade_shape="tri"
        )
        result = f._build_fade_filter(params)
        assert "afade=t=in" in result
        assert "afade=t=out" in result


class TestResolveSfxFiles:
    def test_sfx_files_basic(self, tmp_path):
        f = AudioFinalizer(sfx_library_path=tmp_path)
        # Create one of the files
        sfx_file = tmp_path / "ambient_cheerful.mp3"
        sfx_file.write_bytes(b"\x00")

        result = f._resolve_sfx_files(["ambient_cheerful"])
        assert len(result) == 1
        assert result[0].name == "ambient_cheerful.mp3"

    def test_sfx_files_unknown_passthrough(self, tmp_path):
        f = AudioFinalizer(sfx_library_path=tmp_path)
        result = f._resolve_sfx_files(["unknown_sound"])
        assert result[0].name == "unknown_sound.mp3"


class TestMeasureLoudness:
    def test_measure_loudness_no_path(self):
        f = AudioFinalizer(mock_mode=True)
        i, lra, tp, thresh = f._measure_loudness(Path("/nonexistent.mp3"))
        assert i == 0.0
        assert lra == 0.0
        assert tp == 0.0
        assert thresh == 0.0

    def test_measure_loudness_parses_ffmpeg_output(self, tmp_path):
        f = AudioFinalizer(mock_mode=True)
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"\x00")
        # Mocked subprocess.run returning simulated ebur128 output
        fake_stderr = """
[Parsed_ebur128_0 @ 0x55] t: 0.001  I: -20.5 LUFS  LRA: 7.5 LU  Peak: -2.5 dBFS  Threshold: -40.5 LUFS
"""
        fake_result = MagicMock()
        fake_result.stderr = fake_stderr
        with patch("subprocess.run", return_value=fake_result):
            i, lra, tp, thresh = f._measure_loudness(audio)
        assert i == -20.5
        assert lra == 7.5
        assert tp == -2.5
        assert thresh == -40.5

    def test_measure_loudness_subprocess_exception(self, tmp_path):
        f = AudioFinalizer(mock_mode=True)
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"\x00")
        with patch(
            "subprocess.run",
            side_effect=Exception("ffprobe crashed"),
        ):
            i, lra, tp, thresh = f._measure_loudness(audio)
        assert i == -20.0  # defaults
        assert thresh == -40.0


class TestGetDuration:
    def test_duration_no_path(self):
        f = AudioFinalizer(mock_mode=True)
        d = f._get_duration(Path("/nonexistent.mp3"))
        assert d == 0

    def test_duration_subprocess_failure(self, tmp_path):
        f = AudioFinalizer(mock_mode=True)
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"\x00")
        with patch("subprocess.run", side_effect=Exception("boom")):
            d = f._get_duration(audio)
        assert d == 0


class TestEmbedMetadataNoArgs:
    def test_embed_metadata_no_fields(self, tmp_path):
        f = AudioFinalizer(mock_mode=True)
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"\x00")
        params = make_params(metadata_title=None, embed_metadata=True)
        result = f._embed_metadata(audio, params)
        assert result is False


class TestFinalizeAudioConvenience:
    def test_finalize_audio_mock(self, tmp_path):
        inp = tmp_path / "in.mp3"
        inp.write_bytes(b"\x00")
        out = tmp_path / "out.mp3"
        result = finalize_audio(
            input_path=inp,
            output_path=out,
            mock_mode=True,
        )
        assert isinstance(result, AudioFinalizeResult)
        assert out.exists()

    def test_finalize_audio_default_params(self, tmp_path):
        inp = tmp_path / "in.mp3"
        inp.write_bytes(b"\x00")
        out = tmp_path / "out.mp3"
        result = finalize_audio(
            input_path=inp,
            output_path=out,
            mock_mode=True,
        )
        # Default params should produce a valid result
        assert result.duration_ms > 0
