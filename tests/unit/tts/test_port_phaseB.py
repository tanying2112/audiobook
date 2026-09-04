"""Phase B structural tests for tts/port.py (Remote TTS Port contract)."""

import pytest

from src.audiobook_studio.tts.port import (
    RemoteTTSPort,
    TTSProsody,
    TTSStatus,
    TTSTaskPayload,
    TTSTaskResult,
    TTSTaskStatus,
    TTSVoiceAnchor,
)


def test_tts_status_values():
    assert TTSStatus.PENDING.value == "PENDING"
    assert TTSStatus.RUNNING.value == "RUNNING"
    assert TTSStatus.DONE.value == "DONE"
    assert TTSStatus.FAILED.value == "FAILED"
    assert {s.value for s in TTSStatus} == {"PENDING", "RUNNING", "DONE", "FAILED"}


def test_voice_anchor_valid():
    a = TTSVoiceAnchor(voice_id="v1")
    assert a.voice_id == "v1"
    assert a.language == "zh-CN"
    assert a.speaker_name is None
    assert a.reference_audio_path is None


def test_voice_anchor_empty_id_raises():
    with pytest.raises(ValueError):
        TTSVoiceAnchor(voice_id="   ")


def test_voice_anchor_with_reference():
    a = TTSVoiceAnchor(
        voice_id="v2",
        speaker_name="Narrator",
        language="en-US",
        reference_audio_path="/tmp/ref.wav",
    )
    assert a.speaker_name == "Narrator"
    assert a.language == "en-US"
    assert a.reference_audio_path == "/tmp/ref.wav"


def test_prosody_defaults():
    p = TTSProsody()
    assert p.rate == 1.0
    assert p.pitch == 0.0
    assert p.volume == 0.0
    assert p.emotion is None
    assert p.seed is None


def test_prosody_custom():
    p = TTSProsody(rate=1.5, pitch=2.0, volume=-3.0, emotion="happy", seed=42)
    assert p.rate == 1.5
    assert p.pitch == 2.0
    assert p.volume == -3.0
    assert p.emotion == "happy"
    assert p.seed == 42


def test_task_payload_valid():
    anchor = TTSVoiceAnchor(voice_id="v1")
    payload = TTSTaskPayload(text="hello", voice_anchor=anchor)
    assert payload.text == "hello"
    assert payload.voice_anchor is anchor
    assert payload.prosody is None
    assert payload.metadata == {}


def test_task_payload_empty_text_raises():
    anchor = TTSVoiceAnchor(voice_id="v1")
    with pytest.raises(ValueError):
        TTSTaskPayload(text="  ", voice_anchor=anchor)


def test_task_payload_wrong_anchor_type_raises():
    with pytest.raises(TypeError):
        TTSTaskPayload(text="hello", voice_anchor="not-an-anchor")


def test_task_payload_with_prosody_and_metadata():
    anchor = TTSVoiceAnchor(voice_id="v1")
    prosody = TTSProsody(rate=1.2)
    payload = TTSTaskPayload(text="x", voice_anchor=anchor, prosody=prosody, metadata={"k": "v"})
    assert payload.prosody is prosody
    assert payload.metadata == {"k": "v"}


def test_task_result_construction():
    r = TTSTaskResult(
        task_id="t1",
        status=TTSStatus.DONE,
        audio_path="/tmp/out.wav",
        duration_ms=1234,
        dnsmos_score=4.1,
        asr_wer=0.02,
        speaker_similarity=0.95,
        started_at="s",
        completed_at="c",
        metadata={"m": 1},
    )
    assert r.task_id == "t1"
    assert r.status == TTSStatus.DONE
    assert r.audio_path == "/tmp/out.wav"
    assert r.duration_ms == 1234
    assert r.error_message is None
    assert r.dnsmos_score == 4.1
    assert r.asr_wer == 0.02
    assert r.speaker_similarity == 0.95
    assert r.started_at == "s"
    assert r.completed_at == "c"
    assert r.metadata == {"m": 1}


def test_task_status_construction():
    s = TTSTaskStatus(
        task_id="t1",
        status=TTSStatus.RUNNING,
        progress=0.5,
        error_message=None,
        dnsmos_score=3.9,
    )
    assert s.task_id == "t1"
    assert s.status == TTSStatus.RUNNING
    assert s.progress == 0.5
    assert s.dnsmos_score == 3.9


def test_remote_tts_port_is_abstract():
    with pytest.raises(TypeError):
        RemoteTTSPort()
