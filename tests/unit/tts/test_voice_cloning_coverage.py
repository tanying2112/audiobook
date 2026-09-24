"""Phase 3 isolated coverage tests for ``tts/voice_cloning.py``.

Drives the offline VoiceCloningManager logic (hash/SNR/quality assessment,
voice-print update, async kokoro synthesis) without real ONNX models.
soundfile reads and the Kokoro backend are mocked.
"""

import asyncio
import builtins
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

import src.audiobook_studio.tts.kokoro_backend as kokoro_backend_mod
from src.audiobook_studio.tts import voice_cloning
from src.audiobook_studio.tts.voice_cloning import (
    AudioQuality,
    CloningConfig,
    VoiceCloningManager,
    VoicePrint,
    VoiceSample,
)


@pytest.fixture
def vc_env(tmp_path, monkeypatch):
    """Isolate cwd so the manager writes ./voices ./models under tmp."""
    monkeypatch.chdir(tmp_path)
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


def _make_manager(tmp_path, model_files=False):
    cfg = CloningConfig(
        model_path=str(tmp_path / "models"),
        output_dir=str(tmp_path / "voices" / "cloned"),
    )
    mgr = VoiceCloningManager(cfg)
    if model_files:
        (tmp_path / "models" / "kokoro-v1.0.onnx").write_bytes(b"x")
        (tmp_path / "models" / "voices-v1.0.bin").write_bytes(b"x")
    return mgr


# ── _extract_real_embedding ──


def test_extract_real_embedding_normal(vc_env, monkeypatch):
    f = vc_env / "a.wav"
    f.write_bytes(b"RIFF")
    arr = np.zeros(2000, dtype=np.float32)
    arr[100:600] = 1.0
    with patch("soundfile.read", return_value=(arr, 24000)):
        emb = VoiceCloningManager()._extract_real_embedding(_make_sample("s", file_path=f))
    assert len(emb) == 256
    assert not all(v == 0.5 for v in emb)


def test_extract_real_embedding_resample(vc_env, monkeypatch):
    f = vc_env / "a.wav"
    f.write_bytes(b"RIFF")
    arr = np.zeros(1000, dtype=np.float32)
    arr[50:200] = 1.0
    with patch("soundfile.read", return_value=(arr, 16000)):
        emb = VoiceCloningManager()._extract_real_embedding(_make_sample("s", file_path=f))
    assert len(emb) == 256


def test_extract_real_embedding_short(vc_env, monkeypatch):
    f = vc_env / "a.wav"
    f.write_bytes(b"RIFF")
    arr = np.zeros(50, dtype=np.float32)
    arr[10:20] = 1.0
    with patch("soundfile.read", return_value=(arr, 24000)):
        emb = VoiceCloningManager()._extract_real_embedding(_make_sample("s", file_path=f))
    assert len(emb) == 256


def test_extract_real_embedding_exception(vc_env, monkeypatch):
    f = vc_env / "a.wav"
    f.write_bytes(b"RIFF")
    with patch("soundfile.read", side_effect=RuntimeError("boom")):
        emb = VoiceCloningManager()._extract_real_embedding(_make_sample("s", file_path=f))
    assert emb == [0.5] * 256


# ── hash / snr / validation / quality ──


def test_calculate_audio_hash(vc_env):
    mgr = _make_manager(vc_env)
    arr = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8], dtype=np.float32)
    h = mgr._calculate_audio_hash(arr, 24000)
    assert isinstance(h, str) and len(h) == 64


def test_estimate_snr_empty(vc_env):
    mgr = _make_manager(vc_env)
    assert mgr._estimate_snr(np.array([]), 24000) == 0.0


def test_estimate_snr_normal(vc_env):
    mgr = _make_manager(vc_env)
    arr = np.concatenate([np.zeros(100), np.ones(900)]).astype(np.float32)
    val = mgr._estimate_snr(arr, 24000)
    assert val >= 0.0


def test_is_sample_valid(vc_env):
    mgr = _make_manager(vc_env)
    assert mgr._is_sample_valid(_make_sample("s", duration=5.0))[0] is False
    assert mgr._is_sample_valid(_make_sample("s", snr_db=10.0))[0] is False
    assert mgr._is_sample_valid(_make_sample("s", duration=20.0, snr_db=25.0))[0] is True


def test_assess_quality(vc_env):
    mgr = _make_manager(vc_env)
    assert mgr._assess_quality(30.0) == AudioQuality.EXCELLENT
    assert mgr._assess_quality(22.0) == AudioQuality.GOOD
    assert mgr._assess_quality(17.0) == AudioQuality.FAIR
    assert mgr._assess_quality(5.0) == AudioQuality.POOR


# ── _load / _save voice prints ──


def test_load_voice_prints_success(vc_env):
    voices = vc_env / "voices"
    voices.mkdir()
    (voices / "voice_prints.json").write_text(
        json.dumps(
            {
                "s": {
                    "speaker_id": "s",
                    "voice_hash": "h",
                    "embedding": [0.5],
                    "quality": "good",
                    "sample_count": 1,
                    "avg_snr": 25.0,
                    "created_at": "t",
                    "updated_at": "t",
                }
            }
        )
    )
    mgr = _make_manager(vc_env)
    assert "s" in mgr.voice_prints
    assert mgr.voice_prints["s"].quality == AudioQuality.GOOD


def test_load_voice_prints_corrupt(vc_env):
    voices = vc_env / "voices"
    voices.mkdir()
    (voices / "voice_prints.json").write_text("{not valid json")
    mgr = _make_manager(vc_env)  # should not raise, just warns
    assert mgr.voice_prints == {}


def test_save_voice_prints_success(vc_env):
    mgr = _make_manager(vc_env)
    mgr.add_voice_sample(_make_sample("s", file_path=vc_env / "a.wav"))
    saved = Path("./voices/voice_prints.json").read_text()
    assert "s" in saved


def test_save_voice_prints_error(vc_env, monkeypatch):
    mgr = _make_manager(vc_env)
    monkeypatch.setattr("builtins.open", lambda *a, **k: (_ for _ in ()).throw(OSError("no write")))
    mgr._save_voice_prints()  # should not raise


# ── add_voice_sample / _update_voice_print ──


def test_add_voice_sample_invalid(vc_env):
    mgr = _make_manager(vc_env)
    ok, msg = mgr.add_voice_sample(_make_sample("s", duration=5.0))
    assert ok is False


def test_update_voice_print_no_samples(vc_env):
    mgr = _make_manager(vc_env)
    ok, msg = mgr._update_voice_print("ghost")
    assert ok is False
    assert "没有有效样本" in msg


def test_update_voice_print_no_valid_samples(vc_env):
    mgr = _make_manager(vc_env)
    mgr.voice_samples["s"] = [_make_sample("s", duration=5.0, snr_db=10.0)]
    ok, msg = mgr._update_voice_print("s")
    assert ok is False
    assert "符合要求" in msg


def test_add_voice_sample_creates_print(vc_env):
    mgr = _make_manager(vc_env)
    ok, msg = mgr.add_voice_sample(_make_sample("s", file_path=vc_env / "a.wav"))
    assert ok is True
    assert "创建新声音指纹" in msg
    assert "s" in mgr.voice_prints


def test_update_voice_print_update_path(vc_env):
    mgr = _make_manager(vc_env)
    mgr.add_voice_sample(_make_sample("s", file_path=vc_env / "a.wav"))
    first_hash = mgr.voice_prints["s"].voice_hash
    mgr.add_voice_sample(_make_sample("s", file_path=vc_env / "b.wav", duration=18.0, snr_db=22.0))
    assert mgr.voice_prints["s"].voice_hash != first_hash
    assert mgr.voice_prints["s"].sample_count == 2


def test_update_voice_print_no_change(vc_env):
    mgr = _make_manager(vc_env)
    mgr.add_voice_sample(_make_sample("s", file_path=vc_env / "a.wav"))
    ok, msg = mgr._update_voice_print("s")
    assert "无变化" in msg


def test_update_voice_print_exception(vc_env, monkeypatch):
    mgr = _make_manager(vc_env)
    monkeypatch.setattr("hashlib.sha256", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    ok, msg = mgr.add_voice_sample(_make_sample("s", file_path=vc_env / "a.wav"))
    assert ok is False
    assert "处理声音样本时出错" in msg


# ── get_voice_info ──


def test_get_voice_info_missing(vc_env):
    mgr = _make_manager(vc_env)
    assert mgr.get_voice_info("ghost") is None


def test_get_voice_info_poor_not_clonable(vc_env):
    mgr = _make_manager(vc_env)
    mgr.voice_prints["s"] = VoicePrint(
        speaker_id="s",
        voice_hash="h",
        embedding=[0.5] * 256,
        quality=AudioQuality.POOR,
        sample_count=1,
        avg_snr=10.0,
        created_at="t",
        updated_at="t",
    )
    info = mgr.get_voice_info("s")
    assert info["quality"] == "poor"
    assert info["is_available_for_cloning"] is False


# ── async kokoro synthesis ──


class _FakeKokoroWrite:
    def __init__(self, *a, **k):
        self.initialized = False
        self.cleaned = False

    async def initialize(self):
        self.initialized = True

    async def synthesize(self, **kwargs):
        Path(kwargs["output_path"]).write_bytes(b"x")
        return SimpleNamespace(duration_ms=1234)

    async def cleanup(self):
        self.cleaned = True


class _FakeKokoroNoWrite:
    def __init__(self, *a, **k):
        pass

    async def initialize(self):
        pass

    async def synthesize(self, **kwargs):
        return SimpleNamespace(duration_ms=1234)

    async def cleanup(self):
        pass


class _FakeKokoroFileNotFound:
    def __init__(self, *a, **k):
        pass

    async def initialize(self):
        raise FileNotFoundError("no model")

    async def synthesize(self, **kwargs):
        return SimpleNamespace(duration_ms=1)

    async def cleanup(self):
        pass


class _FakeKokoroRaise:
    def __init__(self, *a, **k):
        pass

    async def initialize(self):
        pass

    async def synthesize(self, **kwargs):
        raise Exception("boom")

    async def cleanup(self):
        pass


def test_async_synthesize_success(vc_env, monkeypatch):
    monkeypatch.setattr(kokoro_backend_mod, "KokoroBackend", _FakeKokoroWrite)
    mgr = _make_manager(vc_env)
    mgr.add_voice_sample(_make_sample("s", file_path=vc_env / "a.wav"))
    out = vc_env / "out.wav"
    ok, msg, path = asyncio.run(mgr._async_synthesize_with_kokoro("hi", "s", "zh-CN", "happy", out))
    assert ok is True
    assert path == out


def test_async_synthesize_empty_output(vc_env, monkeypatch):
    monkeypatch.setattr(kokoro_backend_mod, "KokoroBackend", _FakeKokoroNoWrite)
    mgr = _make_manager(vc_env)
    mgr.add_voice_sample(_make_sample("s", file_path=vc_env / "a.wav"))
    out = vc_env / "out.wav"
    ok, msg, path = asyncio.run(mgr._async_synthesize_with_kokoro("hi", "s", "zh-CN", "happy", out))
    assert ok is False
    assert "输出文件为空" in msg


def test_async_synthesize_file_not_found(vc_env, monkeypatch):
    monkeypatch.setattr(kokoro_backend_mod, "KokoroBackend", _FakeKokoroFileNotFound)
    mgr = _make_manager(vc_env)
    mgr.add_voice_sample(_make_sample("s", file_path=vc_env / "a.wav"))
    out = vc_env / "out.wav"
    ok, msg, path = asyncio.run(mgr._async_synthesize_with_kokoro("hi", "s", "zh-CN", "happy", out))
    assert ok is False
    assert "模型文件缺失" in msg


def test_async_synthesize_generic_exception(vc_env, monkeypatch):
    monkeypatch.setattr(kokoro_backend_mod, "KokoroBackend", _FakeKokoroRaise)
    mgr = _make_manager(vc_env)
    mgr.add_voice_sample(_make_sample("s", file_path=vc_env / "a.wav"))
    out = vc_env / "out.wav"
    ok, msg, path = asyncio.run(mgr._async_synthesize_with_kokoro("hi", "s", "zh-CN", "happy", out))
    assert ok is False
    assert "合成失败: boom" in msg


def test_async_synthesize_import_error(vc_env, monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name.endswith("kokoro_backend"):
            raise ImportError("no module")
        return real_import(name, *a, **k)

    monkeypatch.setattr("builtins.__import__", fake_import)
    mgr = _make_manager(vc_env)
    out = vc_env / "out.wav"
    ok, msg, path = asyncio.run(mgr._async_synthesize_with_kokoro("hi", "s", "zh-CN", "happy", out))
    assert ok is False
    assert "依赖缺失" in msg


# ── synthesize_speech ──


def test_synthesize_speaker_not_found(vc_env):
    mgr = _make_manager(vc_env)
    ok, msg, path = mgr.synthesize_speech("hi", "ghost")
    assert ok is False
    assert "找不到说话人" in msg
    assert path is None


def test_synthesize_poor(vc_env):
    mgr = _make_manager(vc_env)
    mgr.voice_prints["s"] = VoicePrint(
        speaker_id="s",
        voice_hash="h",
        embedding=[0.5] * 256,
        quality=AudioQuality.POOR,
        sample_count=1,
        avg_snr=10.0,
        created_at="t",
        updated_at="t",
    )
    ok, msg, path = mgr.synthesize_speech("hi", "s")
    assert ok is False
    assert "质量太差" in msg


def test_synthesize_success(vc_env, monkeypatch):
    monkeypatch.setattr(kokoro_backend_mod, "KokoroBackend", _FakeKokoroWrite)
    mgr = _make_manager(vc_env)
    mgr.add_voice_sample(_make_sample("s", file_path=vc_env / "a.wav"))
    ok, msg, path = mgr.synthesize_speech("hi", "s")
    assert ok is True
    assert path is not None
    assert "语音合成成功" in msg


def test_synthesize_raises_on_failure(vc_env, monkeypatch):
    monkeypatch.setattr(kokoro_backend_mod, "KokoroBackend", _FakeKokoroRaise)
    mgr = _make_manager(vc_env)
    mgr.add_voice_sample(_make_sample("s", file_path=vc_env / "a.wav"))
    with pytest.raises(RuntimeError):
        mgr.synthesize_speech("hi", "s")


# ── main() demo ──


def test_main_runs(vc_env, monkeypatch):
    monkeypatch.setattr(kokoro_backend_mod, "KokoroBackend", _FakeKokoroWrite)
    voice_cloning.main()


def test_voice_cloning_manager_alias():
    assert voice_cloning.VoiceCloningManager is VoiceCloningManager
