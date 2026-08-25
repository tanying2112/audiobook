"""Phase 3 isolated coverage tests for ``tts/clone.py``.

Drives the offline-testable voice-cloning business logic without real
Kokoro/ONNX models. soundfile reads and the Kokoro backend are mocked so
the gating/SNR/quality assessment + voice-print update logic is fully
exercised. Heavy global state (model-availability flags) is reset per test.
"""

import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from src.audiobook_studio.tts import clone
from src.audiobook_studio.tts.clone import (
    AudioQuality,
    CloningConfig,
    VoiceCloner,
    VoiceCloningEngine,
    VoicePrint,
    VoiceSample,
)


@pytest.fixture
def clone_env(tmp_path, monkeypatch):
    """Isolate cwd + reset module-level model-availability globals."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(clone, "_KOKORO_MODEL_AVAILABLE", False)
    monkeypatch.setattr(clone, "_KOKORO_MODEL_PATH", None)
    yield tmp_path


def _make_sample(speaker_id, duration=20.0, snr_db=25.0, file_path=Path("x.wav"), sr=24000):
    return VoiceSample(
        id=f"{speaker_id}_1",
        file_path=file_path,
        duration=duration,
        sample_rate=sr,
        snr_db=snr_db,
        text_content="text",
        language="zh-CN",
        speaker_id=speaker_id,
    )


def _make_engine(tmp_path, model_ready=False, model_files=False):
    cfg = CloningConfig(
        model_path=str(tmp_path / "models"),
        output_dir=str(tmp_path / "voices" / "cloned"),
    )
    eng = VoiceCloningEngine(cfg)
    if model_files:
        (tmp_path / "models" / "kokoro-v1.0.onnx").write_bytes(b"x")
        (tmp_path / "models" / "voices-v1.0.bin").write_bytes(b"x")
        # re-run availability check against the real files
        clone.check_kokoro_model_availability(cfg.model_path)
    if model_ready:
        eng._model_ready = True
    return eng


# ── check_kokoro_model_availability / get_kokoro_model_path / is_kokoro_available ──

def test_kokoro_availability_present(clone_env):
    models = clone_env / "models"
    models.mkdir()
    (models / "kokoro-v1.0.onnx").write_bytes(b"x")
    (models / "voices-v1.0.bin").write_bytes(b"x")
    assert clone.check_kokoro_model_availability(str(models)) is True
    assert clone.is_kokoro_available() is True
    assert clone.get_kokoro_model_path() == models


def test_kokoro_availability_alt_names(clone_env):
    models = clone_env / "models"
    models.mkdir()
    (models / "model.onnx").write_bytes(b"x")
    (models / "voices.bin").write_bytes(b"x")
    assert clone.check_kokoro_model_availability(str(models)) is True


def test_kokoro_availability_absent(clone_env):
    models = clone_env / "models_empty"
    models.mkdir()
    assert clone.check_kokoro_model_availability(str(models)) is False
    assert clone.is_kokoro_available() is False
    assert clone.get_kokoro_model_path() is None


# ── extract_voice_features ──

def test_extract_voice_features_normal(monkeypatch):
    arr = np.zeros(4000, dtype=np.float32)
    arr[200:600] = 1.0
    with patch("soundfile.read", return_value=(arr, 24000)):
        feat = clone.extract_voice_features(Path("/tmp/x.wav"), 24000)
    assert feat.shape == (256,)
    assert feat.dtype == np.float32
    assert not np.allclose(feat, 0.5)


def test_extract_voice_features_resample(monkeypatch):
    arr = np.zeros(2000, dtype=np.float32)
    arr[100:300] = 1.0
    with patch("soundfile.read", return_value=(arr, 16000)):
        feat = clone.extract_voice_features(Path("/tmp/x.wav"), 24000)
    assert feat.shape == (256,)


def test_extract_voice_features_error(monkeypatch):
    with patch("soundfile.read", side_effect=RuntimeError("boom")):
        feat = clone.extract_voice_features(Path("/tmp/x.wav"))
    assert np.allclose(feat, 0.5)


# ── VoiceCloner ──

def test_clone_voice_missing_file(clone_env):
    ok, msg, sid = VoiceCloner().clone_voice(Path("nope.wav"), "spk")
    assert ok is False
    assert "样本文件不存在" in msg
    assert sid is None


def test_clone_voice_success(clone_env, monkeypatch):
    sample = clone_env / "sample.wav"
    sample.write_bytes(b"RIFF")
    arr = np.zeros(400000, dtype=np.float32)
    arr[1000:5000] = 1.0
    with patch("soundfile.read", return_value=(arr, 24000)):
        ok, msg, sid = VoiceCloner().clone_voice(sample, "spk")
    assert ok is True
    assert sid == "spk"


def test_get_cloned_voices(clone_env):
    eng = _make_engine(clone_env)
    eng.add_voice_sample(_make_sample("spk", file_path=clone_env / "a.wav"))
    cloner = VoiceCloner(eng)
    voices = cloner.get_cloned_voices()
    assert len(voices) == 1
    assert voices[0]["speaker_id"] == "spk"


# ── VoiceCloningEngine: hash / snr / validation / quality ──

def test_calculate_audio_hash(clone_env):
    eng = _make_engine(clone_env)
    arr = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8], dtype=np.float32)
    h = eng._calculate_audio_hash(arr, 24000)
    assert isinstance(h, str) and len(h) == 64


def test_estimate_snr_empty(clone_env):
    eng = _make_engine(clone_env)
    assert eng._estimate_snr(np.array([]), 24000) == 0.0


def test_estimate_snr_normal(clone_env):
    eng = _make_engine(clone_env)
    arr = np.concatenate([np.zeros(100), np.ones(900)]).astype(np.float32)
    val = eng._estimate_snr(arr, 24000)
    assert isinstance(val, float)
    assert val >= 0.0


def test_is_sample_valid(clone_env):
    eng = _make_engine(clone_env)
    assert eng._is_sample_valid(_make_sample("s", duration=5.0))[0] is False
    assert eng._is_sample_valid(_make_sample("s", snr_db=10.0))[0] is False
    assert eng._is_sample_valid(_make_sample("s", duration=20.0, snr_db=25.0))[0] is True


def test_assess_quality(clone_env):
    eng = _make_engine(clone_env)
    assert eng._assess_quality(30.0) == AudioQuality.EXCELLENT
    assert eng._assess_quality(22.0) == AudioQuality.GOOD
    assert eng._assess_quality(17.0) == AudioQuality.FAIR
    assert eng._assess_quality(5.0) == AudioQuality.POOR


# ── add_voice_sample / _update_voice_print ──

def test_add_voice_sample_invalid(clone_env):
    eng = _make_engine(clone_env)
    ok, msg = eng.add_voice_sample(_make_sample("s", duration=5.0))
    assert ok is False


def test_update_voice_print_no_samples(clone_env):
    eng = _make_engine(clone_env)
    ok, msg = eng._update_voice_print("ghost")
    assert ok is False
    assert "没有有效样本" in msg


def test_update_voice_print_no_valid_samples(clone_env):
    eng = _make_engine(clone_env)
    eng.voice_samples["s"] = [_make_sample("s", duration=5.0, snr_db=10.0)]
    ok, msg = eng._update_voice_print("s")
    assert ok is False
    assert "符合要求" in msg


def test_add_voice_sample_creates_print(clone_env):
    eng = _make_engine(clone_env)
    ok, msg = eng.add_voice_sample(_make_sample("s", file_path=clone_env / "a.wav"))
    assert ok is True
    assert "创建新声音指纹" in msg
    assert "s" in eng.voice_prints
    info = eng.get_voice_info("s")
    assert info is not None
    assert info["is_available_for_cloning"] is True


def test_update_voice_print_update_path(clone_env):
    eng = _make_engine(clone_env)
    eng.add_voice_sample(_make_sample("s", file_path=clone_env / "a.wav"))
    first_hash = eng.voice_prints["s"].voice_hash
    # Add a different sample so the combined hash changes → triggers update branch
    eng.add_voice_sample(_make_sample("s", file_path=clone_env / "b.wav", duration=18.0, snr_db=22.0))
    assert eng.voice_prints["s"].voice_hash != first_hash
    assert eng.voice_prints["s"].sample_count == 2


def test_update_voice_print_no_change(clone_env):
    eng = _make_engine(clone_env)
    eng.add_voice_sample(_make_sample("s", file_path=clone_env / "a.wav"))
    # Re-running the update with an unchanged set of valid samples yields an
    # identical combined hash → hits the "声音指纹无变化" branch.
    ok, msg = eng._update_voice_print("s")
    assert "无变化" in msg


def test_update_voice_print_real_extraction(clone_env, monkeypatch):
    eng = _make_engine(clone_env, model_ready=True)
    f = clone_env / "a.wav"
    f.write_bytes(b"RIFF")
    arr = np.zeros(400000, dtype=np.float32)
    arr[1000:5000] = 1.0
    with patch("soundfile.read", return_value=(arr, 24000)):
        ok, msg = eng.add_voice_sample(_make_sample("s", file_path=f))
    assert ok is True
    # embedding came from extract_voice_features (real branch)
    assert len(eng.voice_prints["s"].embedding) == 256


def test_update_voice_print_exception(clone_env, monkeypatch):
    eng = _make_engine(clone_env)
    monkeypatch.setattr(clone.hashlib, "sha256", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    ok, msg = eng.add_voice_sample(_make_sample("s", file_path=clone_env / "a.wav"))
    assert ok is False
    assert "处理声音样本时出错" in msg


# ── get_voice_info ──

def test_get_voice_info_missing(clone_env):
    eng = _make_engine(clone_env)
    assert eng.get_voice_info("ghost") is None


def test_get_voice_info_poor_not_clonable(clone_env):
    eng = _make_engine(clone_env)
    eng.voice_prints["s"] = VoicePrint(
        speaker_id="s", voice_hash="h", embedding=[0.5] * 256,
        quality=AudioQuality.POOR, sample_count=1, avg_snr=10.0,
        created_at="t", updated_at="t",
    )
    info = eng.get_voice_info("s")
    assert info["quality"] == "poor"
    assert info["is_available_for_cloning"] is False


# ── _select_closest_voice ──

def test_select_closest_voice(clone_env):
    eng = _make_engine(clone_env)
    vp = VoicePrint(
        speaker_id="s", voice_hash="h", embedding=[0.5] * 256, quality=AudioQuality.GOOD,
        sample_count=1, avg_snr=25.0, created_at="t", updated_at="t",
    )
    assert eng._select_closest_voice(vp, "zh-CN") == "zf_xiaoxiao"
    assert eng._select_closest_voice(vp, "en-US") == "af"


# ── synthesize_speech ──

def test_synthesize_speaker_not_found(clone_env):
    eng = _make_engine(clone_env)
    ok, msg, path = eng.synthesize_speech("hi", "ghost")
    assert ok is False
    assert "找不到说话人" in msg
    assert path is None


def test_synthesize_poor_quality(clone_env):
    eng = _make_engine(clone_env)
    eng.voice_prints["s"] = VoicePrint(
        speaker_id="s", voice_hash="h", embedding=[0.5] * 256,
        quality=AudioQuality.POOR, sample_count=1, avg_snr=10.0,
        created_at="t", updated_at="t",
    )
    ok, msg, path = eng.synthesize_speech("hi", "s")
    assert ok is False
    assert "质量太差" in msg


def test_synthesize_model_not_ready(clone_env):
    eng = _make_engine(clone_env)  # _model_ready False
    eng.add_voice_sample(_make_sample("s", duration=20.0, snr_db=25.0, file_path=clone_env / "a.wav"))
    with pytest.raises(RuntimeError):
        eng.synthesize_speech("hi", "s")


class _FakeKokoro:
    def __init__(self, *a, **k):
        self.initialized = False
        self.cleaned = False

    async def initialize(self):
        self.initialized = True

    async def synthesize(self, **kwargs):
        return SimpleNamespace(duration_ms=1234)

    async def cleanup(self):
        self.cleaned = True


def test_synthesize_success(clone_env, monkeypatch):
    import src.audiobook_studio.tts.kokoro_backend as kmod
    monkeypatch.setattr(kmod, "KokoroBackend", _FakeKokoro)
    eng = _make_engine(clone_env, model_ready=True)
    f = clone_env / "a.wav"
    f.write_bytes(b"RIFF")
    eng.add_voice_sample(_make_sample("s", duration=20.0, snr_db=25.0, file_path=f))
    ok, msg, path = eng.synthesize_speech("hi", "s")
    assert ok is True
    assert path is not None
    assert "语音合成成功" in msg


def test_synthesize_success_with_reference(clone_env, monkeypatch):
    import src.audiobook_studio.tts.kokoro_backend as kmod
    monkeypatch.setattr(kmod, "KokoroBackend", _FakeKokoro)
    eng = _make_engine(clone_env, model_ready=True)
    f = clone_env / "a.wav"
    f.write_bytes(b"RIFF")
    eng.add_voice_sample(_make_sample("s", duration=20.0, snr_db=25.0, file_path=f))
    arr = np.zeros(400000, dtype=np.float32)
    arr[1000:5000] = 1.0
    with patch("soundfile.read", return_value=(arr, 24000)):
        ok, msg, path = eng.synthesize_speech("hi", "s", emotion="happy")
    assert ok is True


# ── _load_voice_prints success branch ──

def test_load_voice_prints_from_disk(clone_env):
    voices_dir = clone_env / "voices"
    voices_dir.mkdir()
    (voices_dir / "voice_prints.json").write_text(
        '{"s": {"speaker_id": "s", "voice_hash": "h", "embedding": [0.5], '
        '"quality": "good", "sample_count": 1, "avg_snr": 25.0, '
        '"created_at": "t", "updated_at": "t"}}'
    )
    eng = _make_engine(clone_env)
    assert "s" in eng.voice_prints
    assert eng.voice_prints["s"].quality == AudioQuality.GOOD


# ── _save_voice_prints error branch ──

def test_save_voice_prints_error(clone_env, monkeypatch):
    eng = _make_engine(clone_env)
    monkeypatch.setattr("builtins.open", lambda *a, **k: (_ for _ in ()).throw(OSError("no write")))
    # Should not raise; just logs error
    eng._save_voice_prints()


# ── module-level convenience helpers ──

def test_clone_voice_module_func(clone_env, monkeypatch):
    sample = clone_env / "sample.wav"
    sample.write_bytes(b"RIFF")
    arr = np.zeros(400000, dtype=np.float32)
    arr[1000:5000] = 1.0
    with patch("soundfile.read", return_value=(arr, 24000)):
        ok, msg, sid = clone.clone_voice(sample, "spk")
    assert ok is True


def test_load_voice_print_module_func(clone_env):
    assert clone.load_voice_print("ghost") is None


# ── main() demo ──

def test_main_runs(clone_env, monkeypatch):
    import src.audiobook_studio.tts.kokoro_backend as kmod
    monkeypatch.setattr(kmod, "KokoroBackend", _FakeKokoro)
    monkeypatch.setattr(clone, "check_kokoro_model_availability", lambda *a, **k: True)
    # main() synthesizes with a (faked) ready model → completes without error
    clone.main()


def test_voice_cloning_manager_alias():
    assert clone.VoiceCloningManager is VoiceCloningEngine
