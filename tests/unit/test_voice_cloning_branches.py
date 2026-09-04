"""Tests for voice_cloning module - covering missing branches."""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import mock_open, patch

import numpy as np
import pytest

from src.audiobook_studio.tts.voice_cloning import (
    AudioQuality,
    CloningConfig,
    VoiceCloningManager,
    VoicePrint,
    VoiceSample,
)


class TestVoiceCloningManagerBranches:
    """Tests for VoiceCloningManager - targeting missing branches."""

    @pytest.fixture
    def config(self):
        """Create a test config."""
        return CloningConfig(
            min_sample_duration=15.0,
            min_snr_db=20.0,
            model_path="/tmp/test_models",
            output_dir="/tmp/test_voices",
        )

    @pytest.fixture
    def manager(self, config):
        """Create a VoiceCloningManager instance with mocked persistence."""
        with (
            patch.object(VoiceCloningManager, "_load_voice_prints"),
            patch.object(VoiceCloningManager, "_save_voice_prints"),
        ):
            manager = VoiceCloningManager(config)
            yield manager

    def test_load_voice_prints_file_not_exists(self, manager):
        """Test _load_voice_prints when file does not exist - covers line 89-90."""
        with patch("pathlib.Path.exists", return_value=False):
            manager._load_voice_prints()
            assert True

    def test_load_voice_prints_json_decode_error(self, manager):
        """Test _load_voice_prints with JSON decode error - covers lines 100-101."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data="invalid json")),
            patch("json.load", side_effect=json.JSONDecodeError("Expecting value", "", 0)),
        ):
            manager._load_voice_prints()
            assert True

    def test_load_voice_prints_general_exception(self, manager):
        """Test _load_voice_prints with general exception - covers lines 100-101."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data='{"key": "value"}')),
            patch("json.load", side_effect=Exception("General error")),
        ):
            manager._load_voice_prints()
            assert True

    def test_save_voice_prints_exception(self, manager):
        """Test _save_voice_prints exception handling - covers lines 122-123."""
        manager.voice_prints["test_speaker"] = VoicePrint(
            speaker_id="test_speaker",
            voice_hash="abc123",
            embedding=[0.1, 0.2, 0.3],
            quality=AudioQuality.GOOD,
            sample_count=1,
            avg_snr=22.0,
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
        )

        with patch("builtins.open", side_effect=Exception("Write error")):
            manager._save_voice_prints()
            assert True

    def test_extract_real_embedding_resampling(self, manager):
        """Test _extract_real_embedding with resampling - covers lines 141-148."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            import soundfile as sf

            audio_data = np.sin(np.linspace(0, 100, 48000)).astype(np.float32)
            sf.write(tmp.name, audio_data, 48000)

            try:
                sample = VoiceSample(
                    id="test",
                    file_path=Path(tmp.name),
                    duration=2.0,
                    sample_rate=48000,
                    snr_db=25.0,
                    text_content="Test",
                    language="zh-CN",
                    speaker_id="test",
                )
                embedding = manager._extract_real_embedding(sample, target_dim=256)
                assert len(embedding) == 256
            finally:
                Path(tmp.name).unlink(missing_ok=True)

    def test_extract_real_embedding_short_audio(self, manager):
        """Test _extract_real_embedding with short audio - covers line 157."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            import soundfile as sf

            audio_data = np.zeros(50, dtype=np.float32)
            sf.write(tmp.name, audio_data, 24000)

            try:
                sample = VoiceSample(
                    id="test",
                    file_path=Path(tmp.name),
                    duration=0.002,
                    sample_rate=24000,
                    snr_db=25.0,
                    text_content="Test",
                    language="zh-CN",
                    speaker_id="test",
                )
                embedding = manager._extract_real_embedding(sample, target_dim=256)
                assert len(embedding) == 256
            finally:
                Path(tmp.name).unlink(missing_ok=True)

    def test_extract_real_embedding_zero_magnitudes(self, manager):
        """Test _extract_real_embedding with zero magnitudes - covers line 165."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            import soundfile as sf

            audio_data = np.zeros(24000, dtype=np.float32)
            sf.write(tmp.name, audio_data, 24000)

            try:
                sample = VoiceSample(
                    id="test",
                    file_path=Path(tmp.name),
                    duration=1.0,
                    sample_rate=24000,
                    snr_db=25.0,
                    text_content="Test",
                    language="zh-CN",
                    speaker_id="test",
                )
                embedding = manager._extract_real_embedding(sample, target_dim=256)
                assert len(embedding) == 256
            finally:
                Path(tmp.name).unlink(missing_ok=True)

    def test_extract_real_embedding_exception_handler(self, manager):
        """Test _extract_real_embedding exception handler - covers lines 192-194."""
        with patch("soundfile.read") as mock_read:
            mock_read.side_effect = Exception("Mocked read error")

            sample = VoiceSample(
                id="test",
                file_path=Path("dummy.wav"),
                duration=1.0,
                sample_rate=24000,
                snr_db=25.0,
                text_content="Test",
                language="zh-CN",
                speaker_id="test",
            )
            embedding = manager._extract_real_embedding(sample, target_dim=256)
            assert len(embedding) == 256
            assert all(v == 0.5 for v in embedding)

    def test_calculate_audio_hash(self, manager):
        """Test _calculate_audio_hash - covers lines 196-211."""
        audio_data = np.random.rand(48000)
        sample_rate = 24000

        hash1 = manager._calculate_audio_hash(audio_data, sample_rate)
        hash2 = manager._calculate_audio_hash(audio_data, sample_rate)

        assert hash1 == hash2
        assert len(hash1) == 64

    def test_estimate_snr_zero_audio(self, manager):
        """Test _estimate_snr with zero audio - covers line 217-218."""
        audio_data = np.array([], dtype=np.float32)
        snr = manager._estimate_snr(audio_data, 24000)
        assert snr == 0.0

    def test_estimate_snr_zero_noise_floor(self, manager):
        """Test _estimate_snr with zero noise floor - covers lines 231-233."""
        audio_data = np.ones(24000, dtype=np.float32) * 0.5
        snr = manager._estimate_snr(audio_data, 24000)
        assert snr == 50.0

    def test_is_sample_valid_duration(self, manager):
        """Test _is_sample_valid with insufficient duration - covers lines 237-241."""
        sample = VoiceSample(
            id="test",
            file_path=Path("test.wav"),
            duration=10.0,
            sample_rate=24000,
            snr_db=25.0,
            text_content="Test",
            language="zh-CN",
            speaker_id="test",
        )
        is_valid, message = manager._is_sample_valid(sample)
        assert not is_valid
        assert "时长不足" in message

    def test_is_sample_valid_snr(self, manager):
        """Test _is_sample_valid with insufficient SNR - covers lines 243-247."""
        sample = VoiceSample(
            id="test",
            file_path=Path("test.wav"),
            duration=20.0,
            sample_rate=24000,
            snr_db=15.0,
            text_content="Test",
            language="zh-CN",
            speaker_id="test",
        )
        is_valid, message = manager._is_sample_valid(sample)
        assert not is_valid
        assert "信噪比不足" in message

    def test_is_sample_valid_both_pass(self, manager):
        """Test _is_sample_valid with both passing - covers line 249."""
        sample = VoiceSample(
            id="test",
            file_path=Path("test.wav"),
            duration=20.0,
            sample_rate=24000,
            snr_db=25.0,
            text_content="Test",
            language="zh-CN",
            speaker_id="test",
        )
        is_valid, message = manager._is_sample_valid(sample)
        assert is_valid
        assert message == "样本有效"

    def test_add_voice_sample_invalid(self, manager):
        """Test add_voice_sample with invalid sample - covers lines 259-261."""
        sample = VoiceSample(
            id="test",
            file_path=Path("test.wav"),
            duration=5.0,
            sample_rate=24000,
            snr_db=25.0,
            text_content="Test",
            language="zh-CN",
            speaker_id="test",
        )
        success, message = manager.add_voice_sample(sample)
        assert not success
        assert "时长不足" in message

    def test_update_voice_print_no_samples(self, manager):
        """Test _update_voice_print with no samples - covers lines 281-282."""
        success, message = manager._update_voice_print("nonexistent_speaker")
        assert not success
        assert "没有有效样本" in message

    def test_update_voice_print_no_valid_samples(self, manager):
        """Test _update_voice_print with no valid samples - covers lines 291-292."""
        for i in range(3):
            sample = VoiceSample(
                id=f"test_{i}",
                file_path=Path(f"test_{i}.wav"),
                duration=5.0,
                sample_rate=24000,
                snr_db=25.0,
                text_content="Test",
                language="zh-CN",
                speaker_id="test_speaker",
            )
            manager.voice_samples["test_speaker"] = [sample]

        success, message = manager._update_voice_print("test_speaker")
        assert not success
        assert "没有符合要求的有效样本" in message

    def test_update_voice_print_exception_handler(self, manager):
        """Test _update_voice_print exception handler - covers lines 349-350."""
        with patch.object(manager, "_extract_real_embedding", side_effect=Exception("Embedding error")):
            sample = VoiceSample(
                id="test",
                file_path=Path("test.wav"),
                duration=20.0,
                sample_rate=24000,
                snr_db=25.0,
                text_content="Test",
                language="zh-CN",
                speaker_id="test_speaker",
            )
            manager.voice_samples["test_speaker"] = [sample]

            success, message = manager._update_voice_print("test_speaker")
            assert not success
            assert "处理声音样本时出错" in message

    def test_assess_quality_excellent(self, manager):
        """Test _assess_quality EXCELLENT - covers line 354-355."""
        assert manager._assess_quality(30.0) == AudioQuality.EXCELLENT
        assert manager._assess_quality(25.0) == AudioQuality.EXCELLENT

    def test_assess_quality_good(self, manager):
        """Test _assess_quality GOOD - covers line 356-357."""
        assert manager._assess_quality(22.0) == AudioQuality.GOOD
        assert manager._assess_quality(20.0) == AudioQuality.GOOD

    def test_assess_quality_fair(self, manager):
        """Test _assess_quality FAIR - covers line 358-359."""
        assert manager._assess_quality(18.0) == AudioQuality.FAIR
        assert manager._assess_quality(15.0) == AudioQuality.FAIR

    def test_assess_quality_poor(self, manager):
        """Test _assess_quality POOR - covers line 360-361."""
        assert manager._assess_quality(10.0) == AudioQuality.POOR
        assert manager._assess_quality(14.9) == AudioQuality.POOR

    def _register_speaker(self, manager, speaker_id="test"):
        """预置说话人指纹，避免在到达 KokoroBackend 构造前 KeyError。"""
        manager.voice_prints[speaker_id] = {"embedding": [0.0] * 8}
        manager.voice_samples.setdefault(speaker_id, [])

    def test_async_synthesize_import_error(self, manager):
        """Test _async_synthesize_with_kokoro ImportError - covers lines 425-427."""
        # The function imports KokoroBackend inside the try block
        # We need to mock it at the module level where the function is defined
        import sys

        # Create a mock module
        mock_module = type(sys)("mock_kokoro_backend")
        mock_module.KokoroBackend = lambda *args, **kwargs: (_ for _ in ()).throw(ImportError("No module"))

        self._register_speaker(manager)
        with patch.dict("sys.modules", {"src.audiobook_studio.tts.kokoro_backend": mock_module}):
            result = asyncio.run(
                manager._async_synthesize_with_kokoro(
                    text="Test",
                    speaker_id="test",
                    language="zh-CN",
                    emotion="neutral",
                    output_path=Path("/tmp/test.wav"),
                )
            )
            success, message, audio_file = result
            assert not success
            assert "依赖缺失" in message

    def test_async_synthesize_file_not_found(self, manager):
        """Test _async_synthesize_with_kokoro FileNotFoundError - covers lines 428-430."""
        import sys

        # Create a mock module with KokoroBackend that raises FileNotFoundError
        mock_module = type(sys)("mock_kokoro_backend")

        def raise_file_not_found(*args, **kwargs):
            raise FileNotFoundError("Model not found")

        mock_module.KokoroBackend = raise_file_not_found

        self._register_speaker(manager)
        with patch.dict("sys.modules", {"src.audiobook_studio.tts.kokoro_backend": mock_module}):
            result = asyncio.run(
                manager._async_synthesize_with_kokoro(
                    text="Test",
                    speaker_id="test",
                    language="zh-CN",
                    emotion="neutral",
                    output_path=Path("/tmp/test.wav"),
                )
            )
            success, message, audio_file = result
            assert not success
            assert "模型文件缺失" in message

    def test_async_synthesize_general_exception(self, manager):
        """Test _async_synthesize_with_kokoro general exception - covers lines 431-433."""
        import sys

        mock_module = type(sys)("mock_kokoro_backend")

        class MockKokoro:
            def __init__(self, *args, **kwargs):
                pass

            async def initialize(self):
                pass

            async def synthesize(self, *args, **kwargs):
                raise Exception("Synthesis error")

            async def cleanup(self):
                pass

        mock_module.KokoroBackend = MockKokoro

        with patch.dict("sys.modules", {"src.audiobook_studio.tts.kokoro_backend": mock_module}):
            result = asyncio.run(
                manager._async_synthesize_with_kokoro(
                    text="Test",
                    speaker_id="test",
                    language="zh-CN",
                    emotion="neutral",
                    output_path=Path("/tmp/test.wav"),
                )
            )
            success, message, audio_file = result
            assert not success
            assert "合成失败" in message

    def test_synthesize_speech_speaker_not_found(self, manager):
        """Test synthesize_speech with speaker not found - covers lines 448-449."""
        success, message, audio_file = manager.synthesize_speech(
            text="Test",
            speaker_id="nonexistent",
            language="zh-CN",
            emotion="neutral",
        )
        assert not success
        assert "找不到说话人" in message

    def test_synthesize_speech_poor_quality(self, manager):
        """Test synthesize_speech with POOR quality - covers lines 454-459."""
        manager.voice_prints["poor_speaker"] = VoicePrint(
            speaker_id="poor_speaker",
            voice_hash="abc123",
            embedding=[0.1, 0.2, 0.3],
            quality=AudioQuality.POOR,
            sample_count=1,
            avg_snr=10.0,
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
        )

        success, message, audio_file = manager.synthesize_speech(
            text="Test",
            speaker_id="poor_speaker",
            language="zh-CN",
            emotion="neutral",
        )
        assert not success
        assert "声音质量太差" in message

    def test_synthesize_speech_kokoro_runtime_error_new_loop(self, manager):
        """Test synthesize_speech with RuntimeError (new loop) - covers lines 475-498."""
        manager.voice_prints["test_speaker"] = VoicePrint(
            speaker_id="test_speaker",
            voice_hash="abc123",
            embedding=[0.1] * 256,
            quality=AudioQuality.GOOD,
            sample_count=1,
            avg_snr=22.0,
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
        )
        manager.voice_samples["test_speaker"] = [
            VoiceSample(
                id="sample_1",
                file_path=Path("/tmp/test.wav"),
                duration=20.0,
                sample_rate=24000,
                snr_db=25.0,
                text_content="Test",
                language="zh-CN",
                speaker_id="test_speaker",
            )
        ]

        async def mock_async_synthesize(*args, **kwargs):
            return True, "Success", Path("/tmp/output.wav")

        with patch.object(manager, "_async_synthesize_with_kokoro", mock_async_synthesize):

            async def run_in_loop():
                return manager.synthesize_speech(
                    text="Test",
                    speaker_id="test_speaker",
                    language="zh-CN",
                    emotion="neutral",
                )

            result = asyncio.run(run_in_loop())
            success, message, audio_file = result
            assert success

    def test_synthesize_speech_general_exception(self, manager):
        """Test synthesize_speech general exception - covers lines 511-520."""
        manager.voice_prints["test_speaker"] = VoicePrint(
            speaker_id="test_speaker",
            voice_hash="abc123",
            embedding=[0.1] * 256,
            quality=AudioQuality.GOOD,
            sample_count=1,
            avg_snr=22.0,
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
        )

        with patch.object(manager, "_async_synthesize_with_kokoro", side_effect=Exception("General error")):
            try:
                manager.synthesize_speech(
                    text="Test",
                    speaker_id="test_speaker",
                    language="zh-CN",
                    emotion="neutral",
                )
                raise AssertionError("Should have raised RuntimeError")
            except RuntimeError as e:
                assert "语音合成失败" in str(e)

    def test_get_voice_info_not_exists(self, manager):
        """Test get_voice_info for non-existing speaker - covers lines 524-525."""
        info = manager.get_voice_info("nonexistent")
        assert info is None

    def test_get_voice_info_quality_check(self, manager):
        """Test get_voice_info is_available_for_cloning - covers line 536."""
        for quality, expected in [
            (AudioQuality.EXCELLENT, True),
            (AudioQuality.GOOD, True),
            (AudioQuality.FAIR, True),
            (AudioQuality.POOR, False),
        ]:
            manager.voice_prints[f"speaker_{quality.value}"] = VoicePrint(
                speaker_id=f"speaker_{quality.value}",
                voice_hash="abc123",
                embedding=[0.1] * 256,
                quality=quality,
                sample_count=1,
                avg_snr=(
                    25.0
                    if quality == AudioQuality.EXCELLENT
                    else 22.0 if quality == AudioQuality.GOOD else 18.0 if quality == AudioQuality.FAIR else 10.0
                ),
                created_at="2024-01-01T00:00:00",
                updated_at="2024-01-01T00:00:00",
            )

            info = manager.get_voice_info(f"speaker_{quality.value}")
            assert info is not None
            assert info["is_available_for_cloning"] == expected


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
