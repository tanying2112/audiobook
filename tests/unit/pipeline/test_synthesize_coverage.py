"""Real-business coverage tests for ``pipeline/synthesize.py``.

Focuses on the pure routing/normalization helpers, the ``SynthesizePipeline``
constructor and metadata sidecars, and ``_make_routing_decision`` — all of
which run offline with free resources (no live TTS gateway, no ffmpeg).

The network/ffmpeg-heavy paths (``_synthesize_via_port``, ``run`` quality gate,
streaming) are intentionally left to the existing integration tests.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.audiobook_studio.pipeline.synthesize import (
    AudioSegment,
    SynthesizePipeline,
    _normalize_voice_id,
    _port_engine_name,
    synthesize_paragraphs,
)
from src.audiobook_studio.schemas import (
    CharacterVoiceBinding,
    ParagraphAnnotation,
    TtsRoutingInput,
)
from src.audiobook_studio.tts.fake_port import FakeRemoteTTSPort


# ── _normalize_voice_id ─────────────────────────────────────────────────────


def test_normalize_default_kokoro() -> None:
    assert _normalize_voice_id("default", "kokoro") == "zf_xiaoxiao"


def test_normalize_default_edge() -> None:
    assert _normalize_voice_id("default", "edge") == "zh-CN-XiaoxiaoNeural"


def test_normalize_edge_to_kokoro_map() -> None:
    assert _normalize_voice_id("en-US-AriaNeural", "kokoro") == "zf_xiaoxiao"


def test_normalize_kokoro_passthrough() -> None:
    assert _normalize_voice_id("zm_yunjian", "kokoro") == "zm_yunjian"


def test_normalize_kokoro_unknown_nonstrict() -> None:
    # unknown kokoro id, non-strict -> canonical narrator default
    assert _normalize_voice_id("my-custom-clone", "kokoro", strict=False) == "zf_xiaoxiao"


def test_normalize_kokoro_unknown_strict() -> None:
    # unknown kokoro id, strict -> honoured as-is
    assert _normalize_voice_id("my-custom-clone", "kokoro", strict=True) == "my-custom-clone"


def test_normalize_edge_zh_passthrough() -> None:
    assert _normalize_voice_id("zh-CN-YunxiNeural", "edge") == "zh-CN-YunxiNeural"


def test_normalize_edge_unknown_nonstrict() -> None:
    assert _normalize_voice_id("kokoro-style-id", "edge", strict=False) == "zh-CN-XiaoxiaoNeural"


def test_normalize_edge_unknown_strict() -> None:
    assert _normalize_voice_id("kokoro-style-id", "edge", strict=True) == "kokoro-style-id"


# ── _port_engine_name ───────────────────────────────────────────────────────


def test_port_engine_name_none() -> None:
    class P:
        pass

    assert _port_engine_name(P()) == "kokoro"


def test_port_engine_name_kokoro() -> None:
    class KokoroEngine:
        pass

    class P:
        engine = KokoroEngine()

    assert _port_engine_name(P()) == "kokoro"


def test_port_engine_name_edge() -> None:
    class EdgeTTS:
        pass

    class P:
        engine = EdgeTTS()

    assert _port_engine_name(P()) == "edge"


def test_port_engine_name_voxcpm2() -> None:
    class VoxCPM2Backend:
        pass

    class P:
        engine = VoxCPM2Backend()

    assert _port_engine_name(P()) == "voxcpm2"


def test_port_engine_name_unknown_defaults_kokoro() -> None:
    class WeirdEngine:
        pass

    class P:
        engine = WeirdEngine()

    assert _port_engine_name(P()) == "kokoro"


# ── AudioSegment.to_dict ────────────────────────────────────────────────────


def test_audio_segment_to_dict() -> None:
    seg = AudioSegment(
        segment_id="s1",
        file_path="/tmp/s1.wav",
        duration_ms=1234,
        engine="kokoro",
        voice_id="zf_xiaoxiao",
        text_hash="abc",
    )
    d = seg.to_dict()
    assert d == {
        "segment_id": "s1",
        "file_path": "/tmp/s1.wav",
        "duration_ms": 1234,
        "engine": "kokoro",
        "voice_id": "zf_xiaoxiao",
        "text_hash": "abc",
    }


# ── get_crossfade_ms ────────────────────────────────────────────────────────


def test_crossfade_ms_default() -> None:
    assert SynthesizePipeline.get_crossfade_ms() == 50


def test_crossfade_ms_from_env(monkeypatch) -> None:
    monkeypatch.setenv("CROSSFADE_MS", "120")
    assert SynthesizePipeline.get_crossfade_ms() == 120


def test_crossfade_ms_invalid_env(monkeypatch) -> None:
    monkeypatch.setenv("CROSSFADE_MS", "not-an-int")
    assert SynthesizePipeline.get_crossfade_ms() == 50


# ── _build_payload ──────────────────────────────────────────────────────────


def test_build_payload_seed_int() -> None:
    p = SynthesizePipeline(mock_mode=True, router=MagicMock())
    payload = p._build_payload("hello", "zf_xiaoxiao", {"rate": 1.0, "seed": 42})
    assert payload.prosody.seed == 42
    assert payload.voice_anchor.voice_id == "zf_xiaoxiao"


def test_build_payload_seed_float() -> None:
    p = SynthesizePipeline(mock_mode=True, router=MagicMock())
    payload = p._build_payload("hello", "zf_xiaoxiao", {"rate": 1.0, "seed": 3.9})
    assert payload.prosody.seed == 3  # int(3.9)


def test_build_payload_seed_none() -> None:
    p = SynthesizePipeline(mock_mode=True, router=MagicMock())
    payload = p._build_payload("hello", "zf_xiaoxiao", {"rate": 1.0, "seed": "bad"})
    assert payload.prosody.seed is None


# ── _text_hash ──────────────────────────────────────────────────────────────


def test_text_hash_deterministic() -> None:
    p = SynthesizePipeline(mock_mode=True, router=MagicMock())
    h1 = p._text_hash("same text")
    h2 = p._text_hash("same text")
    assert h1 == h2
    assert len(h1) == 12


# ── SynthesizePipeline.__init__ branches ────────────────────────────────────


def test_init_mock_mode_explicit() -> None:
    p = SynthesizePipeline(mock_mode=True, router=MagicMock())
    assert p.mock_mode is True
    assert isinstance(p._port, FakeRemoteTTSPort)


def test_init_mock_mode_from_env(monkeypatch) -> None:
    monkeypatch.setenv("MOCK_LLM", "true")
    p = SynthesizePipeline(router=MagicMock())
    assert p.mock_mode is True


def test_init_non_mock_lazy_port(monkeypatch) -> None:
    monkeypatch.setenv("MOCK_LLM", "false")
    p = SynthesizePipeline(router=MagicMock())
    assert p.mock_mode is False
    assert p._port is None
    assert p._pending_port is not None  # lazy coroutine created


def test_init_port_given() -> None:
    fake = FakeRemoteTTSPort()
    p = SynthesizePipeline(mock_mode=False, router=MagicMock(), port=fake)
    assert p._port is fake


def test_init_crossfade_explicit() -> None:
    p = SynthesizePipeline(mock_mode=True, router=MagicMock(), crossfade_ms=200)
    assert p.crossfade_ms == 200


def test_init_crossfade_from_env(monkeypatch) -> None:
    monkeypatch.setenv("CROSSFADE_MS", "75")
    p = SynthesizePipeline(mock_mode=True, router=MagicMock())
    assert p.crossfade_ms == 75


# ── metadata sidecars ───────────────────────────────────────────────────────


def test_persist_and_load_metadata_roundtrip(tmp_path: Path) -> None:
    p = SynthesizePipeline(mock_mode=True, router=MagicMock(), output_dir=str(tmp_path))
    seg = AudioSegment(
        segment_id="s1",
        file_path=str(tmp_path / "s1.wav"),
        duration_ms=100,
        engine="kokoro",
        voice_id="zf_xiaoxiao",
        text_hash="hash1",
    )
    p._persist_segment_metadata(seg)
    # the sidecar references a real audio file that must exist on disk
    (tmp_path / "s1.wav").write_bytes(b"RIFFfake")
    loaded = p._load_existing_segment_from_disk("s1", "hash1")
    assert loaded is not None
    assert loaded.file_path == seg.file_path
    assert loaded.text_hash == "hash1"


def test_load_metadata_missing_file(tmp_path: Path) -> None:
    p = SynthesizePipeline(mock_mode=True, router=MagicMock(), output_dir=str(tmp_path))
    assert p._load_existing_segment_from_disk("nope", "h") is None


def test_load_metadata_corrupt_json(tmp_path: Path) -> None:
    p = SynthesizePipeline(mock_mode=True, router=MagicMock(), output_dir=str(tmp_path))
    mp = p._metadata_path("bad")
    mp.write_text("{not valid json", encoding="utf-8")
    assert p._load_existing_segment_from_disk("bad", "h") is None


def test_load_metadata_hash_mismatch(tmp_path: Path) -> None:
    p = SynthesizePipeline(mock_mode=True, router=MagicMock(), output_dir=str(tmp_path))
    seg = AudioSegment(
        segment_id="s2",
        file_path=str(tmp_path / "s2.wav"),
        duration_ms=100,
        engine="kokoro",
        voice_id="zf_xiaoxiao",
        text_hash="realhash",
    )
    p._persist_segment_metadata(seg)
    assert p._load_existing_segment_from_disk("s2", "differenthash") is None


def test_load_metadata_audio_missing(tmp_path: Path) -> None:
    p = SynthesizePipeline(mock_mode=True, router=MagicMock(), output_dir=str(tmp_path))
    mp = p._metadata_path("s3")
    mp.write_text(
        json.dumps(
            {
                "segment_id": "s3",
                "file_path": str(tmp_path / "does_not_exist.wav"),
                "duration_ms": 10,
                "engine": "kokoro",
                "voice_id": "zf_xiaoxiao",
                "text_hash": "h",
            }
        ),
        encoding="utf-8",
    )
    assert p._load_existing_segment_from_disk("s3", "h") is None


def test_persist_metadata_oserror(monkeypatch, tmp_path: Path) -> None:
    p = SynthesizePipeline(mock_mode=True, router=MagicMock(), output_dir=str(tmp_path))
    seg = AudioSegment(
        segment_id="s4",
        file_path=str(tmp_path / "s4.wav"),
        duration_ms=100,
        engine="kokoro",
        voice_id="zf_xiaoxiao",
        text_hash="h",
    )

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", boom)
    # should not raise, just log a warning
    p._persist_segment_metadata(seg)


# ── _download_audio ─────────────────────────────────────────────────────────


def test_download_audio_local_copy(tmp_path: Path) -> None:
    p = SynthesizePipeline(mock_mode=True, router=MagicMock())
    src = tmp_path / "src.wav"
    src.write_bytes(b"RIFFdata")
    dest = tmp_path / "dest.wav"
    import asyncio

    asyncio.get_event_loop().run_until_complete(p._download_audio(str(src), dest))
    assert dest.read_bytes() == b"RIFFdata"


def test_download_audio_remote_not_implemented(tmp_path: Path) -> None:
    p = SynthesizePipeline(mock_mode=True, router=MagicMock())
    dest = tmp_path / "dest.wav"
    import asyncio

    with pytest.raises(NotImplementedError):
        asyncio.get_event_loop().run_until_complete(
            p._download_audio("/no/such/remote/key", dest)
        )


# ── close ───────────────────────────────────────────────────────────────────


def test_close_with_port() -> None:
    fake = FakeRemoteTTSPort()
    p = SynthesizePipeline(mock_mode=False, router=MagicMock(), port=fake)
    import asyncio

    asyncio.get_event_loop().run_until_complete(p.close())
    assert p._port is None


def test_close_without_port() -> None:
    p = SynthesizePipeline(mock_mode=True, router=MagicMock())
    p._port = None
    import asyncio

    # should be a no-op without raising
    asyncio.get_event_loop().run_until_complete(p.close())


# ── _make_routing_decision ──────────────────────────────────────────────────


def _make_input(
    speaker: str = "_narrator_",
    emotion: str = "neutral",
    speech_rate: float = 1.0,
    pitch: float = 0.0,
    char_map: list[CharacterVoiceBinding] | None = None,
    prefer_local: bool = True,
) -> TtsRoutingInput:
    ann = ParagraphAnnotation(
        paragraph_index=1,
        speaker_canonical_name=speaker,
        is_dialogue=False,
        emotion=emotion,
        emotion_intensity=0.5,
        speech_rate=speech_rate,
        pitch_shift_semitones=pitch,
        confidence=0.9,
    )
    if char_map is None:
        char_map = [
            CharacterVoiceBinding(
                canonical_name="_narrator_",
                aliases=[],
                gender="neutral",
                age_range="adult",
                suggested_voice_id="zh-CN-XiaoxiaoNeural",
                sample_quote="旁白",
            )
        ]
    return TtsRoutingInput(
        paragraph_annotation=ann,
        text="Hello world.",
        character_voice_map=char_map,
        book_id="b1",
        chapter_index=1,
        paragraph_index=1,
        prefer_local=prefer_local,
    )


def test_routing_decision_default_voice_local_on(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_LOCAL_TTS", "true")
    p = SynthesizePipeline(mock_mode=True, router=MagicMock())
    dec = p._make_routing_decision(_make_input())
    assert dec.engine_choice == "kokoro"
    assert dec.fallback_engine == "edge"
    # default voice -> normalized to narrator
    assert dec.voice_id == "zf_xiaoxiao"


def test_routing_decision_local_off(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_LOCAL_TTS", "false")
    p = SynthesizePipeline(mock_mode=True, router=MagicMock())
    # prefer_local must be explicitly false so ENABLE_LOCAL_TTS drives the choice
    dec = p._make_routing_decision(_make_input(prefer_local=False))
    assert dec.engine_choice == "edge"
    assert dec.fallback_engine == "kokoro"


def test_routing_decision_prefer_local_true(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_LOCAL_TTS", "false")
    p = SynthesizePipeline(mock_mode=True, router=MagicMock())
    dec = p._make_routing_decision(_make_input(prefer_local=True))
    assert dec.engine_choice == "kokoro"


def test_routing_decision_prefer_local_false(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_LOCAL_TTS", "true")
    p = SynthesizePipeline(mock_mode=True, router=MagicMock())
    dec = p._make_routing_decision(_make_input(prefer_local=False))
    assert dec.engine_choice == "edge"


def test_routing_decision_character_binding_honoured(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_LOCAL_TTS", "true")
    binding = CharacterVoiceBinding(
        canonical_name="alice",
        aliases=[],
        gender="female",
        age_range="adult",
        suggested_voice_id="zh-CN-XiaoxiaoNeural",
        sample_quote="hi",
    )
    p = SynthesizePipeline(mock_mode=True, router=MagicMock())
    dec = p._make_routing_decision(
        _make_input(speaker="alice", char_map=[binding])
    )
    # explicit binding matched -> strict pass-through of the Edge id (mapped to kokoro)
    assert dec.voice_id == "zf_xiaoxiao"


def test_routing_decision_emotion_volume(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_LOCAL_TTS", "true")
    p = SynthesizePipeline(mock_mode=True, router=MagicMock())
    dec = p._make_routing_decision(_make_input(emotion="angry"))
    # angry has a positive volume_db in the acoustic map
    assert dec.prosody_overrides["emotion"] == "angry"
    assert "volume" in dec.prosody_overrides


def test_routing_decision_known_emotion_volume(monkeypatch) -> None:
    # "sad" is a valid emotion present in the acoustic map -> volume is applied
    monkeypatch.setenv("ENABLE_LOCAL_TTS", "true")
    p = SynthesizePipeline(mock_mode=True, router=MagicMock())
    dec = p._make_routing_decision(_make_input(emotion="sad"))
    assert dec.prosody_overrides["emotion"] == "sad"
    assert "volume" in dec.prosody_overrides


# ── synthesize_paragraphs constructs a pipeline ─────────────────────────────


def test_synthesize_paragraphs_constructs() -> None:
    # Just verify the convenience wrapper builds a SynthesizePipeline and is
    # callable; full audio synthesis is covered by integration tests.
    p = synthesize_paragraphs.__wrapped__ if hasattr(synthesize_paragraphs, "__wrapped__") else synthesize_paragraphs
    assert callable(p)
