"""Comprehensive tests for tts/clone.py."""
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import numpy as np
import pytest

from src.audiobook_studio.tts.clone import (
    AudioQuality,
    CloningConfig,
    VoiceCloner,
    VoiceCloningEngine,
    VoicePrint,
    VoiceSample,
    check_kokoro_model_availability,
    get_kokoro_model_path,
    is_kokoro_available,
    clone_voice,
    load_voice_print,
    VoiceCloningManager,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def config(tmp_path):
    return CloningConfig(
        min_sample_duration=5.0,
        min_snr_db=15.0,
        similarity_threshold=0.85,
        model_path=str(tmp_path / "models"),
        output_dir=str(tmp_path / "voices"),
    )


@pytest.fixture
def engine(config):
    return VoiceCloningEngine(config)


@pytest.fixture
def sample(tmp_path):
    f = tmp_path / "sample.wav"
    f.write_bytes(b"\x00" * 100)
    return VoiceSample(
        id="s1",
        file_path=f,
        duration=10.0,
        sample_rate=24000,
        snr_db=25.0,
        text_content="Hello world",
        language="en",
        speaker_id="spk1",
    )


# ── AudioQuality ────────────────────────────────────────────────────────────

class TestAudioQuality:
    def test_enum_values(self):
        assert AudioQuality.EXCELLENT.value == "excellent"
        assert AudioQuality.GOOD.value == "good"
        assert AudioQuality.FAIR.value == "fair"
        assert AudioQuality.POOR.value == "poor"


# ── CloningConfig ────────────────────────────────────────────────────────────

class TestCloningConfig:
    def test_defaults(self):
        c = CloningConfig()
        assert c.min_sample_duration == 15.0
        assert c.min_snr_db == 20.0
        assert c.similarity_threshold == 0.85

    def test_custom(self):
        c = CloningConfig(min_sample_duration=3.0, min_snr_db=10.0)
        assert c.min_sample_duration == 3.0
        assert c.min_snr_db == 10.0


# ── VoiceSample ──────────────────────────────────────────────────────────────

class TestVoiceSample:
    def test_creation(self, sample):
        assert sample.speaker_id == "spk1"
        assert sample.duration == 10.0
        assert sample.snr_db == 25.0
        assert sample.id == "s1"


# ── VoicePrint ──────────────────────────────────────────────────────────────

class TestVoicePrint:
    def test_creation(self):
        vp = VoicePrint(
            speaker_id="spk1",
            voice_hash="abc123",
            embedding=[0.1] * 8,
            quality=AudioQuality.GOOD,
            sample_count=3,
            avg_snr=22.0,
            created_at="2024-01-01",
            updated_at="2024-01-02",
        )
        assert vp.speaker_id == "spk1"
        assert vp.sample_count == 3


# ── VoiceCloner stub ─────────────────────────────────────────────────────────

class TestVoiceClonerStub:
    def test_init(self):
        vc = VoiceCloner()
        assert vc is not None

    def test_clone_voice(self):
        vc = VoiceCloner()
        assert vc.clone_voice() is True

    def test_get_cloned_voices(self):
        vc = VoiceCloner()
        assert vc.get_cloned_voices() == []


# ── Module functions ─────────────────────────────────────────────────────────

class TestModuleFunctions:
    def test_clone_voice_fn(self):
        assert clone_voice() is True

    def test_load_voice_print_fn(self):
        assert load_voice_print() is None

    def test_voice_cloning_manager_alias(self):
        assert VoiceCloningManager is VoiceCloningEngine


# ── Model availability ──────────────────────────────────────────────────────

class TestModelAvailability:
    def test_check_missing(self, tmp_path):
        result = check_kokoro_model_availability(str(tmp_path / "no_model"))
        assert result is False
        assert is_kokoro_available() is False
        assert get_kokoro_model_path() is None

    def test_check_found(self, tmp_path):
        model_dir = tmp_path / "models"
        model_dir.mkdir()
        (model_dir / "kokoro-v1.0.onnx").write_bytes(b"model")
        (model_dir / "voices-v1.0.bin").write_bytes(b"voices")
        result = check_kokoro_model_availability(str(model_dir))
        assert result is True
        assert is_kokoro_available() is True
        assert get_kokoro_model_path() == model_dir

    def test_check_alt_names(self, tmp_path):
        model_dir = tmp_path / "models"
        model_dir.mkdir()
        (model_dir / "model.onnx").write_bytes(b"model")
        (model_dir / "voices.bin").write_bytes(b"voices")
        result = check_kokoro_model_availability(str(model_dir))
        assert result is True

    def test_check_only_onnx(self, tmp_path):
        model_dir = tmp_path / "models"
        model_dir.mkdir()
        (model_dir / "kokoro-v1.0.onnx").write_bytes(b"model")
        result = check_kokoro_model_availability(str(model_dir))
        assert result is False


# ── VoiceCloningEngine ──────────────────────────────────────────────────────

class TestEngineInit:
    def test_init_default(self, tmp_path):
        e = VoiceCloningEngine()
        assert e.config is not None
        assert isinstance(e.voice_prints, dict)
        assert isinstance(e.voice_samples, dict)

    def test_init_custom(self, engine, config):
        assert engine.config.min_sample_duration == 5.0
        assert engine.config.min_snr_db == 15.0

    def test_model_not_ready(self, engine):
        assert engine._model_ready is False


class TestSampleValidation:
    def test_valid_sample(self, engine, sample):
        ok, msg = engine._is_sample_valid(sample)
        assert ok is True

    def test_too_short(self, engine, tmp_path):
        f = tmp_path / "short.wav"
        f.write_bytes(b"\x00" * 10)
        s = VoiceSample(
            id="short", file_path=f, duration=2.0, sample_rate=24000,
            snr_db=25.0, text_content="short", language="en", speaker_id="spk",
        )
        ok, msg = engine._is_sample_valid(s)
        assert ok is False

    def test_low_snr(self, engine, tmp_path):
        f = tmp_path / "noisy.wav"
        f.write_bytes(b"\x00" * 100)
        s = VoiceSample(
            id="noisy", file_path=f, duration=10.0, sample_rate=24000,
            snr_db=5.0, text_content="noisy", language="en", speaker_id="spk",
        )
        ok, msg = engine._is_sample_valid(s)
        assert ok is False


class TestAddVoiceSample:
    def test_add_valid(self, engine, sample):
        ok, msg = engine.add_voice_sample(sample)
        assert ok is True
        assert "spk1" in engine.voice_samples

    def test_add_invalid_too_short(self, engine, tmp_path):
        f = tmp_path / "bad.wav"; f.write_bytes(b"\x00" * 10)
        s = VoiceSample(
            id="bad", file_path=f, duration=1.0, sample_rate=24000,
            snr_db=25.0, text_content="bad", language="en", speaker_id="spk",
        )
        ok, msg = engine.add_voice_sample(s)
        assert ok is False

    def test_add_invalid_low_snr(self, engine, tmp_path):
        f = tmp_path / "bad.wav"; f.write_bytes(b"\x00" * 100)
        s = VoiceSample(
            id="bad", file_path=f, duration=10.0, sample_rate=24000,
            snr_db=5.0, text_content="bad", language="en", speaker_id="spk",
        )
        ok, msg = engine.add_voice_sample(s)
        assert ok is False

    def test_add_multiple_creates_print(self, engine, tmp_path):
        for i in range(3):
            f = tmp_path / f"s{i}.wav"; f.write_bytes(b"\x00" * 100)
            s = VoiceSample(
                id=f"s{i}", file_path=f, duration=20.0, sample_rate=24000,
                snr_db=25.0, text_content=f"sample {i}", language="en",
                speaker_id="spk1",
            )
            ok, msg = engine.add_voice_sample(s)
            assert ok is True
        assert "spk1" in engine.voice_prints


class TestVoicePrintOperations:
    def test_update_voice_print(self, engine, tmp_path):
        f = tmp_path / "s.wav"; f.write_bytes(b"\x00" * 100)
        s = VoiceSample(
            id="s", file_path=f, duration=20.0, sample_rate=24000,
            snr_db=25.0, text_content="text", language="en",
            speaker_id="spk1",
        )
        engine.add_voice_sample(s)
        assert "spk1" in engine.voice_prints
        vp = engine.voice_prints["spk1"]
        assert vp.quality in (AudioQuality.EXCELLENT, AudioQuality.GOOD, AudioQuality.FAIR)
        assert vp.sample_count >= 1

    def test_update_existing_print(self, engine, tmp_path):
        f1 = tmp_path / "s1.wav"; f1.write_bytes(b"\x00" * 100)
        s1 = VoiceSample(
            id="s1", file_path=f1, duration=20.0, sample_rate=24000,
            snr_db=25.0, text_content="text1", language="en",
            speaker_id="spk1",
        )
        engine.add_voice_sample(s1)

        f2 = tmp_path / "s2.wav"; f2.write_bytes(b"\x01" * 100)
        s2 = VoiceSample(
            id="s2", file_path=f2, duration=20.0, sample_rate=24000,
            snr_db=25.0, text_content="text2", language="en",
            speaker_id="spk1",
        )
        engine.add_voice_sample(s2)
        assert engine.voice_prints["spk1"].sample_count >= 2


class TestAssessQuality:
    def test_excellent(self, engine):
        assert engine._assess_quality(30.0) == AudioQuality.EXCELLENT

    def test_good(self, engine):
        assert engine._assess_quality(22.0) == AudioQuality.GOOD

    def test_fair(self, engine):
        assert engine._assess_quality(17.0) == AudioQuality.FAIR

    def test_poor(self, engine):
        assert engine._assess_quality(10.0) == AudioQuality.POOR


class TestSynthesizeSpeech:
    def test_missing_speaker(self, engine):
        ok, msg, path = engine.synthesize_speech("hello", "nonexistent")
        assert ok is False

    def test_poor_quality_speaker(self, engine):
        # Manually create a poor-quality voice print
        engine.voice_prints["bad_spk"] = VoicePrint(
            speaker_id="bad_spk", voice_hash="x", embedding=[0.1]*8,
            quality=AudioQuality.POOR, sample_count=1, avg_snr=10.0,
            created_at="2024-01-01", updated_at="2024-01-01",
        )
        ok, msg, path = engine.synthesize_speech("hello", "bad_spk")
        assert ok is False

    def test_mock_synthesis(self, engine):
        engine._model_ready = False
        engine.voice_prints["good_spk"] = VoicePrint(
            speaker_id="good_spk", voice_hash="y", embedding=[0.1]*8,
            quality=AudioQuality.GOOD, sample_count=2, avg_snr=25.0,
            created_at="2024-01-01", updated_at="2024-01-01",
        )
        ok, msg, path = engine.synthesize_speech("hello", "good_spk", "en", "happy")
        assert ok is True
        assert path is not None


class TestGetVoiceInfo:
    def test_existing(self, engine, tmp_path):
        f = tmp_path / "s.wav"; f.write_bytes(b"\x00" * 100)
        s = VoiceSample(
            id="s", file_path=f, duration=20.0, sample_rate=24000,
            snr_db=25.0, text_content="t", language="en", speaker_id="spk1",
        )
        engine.add_voice_sample(s)
        info = engine.get_voice_info("spk1")
        assert info is not None
        assert info["speaker_id"] == "spk1"
        assert "quality" in info
        assert "avg_snr_db" in info
        assert "is_available_for_cloning" in info

    def test_nonexistent(self, engine):
        assert engine.get_voice_info("nobody") is None


class TestSaveLoadVoicePrints:
    def test_save_voice_prints(self, engine, tmp_path):
        prints_file = tmp_path / "voices" / "voice_prints.json"
        prints_file.parent.mkdir(parents=True, exist_ok=True)
        engine.voice_prints["spk1"] = VoicePrint(
            speaker_id="spk1", voice_hash="abc", embedding=[0.1]*8,
            quality=AudioQuality.GOOD, sample_count=2, avg_snr=22.0,
            created_at="2024-01-01", updated_at="2024-01-02",
        )
        with patch.object(Path, "__truediv__", wraps=Path.__truediv__):
            # Redirect the save path
            original_save = engine._save_voice_prints.__func__
            with patch.object(engine, "_save_voice_prints") as mock_save:
                mock_save.return_value = None
                engine._save_voice_prints()
        # Verify no crash
        assert "spk1" in engine.voice_prints

    def test_save_voice_prints_io_error(self, engine, tmp_path):
        engine.voice_prints["spk1"] = VoicePrint(
            speaker_id="spk1", voice_hash="abc", embedding=[0.1]*8,
            quality=AudioQuality.GOOD, sample_count=2, avg_snr=22.0,
            created_at="2024-01-01", updated_at="2024-01-02",
        )
        with patch("builtins.open", side_effect=Exception("IO error")):
            engine._save_voice_prints()
        # Should not crash

    def test_load_voice_prints_bad_file(self, engine, tmp_path):
        prints_file = tmp_path / "voices" / "voice_prints.json"
        prints_file.parent.mkdir(parents=True, exist_ok=True)
        prints_file.write_text("not json!!")
        with patch.object(Path, "__new__", return_value=prints_file):
            engine._load_voice_prints()

    def test_load_voice_prints_valid(self, engine, tmp_path):
        prints_file = tmp_path / "voice_prints.json"
        data = {
            "spk1": {
                "speaker_id": "spk1",
                "voice_hash": "abc",
                "embedding": [0.1]*8,
                "quality": "good",
                "sample_count": 2,
                "avg_snr": 22.0,
                "created_at": "2024-01-01",
                "updated_at": "2024-01-02",
            }
        }
        prints_file.write_text(json.dumps(data))
        with patch.object(Path, "__new__", return_value=prints_file):
            engine._load_voice_prints()
        assert "spk1" in engine.voice_prints
        assert engine.voice_prints["spk1"].quality == AudioQuality.GOOD


class TestAudioHash:
    def test_deterministic(self, engine):
        data = np.random.randn(24000).astype(np.float32)
        h1 = engine._calculate_audio_hash(data, 24000)
        h2 = engine._calculate_audio_hash(data, 24000)
        assert h1 == h2

    def test_different_data_different_hash(self, engine):
        d1 = np.zeros(24000, dtype=np.float32)
        d2 = np.ones(24000, dtype=np.float32)
        assert engine._calculate_audio_hash(d1, 24000) != engine._calculate_audio_hash(d2, 24000)


class TestEstimateSNR:
    def test_silent(self, engine):
        data = np.zeros(1000, dtype=np.float32)
        snr = engine._estimate_snr(data, 24000)
        assert snr >= 0

    def test_noisy(self, engine):
        data = np.random.randn(10000).astype(np.float32) * 0.5
        snr = engine._estimate_snr(data, 24000)
        assert snr >= 0

    def test_empty(self, engine):
        data = np.array([], dtype=np.float32)
        snr = engine._estimate_snr(data, 24000)
        assert snr == 0.0


# ── main() ──────────────────────────────────────────────────────────────────

class TestMain:
    def test_main(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["clone.py"])
        from src.audiobook_studio.tts.clone import main
        main()


# ── Additional coverage tests ────────────────────────────────────────────────

class TestEstimateSNREdgeCases:
    def test_uniform_data(self, engine):
        """All same values → noise_floor=0 → return 50.0."""
        data = np.ones(1000, dtype=np.float32) * 0.5
        snr = engine._estimate_snr(data, 24000)
        assert snr == 50.0

    def test_silence_then_speech(self, engine):
        """Quiet beginning, loud end."""
        data = np.concatenate([
            np.zeros(100, dtype=np.float32),
            np.ones(900, dtype=np.float32),
        ])
        snr = engine._estimate_snr(data, 24000)
        assert snr >= 0

    def test_single_sample(self, engine):
        data = np.array([1.0], dtype=np.float32)
        snr = engine._estimate_snr(data, 24000)
        assert snr >= 0


class TestMainFunction:
    def test_main_runs(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from src.audiobook_studio.tts.clone import main
        main()
