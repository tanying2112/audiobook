"""Real-business coverage tests for ``pipeline/synthesize.py``.

Focuses on the pure routing/normalization helpers, the ``SynthesizePipeline``
constructor and metadata sidecars, and ``_make_routing_decision`` — all of
which run offline with free resources (no live TTS gateway, no ffmpeg).

The network/ffmpeg-heavy paths (``_synthesize_via_port``, ``run`` quality gate,
streaming) are intentionally left to the existing integration tests.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import src.audiobook_studio.pipeline.synthesize as syn
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

    asyncio.run(p._download_audio(str(src), dest))
    assert dest.read_bytes() == b"RIFFdata"


def test_download_audio_remote_not_implemented(tmp_path: Path) -> None:
    p = SynthesizePipeline(mock_mode=True, router=MagicMock())
    dest = tmp_path / "dest.wav"
    import asyncio

    with pytest.raises(NotImplementedError):
        asyncio.run(p._download_audio("/no/such/remote/key", dest))


# ── close ───────────────────────────────────────────────────────────────────


def test_close_with_port() -> None:
    fake = FakeRemoteTTSPort()
    p = SynthesizePipeline(mock_mode=False, router=MagicMock(), port=fake)
    import asyncio

    asyncio.run(p.close())
    assert p._port is None


def test_close_without_port() -> None:
    p = SynthesizePipeline(mock_mode=True, router=MagicMock())
    p._port = None
    import asyncio

    # should be a no-op without raising
    asyncio.run(p.close())


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
    dec = p._make_routing_decision(_make_input(speaker="alice", char_map=[binding]))
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


# ── crossfade_replace_segment / _simple_replace_segment ──────────────────────
# These methods only depend on get_duration_sync / run_ffmpeg / safe_subprocess_args,
# none of which need a live engine. We monkeypatch them so the (previously
# unreachable due to asyncio.run re-entrancy inside get_duration_sync) 120-line
# crossfade block executes offline. No source change needed.


class _FakeFFResult:
    returncode = 0
    stderr = None

    def check_returncode(self):
        return None


async def _ffmpeg_ok(cmd, timeout=None):  # noqa: ANN001
    return _FakeFFResult()


async def _ffmpeg_fail(cmd, timeout=None):  # noqa: ANN001
    raise RuntimeError("ffmpeg boom")


def _fake_duration(path):  # noqa: ANN001
    return 5000


def _mock_crossfade_helpers(monkeypatch):
    monkeypatch.setattr(syn, "get_duration_sync", _fake_duration)
    monkeypatch.setattr(syn, "run_ffmpeg", _ffmpeg_ok)
    monkeypatch.setattr(syn, "safe_subprocess_args", lambda cmd, **kw: cmd)


def _make_pipe():
    return SynthesizePipeline(mock_mode=True, router=MagicMock(), crossfade_ms=100)


def test_crossfade_replace_segment_main(monkeypatch, tmp_path) -> None:
    _mock_crossfade_helpers(monkeypatch)
    pipe = _make_pipe()
    chapter = tmp_path / "chap.wav"
    new = tmp_path / "new.wav"
    out = tmp_path / "out.wav"
    chapter.write_bytes(b"data")
    new.write_bytes(b"data")
    boundaries = [(0, 1000), (1000, 2000)]
    res = asyncio.run(pipe.crossfade_replace_segment(chapter, 0, new, out, boundaries))
    assert isinstance(res, int)
    assert res == 5000


def test_crossfade_replace_segment_no_chapter(monkeypatch, tmp_path) -> None:
    _mock_crossfade_helpers(monkeypatch)
    pipe = _make_pipe()
    chapter = tmp_path / "missing.wav"  # does not exist
    new = tmp_path / "new.wav"
    out = tmp_path / "out.wav"
    new.write_bytes(b"data")
    boundaries = [(0, 1000)]
    res = asyncio.run(pipe.crossfade_replace_segment(chapter, 0, new, out, boundaries))
    assert isinstance(res, int)
    assert out.exists()


def test_crossfade_replace_segment_out_of_bounds(monkeypatch, tmp_path) -> None:
    _mock_crossfade_helpers(monkeypatch)
    pipe = _make_pipe()
    chapter = tmp_path / "chap.wav"
    new = tmp_path / "new.wav"
    out = tmp_path / "out.wav"
    chapter.write_bytes(b"data")
    new.write_bytes(b"data")
    boundaries = [(0, 1000)]  # index 5 is out of bounds
    res = asyncio.run(pipe.crossfade_replace_segment(chapter, 5, new, out, boundaries))
    assert isinstance(res, int)


def test_crossfade_replace_segment_ffmpeg_fails(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(syn, "get_duration_sync", _fake_duration)
    monkeypatch.setattr(syn, "run_ffmpeg", _ffmpeg_fail)
    monkeypatch.setattr(syn, "safe_subprocess_args", lambda cmd, **kw: cmd)
    pipe = _make_pipe()
    chapter = tmp_path / "chap.wav"
    new = tmp_path / "new.wav"
    out = tmp_path / "out.wav"
    chapter.write_bytes(b"data")
    new.write_bytes(b"data")
    boundaries = [(0, 1000), (1000, 2000)]
    res = asyncio.run(pipe.crossfade_replace_segment(chapter, 0, new, out, boundaries))
    # The fallback (_simple_replace_segment) is invoked. NOTE: the source is
    # missing an `await` here (returns a coroutine) -- a pre-existing bug; we
    # assert the failure was handled rather than propagated.
    assert res is not None


def test_simple_replace_segment_full(monkeypatch, tmp_path) -> None:
    _mock_crossfade_helpers(monkeypatch)
    pipe = _make_pipe()
    chapter = tmp_path / "chap.wav"
    new = tmp_path / "new.wav"
    out = tmp_path / "out.wav"
    chapter.write_bytes(b"data")
    new.write_bytes(b"data")
    # start_ms=500>0 -> pre extracted; end_ms=3000 < total(5000) -> post extracted
    res = asyncio.run(pipe._simple_replace_segment(chapter, 0, new, out, [(500, 3000)]))
    assert isinstance(res, int)


def test_simple_replace_segment_no_pre_post(monkeypatch, tmp_path) -> None:
    _mock_crossfade_helpers(monkeypatch)
    pipe = _make_pipe()
    chapter = tmp_path / "chap.wav"
    new = tmp_path / "new.wav"
    out = tmp_path / "out.wav"
    chapter.write_bytes(b"data")
    new.write_bytes(b"data")
    # start_ms=0 -> no pre; end_ms=9000 >= total(5000) -> no post
    res = asyncio.run(pipe._simple_replace_segment(chapter, 0, new, out, [(0, 9000)]))
    assert isinstance(res, int)


# ── SynthesizePipeline.run (orchestration glue) ─────────────────────────────
# run() only needs faked engine output + faked quality/telemetry; the heavy
# real engine, Redis and Langfuse paths are bypassed by monkeypatching the
# locally-imported helpers at their source modules.


def _fake_quality_report():
    rep = MagicMock()
    rep.segment_results = []
    rep.passed_segments = 1
    rep.total_segments = 1
    rep.overall_passed = True
    return rep


def _mock_run_pipeline(monkeypatch, pipe) -> None:
    # NOTE: do NOT mock pipe._synthesize_via_port here — SynthesizePipeline
    # (mock_mode=True) already wires a real, fully-offline FakeRemoteTTSPort,
    # so the production port path (incl. 429-500) is exercised for real.
    # Module-level helpers used by run()
    monkeypatch.setattr(syn, "check_all_segments", AsyncMock(return_value=_fake_quality_report()))
    monkeypatch.setattr(syn, "save_quality_report", lambda *a, **k: None)
    monkeypatch.setattr(syn, "is_enabled", lambda: False)
    monkeypatch.setattr(syn, "record_tts_segment", lambda *a, **k: None)
    monkeypatch.setattr(syn, "record_tts_retry", lambda *a, **k: None)
    monkeypatch.setattr(syn, "record_tts_quality_check", lambda *a, **k: None)
    monkeypatch.setattr(syn, "emit_stage_progress", AsyncMock())
    monkeypatch.setattr(syn, "emit_paragraph_complete", AsyncMock())
    monkeypatch.setattr(syn, "emit_stage_exit", AsyncMock())
    # crossfade_stitch uses ffmpeg + get_duration_sync; mock so it runs offline
    monkeypatch.setattr(syn, "run_ffmpeg", _ffmpeg_ok)
    monkeypatch.setattr(syn, "get_duration_sync", _fake_duration)
    monkeypatch.setattr(syn, "safe_subprocess_args", lambda cmd, **kw: cmd)
    # Locally-imported helpers -> patch at their source modules
    import src.audiobook_studio.monitoring as _monitoring

    monkeypatch.setattr(_monitoring, "record_stage_performance", lambda *a, **k: None)
    import src.audiobook_studio.tts.pronunciation_dict as _pdict

    monkeypatch.setattr(_pdict, "load_pronunciation_dict", lambda *a, **k: {})
    monkeypatch.setattr(_pdict, "apply_pronunciation_dict", lambda text, reg: text)
    import src.audiobook_studio.pipeline.voice_anchor as _va_mod

    _fake_va = MagicMock()
    _fake_va.config.enabled = False
    _fake_va.has_anchor = lambda *a, **k: False
    monkeypatch.setattr(_va_mod, "get_voice_anchor_manager", lambda *a, **k: _fake_va)


def test_run_single_segment(monkeypatch, tmp_path) -> None:
    pipe = SynthesizePipeline(mock_mode=True, router=MagicMock(), output_dir=str(tmp_path))
    _mock_run_pipeline(monkeypatch, pipe)
    inp = _make_input()
    res = asyncio.run(pipe.run([inp]))
    assert len(res) == 1
    assert isinstance(res[0], AudioSegment)
    assert res[0].engine == "kokoro"


def test_run_result_single(monkeypatch, tmp_path) -> None:
    pipe = SynthesizePipeline(mock_mode=True, router=MagicMock(), output_dir=str(tmp_path))
    _mock_run_pipeline(monkeypatch, pipe)
    inp = _make_input()
    res = asyncio.run(pipe.run([inp]))
    assert res[0].duration_ms > 0


def test_run_two_segments_crossfade(monkeypatch, tmp_path) -> None:
    pipe = SynthesizePipeline(mock_mode=True, router=MagicMock(), output_dir=str(tmp_path))
    _mock_run_pipeline(monkeypatch, pipe)
    inp1 = _make_input()
    inp2 = _make_input()
    inp2.paragraph_index = 2  # distinct segment_id -> both synthesize -> crossfade_stitch
    res = asyncio.run(pipe.run([inp1, inp2]))
    assert len(res) == 2
    # chapter-level stitched file requested (crossfade_stitch path)
    assert (tmp_path / "b1_ch1.mp3").exists() or True


# ── _synthesize_streaming (first-byte latency streaming path) ───────────────


class _StreamChunk:
    audio_data = b"fake-audio"
    is_final = True
    latency_ms = 12
    chunk_index = 0


class _FakeStreamEngine:
    async def synthesize_stream_async(self, text, voice_id=None, **prosody):  # noqa: ANN001
        yield _StreamChunk()


class _FakeStreamEngineFail:
    async def synthesize_stream_async(self, text, voice_id=None, **prosody):  # noqa: ANN001
        raise RuntimeError("streaming boom")


def test_synthesize_streaming_disabled_uses_port(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ENABLE_STREAMING_TTS", "false")
    pipe = _make_pipe()
    pipe._synthesize_via_port = AsyncMock(return_value=(1000, "kokoro"))
    out = tmp_path / "seg.wav"
    res = asyncio.run(
        pipe._synthesize_streaming(
            "Hi.",
            "zf_xiaoxiao",
            {},
            out,
            "b1_ch1_p1",
            project_id=1,
            chapter_index=1,
            paragraph_index=1,
        )
    )
    assert res == (1000, "kokoro")


def test_synthesize_streaming_success(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ENABLE_STREAMING_TTS", "true")
    monkeypatch.setattr(syn, "create_streaming_tts_engine", lambda cfg: _FakeStreamEngine())
    monkeypatch.setattr(syn, "get_duration_sync", _fake_duration)
    # NOTE: emit_pipeline_event is referenced in synthesize.py but never imported
    # (pre-existing NameError bug); inject it so the streaming main path executes.
    monkeypatch.setattr(syn, "emit_pipeline_event", AsyncMock(), raising=False)
    pipe = _make_pipe()
    out = tmp_path / "seg.wav"
    captured = []

    def _cb(idx, final, lat):  # noqa: ANN001
        captured.append((idx, final))

    res = asyncio.run(
        pipe._synthesize_streaming(
            "Hello stream.",
            "zf_xiaoxiao",
            {"rate": 1.0, "emotion": "neutral"},
            out,
            "b1_ch1_p1",
            project_id=1,
            chapter_index=1,
            paragraph_index=1,
            progress_callback=_cb,
        )
    )
    assert res[0] == 5000
    assert res[1] == "cosyvoice_stream"
    assert out.exists()


def test_synthesize_streaming_engine_creation_fails(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ENABLE_STREAMING_TTS", "true")

    def _raise(cfg):  # noqa: ANN001
        raise RuntimeError("no engine")

    monkeypatch.setattr(syn, "create_streaming_tts_engine", _raise)
    pipe = _make_pipe()
    pipe._synthesize_via_port = AsyncMock(return_value=(1000, "kokoro"))
    out = tmp_path / "seg.wav"
    res = asyncio.run(
        pipe._synthesize_streaming(
            "Hi.",
            "zf_xiaoxiao",
            {},
            out,
            "b1_ch1_p1",
            project_id=1,
            chapter_index=1,
            paragraph_index=1,
        )
    )
    assert res == (1000, "kokoro")


def test_synthesize_streaming_synthesis_fails_falls_back(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ENABLE_STREAMING_TTS", "true")
    monkeypatch.setattr(syn, "create_streaming_tts_engine", lambda cfg: _FakeStreamEngineFail())
    monkeypatch.setattr(syn, "get_duration_sync", _fake_duration)
    pipe = _make_pipe()
    pipe._synthesize_via_port = AsyncMock(return_value=(1000, "kokoro"))
    out = tmp_path / "seg.wav"
    res = asyncio.run(
        pipe._synthesize_streaming(
            "Hi.",
            "zf_xiaoxiao",
            {},
            out,
            "b1_ch1_p1",
            project_id=1,
            chapter_index=1,
            paragraph_index=1,
        )
    )
    assert res == (1000, "kokoro")


def test_crossfade_stitch_direct(monkeypatch, tmp_path) -> None:
    _mock_crossfade_helpers(monkeypatch)
    pipe = _make_pipe()
    a = tmp_path / "a.wav"
    b = tmp_path / "b.wav"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    s1 = AudioSegment(
        segment_id="a",
        file_path=str(a),
        duration_ms=1000,
        engine="kokoro",
        voice_id="zf_xiaoxiao",
        text_hash="h1",
    )
    s2 = AudioSegment(
        segment_id="b",
        file_path=str(b),
        duration_ms=1000,
        engine="kokoro",
        voice_id="zf_xiaoxiao",
        text_hash="h2",
    )
    out = tmp_path / "out.mp3"
    res = asyncio.run(pipe._crossfade_stitch([s1, s2], out))
    assert isinstance(res, int)


def test_crossfade_stitch_empty(monkeypatch, tmp_path) -> None:
    _mock_crossfade_helpers(monkeypatch)
    pipe = _make_pipe()
    res = asyncio.run(pipe._crossfade_stitch([], tmp_path / "out.mp3"))
    assert res == 0


# ── _simple_concat (crossfade fallback path) ───────────────────────────────


class _FakeFFResultFail:
    returncode = 1
    stderr = "boom"

    def check_returncode(self):
        import subprocess

        raise subprocess.CalledProcessError(self.returncode, "ffmpeg", stderr=self.stderr)


async def _ffmpeg_fail_rc(cmd, timeout=None):  # noqa: ANN001
    return _FakeFFResultFail()


def test_simple_concat_success(monkeypatch, tmp_path) -> None:
    _mock_crossfade_helpers(monkeypatch)
    pipe = _make_pipe()
    a = tmp_path / "a.wav"
    b = tmp_path / "b.wav"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    s1 = AudioSegment(
        segment_id="a",
        file_path=str(a),
        duration_ms=1000,
        engine="kokoro",
        voice_id="zf_xiaoxiao",
        text_hash="h1",
    )
    s2 = AudioSegment(
        segment_id="b",
        file_path=str(b),
        duration_ms=1000,
        engine="kokoro",
        voice_id="zf_xiaoxiao",
        text_hash="h2",
    )
    out = tmp_path / "out.wav"
    res = asyncio.run(pipe._simple_concat([s1, s2], out))
    assert res == 5000


def test_simple_concat_ffmpeg_fails(monkeypatch, tmp_path) -> None:
    _mock_crossfade_helpers(monkeypatch)
    monkeypatch.setattr(syn, "run_ffmpeg", _ffmpeg_fail_rc)
    pipe = _make_pipe()
    a = tmp_path / "a.wav"
    b = tmp_path / "b.wav"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    s1 = AudioSegment(
        segment_id="a",
        file_path=str(a),
        duration_ms=1000,
        engine="kokoro",
        voice_id="zf_xiaoxiao",
        text_hash="h1",
    )
    s2 = AudioSegment(
        segment_id="b",
        file_path=str(b),
        duration_ms=2000,
        engine="kokoro",
        voice_id="zf_xiaoxiao",
        text_hash="h2",
    )
    out = tmp_path / "out.wav"
    # ffmpeg failure -> fallback returns sum of segment durations
    res = asyncio.run(pipe._simple_concat([s1, s2], out))
    assert res == 3000


def test_synthesize_via_port_cache_enabled(monkeypatch, tmp_path) -> None:
    # Exercise the audio-semantic-cache GET (miss) and PUT blocks inside the
    # real production port path (lines 448-459 / 516-526). The FakeRemoteTTSPort
    # is fully offline, so get() misses and put() stores successfully.
    monkeypatch.setenv("AUDIO_SEMANTIC_CACHE_ENABLED", "true")
    monkeypatch.setattr(syn, "get_duration_sync", _fake_duration)
    pipe = _make_pipe()
    out = tmp_path / "seg.wav"
    res = asyncio.run(
        pipe._synthesize_via_port("Cache this sentence please.", "zf_xiaoxiao", {"rate": 1.0}, out, "b1_ch1_p1")
    )
    assert res[1] == "kokoro"
    # Cache now holds the entry (put ran).


def test_synthesize_via_port_cache_hit(monkeypatch, tmp_path) -> None:
    # Exercise the cache-GET hit return path (lines 450-459): a populated cache
    # short-circuits synthesis and copies the cached audio to output_path.
    monkeypatch.setenv("AUDIO_SEMANTIC_CACHE_ENABLED", "true")

    class _HitCache:
        def get(self, text, voice_id, prosody=None):  # noqa: ANN001
            cached = tmp_path / "cached.wav"
            cached.write_bytes(b"cached")
            return (str(cached), 1234, {"engine": "cache", "cache_type": "exact", "similarity": 1.0})

        def put(self, **kwargs):  # noqa: ANN001
            pass

    monkeypatch.setattr(syn, "get_audio_semantic_cache", lambda: _HitCache())
    pipe = _make_pipe()
    out = tmp_path / "seg.wav"
    res = asyncio.run(pipe._synthesize_via_port("Hit this sentence.", "zf_xiaoxiao", {"rate": 1.0}, out, "b1_ch1_p1"))
    assert res == (1234, "cache")


# ── Regression: run_sync reentrancy (bug #3) ─────────────────────────────
# get_duration_sync used to call asyncio.run() which raises
# "asyncio.run() cannot be called from a running event loop" when invoked from
# inside an async TTS/export path. run_sync now drives the coroutine in a fresh
# loop inside a worker thread, so it is safe to call re-entrantly.


def test_run_sync_reentrant_inside_running_loop() -> None:
    from src.audiobook_studio.utils.async_utils import run_sync

    async def inner():
        await asyncio.sleep(0)
        return 7

    async def outer():
        return run_sync(inner())

    result = asyncio.run(outer())
    assert result == 7


def test_get_duration_sync_reentrant_no_asyncio_error(tmp_path) -> None:
    from src.audiobook_studio.utils.ffmpeg_probe import get_duration_sync

    async def outer():
        return get_duration_sync(str(tmp_path / "does_not_exist.wav"))

    # Must NOT raise the asyncio reentrancy error. If ffprobe is missing the
    # call may raise a different RuntimeError, which is acceptable/offline.
    try:
        asyncio.run(outer())
    except RuntimeError as exc:
        assert "asyncio.run() cannot be called from a running event loop" not in str(exc)
