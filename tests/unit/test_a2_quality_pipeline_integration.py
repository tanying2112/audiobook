"""A2 集成：QualityCheckPipeline.run 在 golden_feedback=True 时把判定回流为 judge 金标。

全程 mock 模式、不触网、不调用真实 LLM/音频后端。用 spy 取代真实写盘函数，
既验证集成调用路径，又避免污染仓库 data/golden。
"""

from pathlib import Path
from unittest.mock import MagicMock

from src.audiobook_studio.pipeline.quality_check import QualityCheckPipeline
from src.audiobook_studio.schemas import ParagraphAnnotation
from src.audiobook_studio.schemas.tts_routing import TtsRoutingDecision


def _annotation(**overrides):
    defaults = {
        "paragraph_index": 0,
        "speaker_canonical_name": "旁白",
        "is_dialogue": False,
        "emotion": "neutral",
        "emotion_intensity": 0.5,
        "speech_rate": 1.0,
        "pitch_shift_semitones": 0,
        "pause_before_ms": 300,
        "pause_after_ms": 500,
        "confidence": 0.9,
        "difficulty": "B",
        "needs_sfx": False,
        "sfx_tags": [],
    }
    defaults.update(overrides)
    return ParagraphAnnotation(**defaults)


def _routing(**overrides):
    defaults = {
        "segment_id": "book_001_ch1_p0",
        "engine_choice": "kokoro",
        "voice_id": "kokoro_narrator",
        "prosody_overrides": None,
        "fallback_engine": "edge",
        "reasoning": "Mock routing decision",
        "estimated_cost_usd": 0.001,
        "estimated_duration_ms": 5000,
    }
    defaults.update(overrides)
    return TtsRoutingDecision(**defaults)


def test_quality_check_run_calls_golden_feedback(monkeypatch):
    # spy 取代真实写盘函数，避免污染仓库 data/golden
    spy = MagicMock(return_value=1)
    monkeypatch.setattr("audiobook_studio.feedback.loop.quality_judgments_to_golden", spy)
    monkeypatch.setenv("AUDIOBOOK_GOLDEN_FEEDBACK", "0")  # 关闭全局开关，改用显式参数

    import tempfile

    audio_path = Path(tempfile.mkdtemp()) / "seg.wav"
    audio_path.write_bytes(b"RIFF" + b"\x00" * 1000)  # 最小 WAV 头，规则分析会失败但被捕获

    ann = _annotation()
    routing = _routing()

    pipeline = QualityCheckPipeline(mock_mode=True)
    inputs = [("dummy.wav", ann, routing, "这是参考文本")]
    judgments = pipeline.run(
        inputs,
        golden_feedback=True,
        golden_feedback_split="val",
        golden_feedback_stage="judge",
    )
    assert len(judgments) == 1
    # 集成点被触发，且把判定/标注/参考文本带入回流
    assert spy.called
    assert spy.call_args.args[0] is judgments  # 判定列表原样传入回流
    call_kwargs = spy.call_args.kwargs
    assert call_kwargs["split"] == "val"
    assert call_kwargs["stage"] == "judge"
    assert call_kwargs["annotations"][0] is ann
    assert call_kwargs["reference_texts"][0] == "这是参考文本"


def test_quality_check_run_golden_feedback_off_by_default(monkeypatch):
    spy = MagicMock(return_value=0)
    monkeypatch.setattr("audiobook_studio.feedback.loop.quality_judgments_to_golden", spy)
    ann = _annotation()
    routing = _routing()
    pipeline = QualityCheckPipeline(mock_mode=True)
    pipeline.run([("dummy.wav", ann, routing, "x")])
    # 默认关闭，不应触发回流
    assert not spy.called
