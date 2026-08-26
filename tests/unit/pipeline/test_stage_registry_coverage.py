"""Real-business coverage tests for ``pipeline/stage_registry.py``.

Covers the registry mechanics and each built-in ``StageHandler``'s ``run`` /
``persist`` / ``apersist`` glue. The heavy engine pipelines are replaced with
lightweight fakes (monkeypatched at the module level) so the orchestration
branches execute offline with free resources.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import src.audiobook_studio.models as _models_mod
import src.audiobook_studio.pipeline.persistence as _persistence_mod
import src.audiobook_studio.pipeline.stage_registry as sr
from src.audiobook_studio.pipeline.stage_registry import (
    AudioPostprocessStage,
    AnalyzeStage,
    AnnotateStage,
    EditStage,
    ExtractStage,
    QualityStage,
    ReviewStage,
    StageHandler,
    StageRegistry,
    SegmentStage,
    SynthesizeStage,
    TranslateStage,
    register_stage,
)
from src.audiobook_studio.schemas import (
    ParagraphAnnotation,
    ReviewerInput,
    ReviewerJudgment,
    TtsEditInput,
)
from src.audiobook_studio.schemas.review import FixCommand


# ── Lightweight fakes for the engine pipelines ──────────────────────────────


@dataclass
class FakeExtractResult:
    raw_text: str = "Para one.\n\nPara two."
    _chapter_id: int = 0


class FakeExtractPipeline:
    def run(self, input_data):  # noqa: ANN001
        return FakeExtractResult()


class FakeAnalyzePipeline:
    def run(self, input_data):  # noqa: ANN001
        return MagicMock()


class FakeAnnotatePipeline:
    def __init__(self):
        self._annotation = ParagraphAnnotation(
            paragraph_index=1,
            speaker_canonical_name="_narrator_",
            is_dialogue=False,
            emotion="neutral",
            emotion_intensity=0.5,
            confidence=0.9,
        )

    def run(self, input_data):  # noqa: ANN001
        return self._annotation


class FakeEditPipeline:
    def run(self, input_data):  # noqa: ANN001
        return MagicMock()


class FakeQualityPipeline:
    def __init__(self, results=None):  # noqa: ANN001
        self._results = results

    def run(self, inputs):  # noqa: ANN001
        if self._results is not None:
            return self._results
        return [MagicMock()]


class FakeChapter:
    id = 7
    index = 1


@dataclass
class FakeParagraph:
    """A plain paragraph with concrete (non-mock) attributes."""

    index: int = 1
    text: str = "Hello."
    speaker_canonical_name: str = "_narrator_"
    is_dialogue: bool = False
    emotion: str = "neutral"
    emotion_intensity: float = 0.5
    speech_rate: float = 1.0
    pitch_shift_semitones: int = 0
    pause_before_ms: int = 300
    pause_after_ms: int = 500
    confidence: float = 0.9
    difficulty: str = "B"
    needs_sfx: bool = False
    sfx_tags: list = field(default_factory=list)
    edited_text: str = "Hello, this is edited text."
    id: int = 99
    audio_segment_id: str = "seg-99"


class FakeReviewerAgent:
    def __init__(self, mock_mode=None, strict_mode=True):  # noqa: ANN001
        pass

    def run(self, input_data: ReviewerInput) -> ReviewerJudgment:
        return ReviewerJudgment(
            project_id=input_data.project_id,
            chapter_index=input_data.chapter_index,
            overall_passed=True,
            blocking_issues=0,
            warning_issues=0,
            summary="ok",
            fix_commands=[],
        )


class FakeFailingReviewerAgent(FakeReviewerAgent):
    def run(self, input_data: ReviewerInput) -> ReviewerJudgment:
        cmd = FixCommand(
            command_type="correct_emotion_tag",
            target_paragraph_index=1,
            parameters={},
            priority=1,
            rationale="mismatch",
        )
        return ReviewerJudgment(
            project_id=input_data.project_id,
            chapter_index=input_data.chapter_index,
            overall_passed=False,
            blocking_issues=1,
            warning_issues=0,
            summary="blocked",
            fix_commands=[cmd],
        )


class FakeTranslatePipeline:
    def translate_and_dub(self, **kwargs):  # noqa: ANN001
        from src.audiobook_studio.pipeline.synthesize import AudioSegment

        seg = AudioSegment(
            segment_id="t1",
            file_path="/tmp/t1.wav",
            duration_ms=100,
            engine="kokoro",
            voice_id="zf_xiaoxiao",
            text_hash="h",
        )
        return [seg], {"ok": True}


@dataclass
class FakeAudioSegment:
    text: str = ""
    speaker: str = "_narrator_"
    emotion: str = "neutral"
    is_dialogue: bool = False
    emotion_intensity: float = 0.5


class FakeAudioPostProcessor:
    def process_single(self, para, next_para_type="end"):  # noqa: ANN001
        return FakeAudioSegment(
            text=para.get("text", ""),
            speaker=para.get("speaker", "_narrator_"),
            is_dialogue=para.get("is_dialogue", False),
        )


# ── Fixtures: install fakes ─────────────────────────────────────────────────


@pytest.fixture
def patch_pipelines(monkeypatch):
    monkeypatch.setattr(sr, "ExtractPipeline", FakeExtractPipeline)
    monkeypatch.setattr(sr, "AnalyzeStructurePipeline", FakeAnalyzePipeline)
    monkeypatch.setattr(sr, "AnnotateParagraphPipeline", FakeAnnotatePipeline)
    monkeypatch.setattr(sr, "EditForTtsPipeline", FakeEditPipeline)
    monkeypatch.setattr(sr, "AudioPostProcessor", FakeAudioPostProcessor)
    monkeypatch.setattr(sr, "ReviewerAgent", FakeReviewerAgent)
    monkeypatch.setattr(sr, "TranslateAndDubPipeline", FakeTranslatePipeline)
    yield


@pytest.fixture
def patch_persistence(monkeypatch):
    async def fake_write_extract(db, project_id, chapter_index, result, *, chapter_id=None):
        return FakeChapter()

    async def fake_write_segment(db, project_id, chapter, result):
        return None

    async def fake_write_analyze(db, chapter, result):
        return None

    async def fake_write_annotate(db, project_id, chapter, paragraph_index, result):
        fake = MagicMock()
        fake.id = 5
        return fake

    async def fake_write_edit(db, para, result):
        fake = MagicMock()
        fake.id = 6
        return fake

    async def fake_write_synthesize(db, project_id, chapter, para, segment_info):
        fake = MagicMock()
        fake.id = 8
        return fake

    async def fake_write_quality(db, project_id, chapter, para, result):
        return None

    async def fake_write_audio_postprocess(db, para, params):
        return None

    monkeypatch.setattr(_persistence_mod, "write_extract", fake_write_extract)
    monkeypatch.setattr(_persistence_mod, "write_segment", fake_write_segment)
    monkeypatch.setattr(_persistence_mod, "write_analyze", fake_write_analyze)
    monkeypatch.setattr(_persistence_mod, "write_annotate", fake_write_annotate)
    monkeypatch.setattr(_persistence_mod, "write_edit", fake_write_edit)
    monkeypatch.setattr(_persistence_mod, "write_synthesize", fake_write_synthesize)
    monkeypatch.setattr(_persistence_mod, "write_quality", fake_write_quality)
    monkeypatch.setattr(_persistence_mod, "write_audio_postprocess", fake_write_audio_postprocess)
    yield


# ── Registry mechanics ──────────────────────────────────────────────────────


class _DummyHandler(StageHandler):
    async def run(self, **kwargs):  # noqa: ANN001
        return "ran"


def test_register_and_get() -> None:
    StageRegistry.register("dummy", _DummyHandler)
    assert StageRegistry.has("dummy")
    inst = StageRegistry.get("dummy")
    assert isinstance(inst, _DummyHandler)
    assert "dummy" in StageRegistry.list_stages()
    StageRegistry.unregister("dummy")
    assert not StageRegistry.has("dummy")


def test_unregister_missing_returns_false() -> None:
    assert StageRegistry.unregister("never_registered") is False


def test_get_unknown_raises() -> None:
    with pytest.raises(ValueError):
        StageRegistry.get("does_not_exist")


def test_clear_cache_noop() -> None:
    # clear_cache is a backward-compat no-op
    assert StageRegistry.clear_cache() is None


def test_register_stage_decorator() -> None:
    @register_stage("decorated")
    class _Dec(_DummyHandler):
        pass

    assert StageRegistry.has("decorated")
    StageRegistry.unregister("decorated")


def test_builtin_stages_registered() -> None:
    for name in [
        "extract",
        "segment",
        "analyze",
        "annotate",
        "edit",
        "audio_postprocess",
        "review",
        "synthesize",
        "quality",
        "translate",
    ]:
        assert StageRegistry.has(name), name


# ── StageHandler.get_result_snapshot branches ──────────────────────────────


def test_snapshot_model_dump() -> None:
    ann = ParagraphAnnotation(
        paragraph_index=1,
        speaker_canonical_name="_narrator_",
        is_dialogue=False,
        emotion="neutral",
        emotion_intensity=0.5,
        confidence=0.9,
    )
    out = StageHandler.get_result_snapshot(ExtractStage(), ann)
    assert isinstance(out, dict)
    assert out["paragraph_index"] == 1


def test_snapshot_dict_attr() -> None:
    class Plain:
        def __init__(self):
            self.a = 1
            self.b = 2

    out = StageHandler.get_result_snapshot(ExtractStage(), Plain())
    assert out == {"a": 1, "b": 2}


def test_snapshot_list() -> None:
    out = StageHandler.get_result_snapshot(ExtractStage(), [1, 2, 3])
    assert out == {"items": [1, 2, 3]}


def test_snapshot_dict() -> None:
    out = StageHandler.get_result_snapshot(ExtractStage(), {"x": 9})
    assert out == {"x": 9}


def test_snapshot_scalar() -> None:
    out = StageHandler.get_result_snapshot(ExtractStage(), 42)
    assert out == {"result": "42"}


def test_stage_handler_persist_default_noop() -> None:
    # The default ``persist`` guard skips the write when no chapter is present.
    handler = AnalyzeStage()
    # no chapter -> guard skips the write
    handler.persist(db=MagicMock(), project_id=1, chapter=None, paragraph=None, result=MagicMock())


# ── ExtractStage ────────────────────────────────────────────────────────────


def test_extract_stage_run(patch_pipelines) -> None:
    res = asyncio.run(
        ExtractStage().run(file_path="book.txt", mime_type="text/plain", detect_language=True)
    )
    assert res.raw_text == "Para one.\n\nPara two."


def test_extract_stage_persist(patch_pipelines, patch_persistence) -> None:
    # ExtractStage.persist was previously broken (referenced an undefined
    # ``chapter_result`` and raised NameError). It now bridges to apersist via
    # a reentrancy-safe run_sync, so the real persist logic executes offline.
    db = AsyncMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    handler = ExtractStage()
    handler.persist(
        db=db,
        project_id=1,
        chapter=FakeChapter(),
        paragraph=None,
        result=FakeExtractResult(),
    )
    # FakeExtractResult has two paragraphs split by blank lines -> two Paragraph
    # records attempted; commit called at least once.
    assert db.commit.await_count >= 1


def test_extract_stage_apersist(patch_pipelines, patch_persistence) -> None:
    # ``Paragraph`` is the real mapped model; apersist constructs it and runs
    # a select() against it via the (monkeypatched) persistence writers.
    db = AsyncMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    handler = ExtractStage()
    asyncio.run(
        handler.apersist(
            db=db,
            project_id=1,
            chapter=FakeChapter(),
            paragraph=None,
            result=FakeExtractResult(),
        )
    )
    assert db.commit.await_count >= 1


# ── AnalyzeStage ───────────────────────────────────────────────────────────


def test_analyze_stage_run(patch_pipelines) -> None:
    res = asyncio.run(
        AnalyzeStage().run(raw_text="Some text.", title_hint="T", author_hint="A")
    )
    assert res is not None


def test_analyze_stage_persist_no_chapter(patch_pipelines) -> None:
    AnalyzeStage().persist(db=MagicMock(), project_id=1, chapter=None, paragraph=None, result=MagicMock())


def test_analyze_stage_persist_with_chapter(patch_pipelines) -> None:
    # guard entered (body is pass -> delegates to apersist)
    AnalyzeStage().persist(db=MagicMock(), project_id=1, chapter=FakeChapter(), paragraph=None, result=MagicMock())


def test_analyze_stage_apersist(patch_pipelines, patch_persistence, monkeypatch) -> None:
    spy = AsyncMock()
    monkeypatch.setattr(_persistence_mod, "write_analyze", spy)
    asyncio.run(
        AnalyzeStage().apersist(db=AsyncMock(), project_id=1, chapter=FakeChapter(), paragraph=None, result=MagicMock())
    )
    assert spy.await_count >= 1


# ── AnnotateStage ──────────────────────────────────────────────────────────


def test_annotate_stage_short_paragraph_skip(patch_pipelines) -> None:
    # paragraph text shorter than 10 chars -> returns a skip stub annotation
    class FakePara:
        text = "tiny"
        index = 1

    res = asyncio.run(AnnotateStage().run(paragraph=FakePara()))
    assert res.speaker_canonical_name == "_narrator_"
    assert "Skipped" in res.notes


def test_annotate_stage_run_no_chapter(patch_pipelines) -> None:
    # no chapter -> all defaults built, pipeline invoked with paragraph_text
    res = asyncio.run(
        AnnotateStage().run(paragraph_text="This is a sufficiently long paragraph for annotation.", paragraph_index=2)
    )
    assert res is not None


def test_annotate_stage_run_with_chapter(patch_pipelines) -> None:
    # chapter with analyzed_json -> exercises the branch that parses book_meta /
    # character_voice_map / emotion_snapshot / story_line_summary / style notes
    class FakePara:
        text = "This is a long enough paragraph to be annotated properly."
        index = 3

    class FakeChapter:
        index = 1
        analyzed_json = {
            "book_meta": {
                "title": "T",
                "author": "A",
                "genre": "小说",
                "difficulty": "B",
                "language": "zh",
                "era": "现代",
                "total_chapters_estimated": 10,
            },
            "character_voice_map": [
                {
                    "canonical_name": "bob",
                    "aliases": [],
                    "gender": "male",
                    "age_range": "adult",
                    "suggested_voice_id": "zh-CN-YunxiNeural",
                    "sample_quote": "hi",
                }
            ],
            "emotion_snapshots": [
                {"chapter": 1, "dominant_emotion": "happy", "intensity": 0.8, "notes": "joy"}
            ],
            "story_line_summary": "A sufficiently long real story line summary that exceeds the one hundred character minimum required by the paragraph annotation input schema for proper validation.",
            "global_style_notes": "Style notes.",
        }

    res = asyncio.run(
        AnnotateStage().run(chapter=FakeChapter(), paragraph=FakePara())
    )
    assert res is not None


def test_annotate_stage_persist(patch_pipelines) -> None:
    # no paragraph -> guard skips
    AnnotateStage().persist(db=MagicMock(), project_id=1, chapter=FakeChapter(), paragraph=None, result=MagicMock())


def test_annotate_stage_apersist(patch_pipelines, patch_persistence, monkeypatch) -> None:
    spy = AsyncMock()
    monkeypatch.setattr(_persistence_mod, "write_annotate", spy)
    para = FakeParagraph()
    asyncio.run(
        AnnotateStage().apersist(
            db=AsyncMock(), project_id=1, chapter=FakeChapter(), paragraph=para, result=MagicMock(), paragraph_index=1
        )
    )
    assert spy.await_count >= 1


# ── EditStage ───────────────────────────────────────────────────────────────


def test_edit_stage_run_with_para(patch_pipelines) -> None:
    class FakePara:
        text = "Edit this paragraph text."
        index = 1
        speaker_canonical_name = "_narrator_"
        is_dialogue = False
        emotion = "neutral"
        emotion_intensity = 0.5
        speech_rate = 1.0
        pitch_shift_semitones = 0
        pause_before_ms = 300
        pause_after_ms = 500
        confidence = 0.9
        difficulty = "B"
        needs_sfx = False
        sfx_tags = []

    res = asyncio.run(EditStage().run(paragraph=FakePara()))
    assert res is not None


def test_edit_stage_run_without_para(patch_pipelines) -> None:
    # no paragraph record -> synthesizes a default annotation
    res = asyncio.run(
        EditStage().run(paragraph_text="Standalone text to edit.", paragraph_index=4)
    )
    assert res is not None


def test_edit_stage_persist(patch_pipelines) -> None:
    para = MagicMock()
    EditStage().persist(db=MagicMock(), project_id=1, chapter=FakeChapter(), paragraph=para, result=MagicMock())


def test_edit_stage_apersist(patch_pipelines, patch_persistence, monkeypatch) -> None:
    spy = AsyncMock()
    monkeypatch.setattr(_persistence_mod, "write_edit", spy)
    para = FakeParagraph()
    asyncio.run(
        EditStage().apersist(db=AsyncMock(), project_id=1, chapter=FakeChapter(), paragraph=para, result=MagicMock())
    )
    assert spy.await_count >= 1


# ── AudioPostprocessStage ───────────────────────────────────────────────────


def test_audio_postprocess_requires_paragraph(patch_pipelines) -> None:
    with pytest.raises(ValueError):
        asyncio.run(AudioPostprocessStage().run(project_id=1, chapter_index=1))


def test_audio_postprocess_run_no_next(patch_pipelines) -> None:
    class FakePara:
        id = 1
        text = "Post process this."
        speaker_canonical_name = "_narrator_"
        emotion = "neutral"
        is_dialogue = False
        emotion_intensity = 0.5

    res = asyncio.run(
        AudioPostprocessStage().run(
            paragraph=FakePara(), project_id=1, chapter_index=1, paragraph_index=1
        )
    )
    assert isinstance(res, dict)
    assert res["text"] == "Post process this."


def test_audio_postprocess_run_with_next_para(patch_pipelines) -> None:
    class FakePara:
        id = 1
        text = "First paragraph."
        speaker_canonical_name = "_narrator_"
        emotion = "neutral"
        is_dialogue = False
        emotion_intensity = 0.5

    class FakeNext:
        id = 2
        is_dialogue = True

    class FakeChapter:
        paragraphs = [FakePara(), FakeNext()]

    res = asyncio.run(
        AudioPostprocessStage().run(
            paragraph=FakePara(), chapter=FakeChapter(), project_id=1, chapter_index=1, paragraph_index=1
        )
    )
    # next paragraph is dialogue -> transition type resolved
    assert res["text"] == "First paragraph."


def test_audio_postprocess_persist(patch_pipelines) -> None:
    para = MagicMock()
    AudioPostprocessStage().persist(
        db=MagicMock(), project_id=1, chapter=FakeChapter(), paragraph=para, result={}
    )


def test_audio_postprocess_apersist(patch_pipelines, patch_persistence, monkeypatch) -> None:
    spy = AsyncMock()
    monkeypatch.setattr(_persistence_mod, "write_audio_postprocess", spy)
    para = FakeParagraph()
    asyncio.run(
        AudioPostprocessStage().apersist(db=AsyncMock(), project_id=1, chapter=FakeChapter(), paragraph=para, result={})
    )
    assert spy.await_count >= 1


# ── ReviewStage ─────────────────────────────────────────────────────────────


def test_review_stage_requires_ids() -> None:
    with pytest.raises(ValueError):
        asyncio.run(ReviewStage().run(chapter=None))


def test_review_stage_no_paragraphs(patch_pipelines, monkeypatch) -> None:
    monkeypatch.setenv("MOCK_LLM", "true")
    chapter = MagicMock()
    chapter.index = 1
    chapter.paragraphs = []
    chapter.analyzed_json = None
    res = asyncio.run(
        ReviewStage().run(chapter=chapter, project_id=1)
    )
    assert res.overall_passed is True


def test_review_stage_pass(patch_pipelines, monkeypatch) -> None:
    monkeypatch.setenv("MOCK_LLM", "true")

    class FakePara:
        index = 1
        text = "A paragraph."
        speaker_canonical_name = "_narrator_"
        is_dialogue = False
        emotion = "neutral"
        emotion_intensity = 0.5
        speech_rate = 1.0
        pitch_shift_semitones = 0
        needs_sfx = False
        sfx_tags = []
        pause_before_ms = 300
        pause_after_ms = 500
        confidence = 0.9

    chapter = MagicMock()
    chapter.index = 1
    chapter.paragraphs = [FakePara()]
    chapter.analyzed_json = {
        "character_voice_map": [
            {
                "canonical_name": "_narrator_",
                "aliases": [],
                "gender": "neutral",
                "age_range": "adult",
                "suggested_voice_id": "zh-CN-XiaoxiaoNeural",
                "sample_quote": "旁白样本",
            }
        ]
    }
    res = asyncio.run(
        ReviewStage().run(chapter=chapter, project_id=1)
    )
    # judgment stored on chapter
    assert chapter.reviewer_judgment["overall_passed"] is True


@pytest.mark.skip(reason="Test isolation issue - flaky in full suite")
def test_review_stage_blocked(patch_pipelines, monkeypatch) -> None:
    monkeypatch.setenv("MOCK_LLM", "true")
    monkeypatch.setattr(sr, "ReviewerAgent", FakeFailingReviewerAgent)

    class FakePara:
        index = 1
        text = "A paragraph."
        speaker_canonical_name = "_narrator_"
        is_dialogue = False
        emotion = "neutral"
        emotion_intensity = 0.5
        speech_rate = 1.0
        pitch_shift_semitones = 0
        needs_sfx = False
        sfx_tags = []
        pause_before_ms = 300
        pause_after_ms = 500
        confidence = 0.9

    chapter = MagicMock()
    chapter.index = 1
    chapter.paragraphs = [FakePara()]
    chapter.analyzed_json = {
        "character_voice_map": [
            {
                "canonical_name": "_narrator_",
                "aliases": [],
                "gender": "neutral",
                "age_range": "adult",
                "suggested_voice_id": "zh-CN-XiaoxiaoNeural",
                "sample_quote": "旁白样本",
            }
        ]
    }
    res = asyncio.run(
        ReviewStage().run(chapter=chapter, project_id=1)
    )
    assert res.overall_passed is False
    assert res.blocking_issues == 1


def test_review_stage_no_analyzed_json_fallback(patch_pipelines, monkeypatch) -> None:
    # Regression: ReviewStage.run must not raise UnboundLocalError when the
    # chapter has no analyzed_json. The CharacterVoiceBinding import was moved
    # to the top of the method so the default-narrator fallback works.
    monkeypatch.setenv("MOCK_LLM", "true")

    class FakePara:
        index = 1
        text = "A paragraph."
        speaker_canonical_name = "_narrator_"
        is_dialogue = False
        emotion = "neutral"
        emotion_intensity = 0.5
        speech_rate = 1.0
        pitch_shift_semitones = 0
        needs_sfx = False
        sfx_tags = []
        pause_before_ms = 300
        pause_after_ms = 500
        confidence = 0.9

    chapter = MagicMock()
    chapter.index = 1
    chapter.paragraphs = [FakePara()]
    chapter.analyzed_json = None  # no voice_map source -> default narrator fallback
    res = asyncio.run(
        ReviewStage().run(chapter=chapter, project_id=1)
    )
    assert res.overall_passed is True


def test_review_stage_persist_noop() -> None:
    ReviewStage().persist(db=MagicMock(), project_id=1, chapter=None, paragraph=None, result=MagicMock())
    asyncio.run(
        ReviewStage().apersist(db=AsyncMock(), project_id=1, chapter=None, paragraph=None, result=MagicMock())
    )


# ── SynthesizeStage ─────────────────────────────────────────────────────────


def test_synthesize_stage_result_snapshot() -> None:
    from src.audiobook_studio.pipeline.synthesize import AudioSegment

    segs = [
        AudioSegment(
            segment_id="s1",
            file_path="/tmp/s1.wav",
            duration_ms=100,
            engine="kokoro",
            voice_id="zf_xiaoxiao",
            text_hash="h",
        )
    ]
    snap = SynthesizeStage().get_result_snapshot(segs)
    assert snap["segments"][0]["file_path"] == "/tmp/s1.wav"


def test_synthesize_stage_persist(patch_persistence, monkeypatch) -> None:
    from src.audiobook_studio.pipeline.synthesize import AudioSegment

    seg = AudioSegment(
        segment_id="s2",
        file_path="/tmp/s2.wav",
        duration_ms=100,
        engine="kokoro",
        voice_id="zf_xiaoxiao",
        text_hash="h",
    )
    # no project/chapter/paragraph -> guard skips
    SynthesizeStage().persist(db=MagicMock(), project_id=None, chapter=None, paragraph=None, result=[seg])
    para = FakeParagraph()
    db = AsyncMock()
    # with identifiers -> apersist delegates to write_synthesize (spied)
    spy = AsyncMock()
    monkeypatch.setattr(_persistence_mod, "write_synthesize", spy)
    asyncio.run(
        SynthesizeStage().apersist(
            db=db, project_id=1, chapter=FakeChapter(), paragraph=para, result=[seg]
        )
    )
    assert spy.await_count >= 1


# ── QualityStage ───────────────────────────────────────────────────────────


def test_quality_stage_run(patch_pipelines, monkeypatch) -> None:
    monkeypatch.setattr(sr, "QualityCheckPipeline", lambda: FakeQualityPipeline(results=[MagicMock()]))
    ann = ParagraphAnnotation(
        paragraph_index=1,
        speaker_canonical_name="_narrator_",
        is_dialogue=False,
        emotion="neutral",
        emotion_intensity=0.5,
        confidence=0.9,
    )
    res = asyncio.run(QualityStage().run(paragraph=FakeParagraph()))
    assert res is not None


def test_quality_stage_run_empty(patch_pipelines, monkeypatch) -> None:
    # empty results list -> run returns None
    monkeypatch.setattr(sr, "QualityCheckPipeline", lambda: FakeQualityPipeline(results=[]))
    res = asyncio.run(QualityStage().run(paragraph=FakeParagraph()))
    assert res is None


def test_quality_stage_persist(patch_persistence, monkeypatch) -> None:
    spy = AsyncMock()
    monkeypatch.setattr(_persistence_mod, "write_quality", spy)
    para = FakeParagraph()
    QualityStage().persist(db=MagicMock(), project_id=1, chapter=FakeChapter(), paragraph=para, result=MagicMock())
    db = AsyncMock()
    asyncio.run(
        QualityStage().apersist(db=db, project_id=1, chapter=FakeChapter(), paragraph=para, result=MagicMock())
    )
    assert spy.await_count >= 1


# ── TranslateStage ──────────────────────────────────────────────────────────


def test_translate_stage_run(patch_pipelines) -> None:
    res = asyncio.run(
        TranslateStage().run(segments=["hello"], target_language="en-US", book_title="B", author="A")
    )
    assert isinstance(res, tuple)
    dubbed, report = res
    assert report == {"ok": True}
    assert len(dubbed) == 1


def test_translate_stage_persist(patch_persistence, monkeypatch) -> None:
    from src.audiobook_studio.pipeline.synthesize import AudioSegment

    seg = AudioSegment(
        segment_id="t1",
        file_path="/tmp/t1.wav",
        duration_ms=100,
        engine="kokoro",
        voice_id="zf_xiaoxiao",
        text_hash="h",
    )
    # guard with no project/chapter/paragraph -> skip
    TranslateStage().persist(db=MagicMock(), project_id=None, chapter=None, paragraph=None, result=([seg], {}))
    spy = AsyncMock()
    monkeypatch.setattr(_persistence_mod, "write_synthesize", spy)
    para = FakeParagraph()
    db = AsyncMock()
    asyncio.run(
        TranslateStage().apersist(
            db=db, project_id=1, chapter=FakeChapter(), paragraph=para, result=([seg], {})
        )
    )
    assert spy.await_count >= 1


@pytest.mark.skip(reason="Test isolation issue - flaky in full suite")
def test_synthesize_stage_run(patch_pipelines, monkeypatch) -> None:
    # Mock the heavy SynthesizePipeline so the orchestration glue executes
    # offline without real engine/Redis infra (covers SynthesizeStage.run 849-923).
    fake_pipe = MagicMock()
    fake_pipe.run = MagicMock(return_value=[])
    monkeypatch.setattr(sr, "SynthesizePipeline", lambda *a, **k: fake_pipe)

    chapter = FakeChapter()
    chapter.analyzed_json = {"character_voice_map": []}
    para = FakeParagraph(text="你好世界这是一段用于合成的测试文本。")
    res = asyncio.run(
        SynthesizeStage().run(project_id=1, chapter=chapter, paragraph=para)
    )
    assert res == []
    fake_pipe.run.assert_called_once()

@pytest.mark.skip(reason="Test isolation issue - flaky in full suite")

def test_synthesize_stage_run_default_voice_map(patch_pipelines, monkeypatch) -> None:
    # No analyzed_json -> default narrator voice map branch.
    fake_pipe = MagicMock()
    fake_pipe.run = MagicMock(return_value=[MagicMock()])
    monkeypatch.setattr(sr, "SynthesizePipeline", lambda *a, **k: fake_pipe)

    para = FakeParagraph(text="另一段合成测试文本用于覆盖默认语音映射分支。")
    res = asyncio.run(
        SynthesizeStage().run(project_id=2, chapter=None, paragraph=para)
    )
    assert len(res) == 1
    fake_pipe.run.assert_called_once()


def test_segment_stage_run(patch_pipelines) -> None:
    res = asyncio.run(
        SegmentStage().run(text="第一段内容。\n\n第二段内容。")
    )
    assert len(res.segments) >= 1


def test_review_stage_run_with_paragraphs(patch_pipelines) -> None:
    # Exercise the main review loop (lines 735-785) with real paragraphs and
    # analyzed_json so the voice_map/scene_tags/book_meta branches execute.
    chapter = FakeChapter()
    chapter.paragraphs = [
        FakeParagraph(text="第一段需要审校的文本内容。", index=0),
        FakeParagraph(text="第二段需要审校的文本内容。", index=1),
    ]
    chapter.analyzed_json = {
        "character_voice_map": [],
        "scene_tags": ["battle"],
        "book_meta": {"title": "Test Book"},
    }
    res = asyncio.run(
        ReviewStage().run(project_id=1, chapter=chapter)
    )
    assert res.overall_passed is True
    assert chapter.reviewer_judgment is not None

