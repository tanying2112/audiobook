"""运行时自动回流（M0/A2）：SOPBackgroundThread 驱动生产失败/纠错回流为金标。

验证：
* M0：用户修正经 _ingest_corrections_to_golden 回流为 val/edit 金标。
* A2：质检判定经全局收集器被 _drain_quality_judgments_to_golden 回流为 val/judge 金标。
* 开关：仅在 AUDIOBOOK_GOLDEN_FEEDBACK=1 时启用，默认关闭防污染。
* quality_check.run 在 golden_feedback 开启时把判定推入全局收集器，交由后台线程抽干。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from audiobook_studio.pipeline.quality_check import QualityCheckPipeline, get_quality_judgment_collector
from audiobook_studio.pipeline.sop_reflection import CorrectionCollector, SOPBackgroundThread, UserCorrection


def _make_thread(golden_root: Path, learning_enabled: bool = True):
    class _StubSOP:
        def is_learning_enabled(self):
            return learning_enabled

        def get_min_corrections_for_update(self):
            return 1

        def get_confidence_threshold(self):
            return 0.0

        def update_genre_rules(self, *a, **k):
            return True

        def record_correction(self, *a, **k):
            pass

    class _StubEngine:
        def reflect(self, genre, corrections):
            return SimpleNamespace(
                confidence=1.0,
                proposed_rules={"x": 1},
                reasoning="ok",
                corrections_analyzed=len(corrections),
            )

    return SOPBackgroundThread(_StubSOP(), CorrectionCollector(), _StubEngine(), golden_root=golden_root)


def _make_correction():
    return UserCorrection(
        timestamp="2026-08-30T00:00:00Z",
        project_id=1,
        chapter_index=2,
        paragraph_index=3,
        field="speech_rate",
        original_value=1.0,
        corrected_value=1.15,
        genre="default",
        context={"speaker": "narrator"},
    )


def _make_judgment(seg_id="seg_x"):
    return SimpleNamespace(
        segment_id=seg_id,
        needs_regeneration=False,
        overall_score=0.92,
        issues=[],
    )


def _drain_collector():
    get_quality_judgment_collector().drain()


def test_ingest_corrections_to_golden_writes_edit_samples(tmp_path: Path):
    t = _make_thread(tmp_path)
    added = t._ingest_corrections_to_golden([_make_correction()])
    assert added == 1
    f = tmp_path / "val" / "edit" / "edit.jsonl"
    assert f.exists()
    rows = [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["stage"] == "edit"
    assert rows[0]["source"] == "user_correction"
    assert rows[0]["output"]["value"] == 1.15


def test_drain_quality_judgments_to_golden_writes_judge_samples(tmp_path: Path):
    _drain_collector()
    get_quality_judgment_collector().add(
        _make_judgment("seg_a"),
        annotation={"speaker": "n"},
        reference_text="参考文本",
        audio_description="desc",
    )
    t = _make_thread(tmp_path)
    added = t._drain_quality_judgments_to_golden()
    assert added == 1
    f = tmp_path / "val" / "judge" / "judge.jsonl"
    assert f.exists()
    rows = [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["stage"] == "judge"
    assert rows[0]["source"] == "quality_check"
    assert rows[0]["output"]["needs_regeneration"] is False


def test_check_and_reflect_gated_by_env(tmp_path: Path, monkeypatch):
    # env 关闭：即使收集器已满，也不回流（防污染）
    _drain_collector()
    get_quality_judgment_collector().add(_make_judgment("seg_a"))
    c = CorrectionCollector()
    c.add_correction(_make_correction())
    t = _make_thread(tmp_path)
    t.collector = c
    calls = {"a2": 0, "m0": 0}
    monkeypatch.setattr(t, "_drain_quality_judgments_to_golden", lambda: calls.__setitem__("a2", calls["a2"] + 1) or 0)
    monkeypatch.setattr(t, "_ingest_corrections_to_golden", lambda _c: calls.__setitem__("m0", calls["m0"] + 1) or 0)
    monkeypatch.setenv("AUDIOBOOK_GOLDEN_FEEDBACK", "0")
    t._check_and_reflect()
    assert calls["a2"] == 0 and calls["m0"] == 0
    assert not (tmp_path / "val").exists()


def test_check_and_reflect_runs_when_env_on(tmp_path: Path, monkeypatch):
    # env 开启：A2 + M0 都回流（学习启用 -> 修正被抽干并回流）
    _drain_collector()
    get_quality_judgment_collector().add(_make_judgment("seg_a"))
    c = CorrectionCollector()
    c.add_correction(_make_correction())
    t = _make_thread(tmp_path)
    t.collector = c
    monkeypatch.setenv("AUDIOBOOK_GOLDEN_FEEDBACK", "1")
    t._check_and_reflect()
    assert (tmp_path / "val" / "judge" / "judge.jsonl").exists()
    assert (tmp_path / "val" / "edit" / "edit.jsonl").exists()


def test_quality_check_run_populates_judgment_collector(monkeypatch):
    # run() 在 golden_feedback=True 时把判定推入全局收集器
    _drain_collector()
    monkeypatch.setenv("AUDIOBOOK_GOLDEN_FEEDBACK", "0")  # 关闭同步写盘，专注验证收集器
    monkeypatch.setattr("audiobook_studio.feedback.loop.quality_judgments_to_golden", lambda *a, **k: 0)

    from audiobook_studio.schemas import ParagraphAnnotation
    from audiobook_studio.schemas.tts_routing import TtsRoutingDecision

    ann = ParagraphAnnotation(
        paragraph_index=0,
        speaker_canonical_name="旁白",
        is_dialogue=False,
        emotion="neutral",
        emotion_intensity=0.5,
        speech_rate=1.0,
        pitch_shift_semitones=0,
        pause_before_ms=300,
        pause_after_ms=500,
        confidence=0.9,
        difficulty="B",
        needs_sfx=False,
        sfx_tags=[],
    )
    routing = TtsRoutingDecision(
        segment_id="book_001_ch1_p0",
        engine_choice="kokoro",
        voice_id="kokoro_narrator",
        prosody_overrides=None,
        fallback_engine="edge",
        reasoning="mock",
        estimated_cost_usd=0.001,
        estimated_duration_ms=5000,
    )
    pipeline = QualityCheckPipeline(mock_mode=True)
    pipeline.run([("dummy.wav", ann, routing, "参考文本")], golden_feedback=True)
    assert get_quality_judgment_collector().size() == 1
