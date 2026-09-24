"""Tests proving the clone path truly executes against a real backend.

Audit rec #9 (Track B / Pro Studio): when ``real_clone_available()`` is True
(a real VoxCPM2/CosyVoice GPU backend is configured AND answers ``/health``),
``VoiceCloningEngine`` must (a) register the voice as a *real* clone (storing
the 15s reference sample as the anchor) and (b) route actual synthesis to that
backend via ``RemoteVoxCPM2Port``, forwarding the reference audio. Under free +
no-GPU (no endpoint / CLONE_BACKEND_DISABLED) it must stay honest preset and
never claim a real clone.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from src.audiobook_studio.tts import clone as clone_mod
from src.audiobook_studio.tts.clone import VoiceCloningEngine, VoiceSample, _real_clone_backend, real_clone_available
from src.audiobook_studio.tts.port import TTSStatus, TTSTaskResult, TTSTaskStatus


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch, tmp_path):
    """Reset probe cache + env, and isolate cwd so we never touch ./voices."""
    clone_mod._CLONE_AVAILABLE_CACHE = None
    clone_mod._CLONE_PROBE_TS = 0.0
    monkeypatch.delenv("VOXCPM2_ENDPOINT", raising=False)
    monkeypatch.delenv("COSYVOICE_ENDPOINT", raising=False)
    monkeypatch.delenv("CLONE_BACKEND_DISABLED", raising=False)
    monkeypatch.chdir(tmp_path)
    yield
    clone_mod._CLONE_AVAILABLE_CACHE = None
    clone_mod._CLONE_PROBE_TS = 0.0


def _make_sample(path: Path, speaker_id: str = "spk1") -> VoiceSample:
    return VoiceSample(
        id=f"{speaker_id}_s1",
        file_path=path,
        duration=15.0,
        sample_rate=24000,
        snr_db=25.0,
        text_content="这是克隆样本。",
        language="zh-CN",
        speaker_id=speaker_id,
    )


class _FakeClonePort:
    """Minimal async stand-in for RemoteVoxCPM2Port that records the payload."""

    def __init__(self):
        self.submitted = []
        self.closed = False
        self.result_audio: str | None = None

    async def submit(self, task_id, payload):
        self.submitted.append((task_id, payload))
        return True

    async def get_status(self, task_id):
        return TTSTaskStatus(task_id=task_id, status=TTSStatus.DONE)

    async def get_result(self, task_id):
        return TTSTaskResult(task_id=task_id, status=TTSStatus.DONE, audio_path=self.result_audio)

    async def close(self):
        self.closed = True


def test_real_backend_absent_is_honest_preset(monkeypatch):
    assert real_clone_available() is False
    assert _real_clone_backend() == (False, None)


def test_clone_backend_disabled_stays_preset(monkeypatch):
    monkeypatch.setenv("VOXCPM2_ENDPOINT", "http://voxcpm2:5010")
    monkeypatch.setenv("CLONE_BACKEND_DISABLED", "true")
    assert real_clone_available() is False
    assert _real_clone_backend() == (False, None)


def test_add_voice_sample_tags_real_clone_when_available(monkeypatch, tmp_path):
    sample_wav = tmp_path / "ref.wav"
    sample_wav.write_bytes(b"RIFFfakewavdata")
    monkeypatch.setenv("VOXCPM2_ENDPOINT", "http://voxcpm2:5010")
    with patch.object(clone_mod, "_probe_endpoint_health", lambda url: True):
        assert real_clone_available() is True
        assert _real_clone_backend() == (True, "voxcpm2")

        engine = VoiceCloningEngine()
        ok, msg = engine.add_voice_sample(_make_sample(sample_wav))
        assert ok is True
        vp = engine.voice_prints["spk1"]
        assert vp.is_real_clone is True
        assert vp.clone_backend == "voxcpm2"
        assert vp.feature_method == "real_remote_clone"
        assert vp.reference_audio_path == str(sample_wav)
        assert vp.embedding == []  # 真实声纹由后端持有，本地不伪称
        info = engine.get_voice_info("spk1")
        assert info["clone_mode"] == "clone"
        assert info["is_real_clone"] is True


def test_synthesize_routes_to_real_backend_and_forwards_reference(monkeypatch, tmp_path):
    sample_wav = tmp_path / "ref.wav"
    sample_wav.write_bytes(b"RIFFfakewavdata")
    result_wav = tmp_path / "result.wav"
    result_wav.write_bytes(b"RIFFresultwavdata")

    monkeypatch.setenv("VOXCPM2_ENDPOINT", "http://voxcpm2:5010")
    with patch.object(clone_mod, "_probe_endpoint_health", lambda url: True):
        from src.audiobook_studio.tts import remote_voxcpm2_port as remote_mod

        fake = _FakeClonePort()
        fake.result_audio = str(result_wav)
        monkeypatch.setattr(remote_mod, "create_remote_voxcpm2_port", lambda: fake)

        engine = VoiceCloningEngine()
        ok, _ = engine.add_voice_sample(_make_sample(sample_wav))
        assert ok is True

        ok, msg, audio_path = engine.synthesize_speech(
            "你好，这是真实克隆。", "spk1", language="zh-CN", emotion="neutral"
        )
        assert ok is True
        assert audio_path is not None and Path(audio_path).exists()
        # The real backend was actually called exactly once...
        assert len(fake.submitted) == 1
        task_id, payload = fake.submitted[0]
        # ...and the stored 15s reference sample was forwarded as the anchor.
        assert payload.voice_anchor.reference_audio_path == str(sample_wav)
        assert payload.text == "你好，这是真实克隆。"
        assert fake.closed is True  # port owned by synthesize_real_clone was closed


def test_real_clone_unavailable_at_synth_time_raises(monkeypatch, tmp_path):
    """A voice registered as real but whose backend is now down must fail honestly."""
    sample_wav = tmp_path / "ref.wav"
    sample_wav.write_bytes(b"RIFFfakewavdata")
    monkeypatch.setenv("VOXCPM2_ENDPOINT", "http://voxcpm2:5010")
    with patch.object(clone_mod, "_probe_endpoint_health", lambda url: True):
        engine = VoiceCloningEngine()
        ok, _ = engine.add_voice_sample(_make_sample(sample_wav))
        assert ok is True

    # Backend goes away: probe now reports unavailable.
    clone_mod._CLONE_AVAILABLE_CACHE = None
    clone_mod._CLONE_PROBE_TS = 0.0
    with patch.object(clone_mod, "_probe_endpoint_health", lambda url: False):
        assert real_clone_available() is False
        with pytest.raises(RuntimeError):
            engine.synthesize_speech("x", "spk1")


def test_no_endpoint_add_sample_is_preset(monkeypatch, tmp_path):
    sample_wav = tmp_path / "ref.wav"
    sample_wav.write_bytes(b"RIFFfakewavdata")
    engine = VoiceCloningEngine()
    ok, _ = engine.add_voice_sample(_make_sample(sample_wav))
    assert ok is True
    vp = engine.voice_prints["spk1"]
    assert vp.is_real_clone is False
    assert vp.feature_method == "spectral_centroid_placeholder"
    assert vp.reference_audio_path is None
    assert engine.get_voice_info("spk1")["clone_mode"] == "preset"
