"""Tests for pipeline/orchestrator.py — _write_* functions."""

import json
from unittest.mock import MagicMock

import pytest

from src.audiobook_studio.pipeline.orchestrator import (
    _write_analyze,
    _write_annotate,
    _write_audio_postprocess,
    _write_edit,
    _write_extract,
    _write_quality,
    _write_synthesize,
)
from src.audiobook_studio.schemas import (
    AudioPostProcessParams,
    BookAnalysisOutput,
    ExtractionResult,
    ParagraphAnnotation,
    QualityJudgment,
    TtsEditOutput,
)


@pytest.fixture
def mock_db():
    db = MagicMock()
    chapter = MagicMock()
    chapter.id = 1
    chapter.index = 1
    chapter.project_id = 1

    para = MagicMock()
    para.id = 10
    para.index = 1
    para.project_id = 1
    para.chapter_id = 1
    para.edited_text = ""

    db.query.return_value.filter.return_value.first.return_value = None
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    return db, chapter, para


class TestWriteExtract:
    def test_new_chapter(self, mock_db):
        db, _, _ = mock_db
        result = ExtractionResult(raw_text="hello", language="zh", page_count=1)
        _write_extract(db, project_id=1, chapter_index=1, result=result)
        db.add.assert_called()
        db.commit.assert_called()

    def test_existing_by_index(self, mock_db):
        db, chapter, _ = mock_db
        db.query.return_value.filter.return_value.first.side_effect = [chapter]
        result = ExtractionResult(raw_text="text", language="en", page_count=1)
        _write_extract(db, project_id=1, chapter_index=1, result=result)
        db.add.assert_not_called()

    def test_existing_by_id(self, mock_db):
        db, chapter, _ = mock_db
        db.query.return_value.filter.return_value.first.return_value = chapter
        result = ExtractionResult(raw_text="by id", language="en", page_count=1)
        _write_extract(db, project_id=1, chapter_index=1, result=result, chapter_id=5)
        db.add.assert_not_called()


class TestWriteAnalyze:
    def test_write(self, mock_db):
        db, chapter, _ = mock_db
        result = BookAnalysisOutput(
            book_meta={
                "title": "Test Book",
                "genre": "小说",
                "difficulty": "B",
                "language": "zh",
                "total_chapters_estimated": 10,
            },
            character_voice_map=[
                {
                    "canonical_name": "Alice",
                    "sample_quote": "Hello world",
                }
            ],
            emotion_snapshots=[{"chapter": 1, "dominant_emotion": "neutral", "intensity": 0.5}],
            story_line_summary="A" * 100,
            global_style_notes="n",
        )
        _write_analyze(db, chapter, result)
        db.commit.assert_called()
        assert chapter.analyze_status == "completed"


class TestWriteAnnotate:
    def test_new_paragraph(self, mock_db):
        db, chapter, _ = mock_db
        db.query.return_value.filter.return_value.first.return_value = None
        result = ParagraphAnnotation(
            paragraph_index=1,
            speaker_canonical_name="Alice",
            is_dialogue=True,
            emotion="happy",
            emotion_intensity=0.8,
            confidence=0.9,
        )
        _write_annotate(db, project_id=1, chapter=chapter, paragraph_index=1, result=result)
        db.add.assert_called()
        db.commit.assert_called()

    def test_existing_paragraph(self, mock_db):
        db, chapter, para = mock_db
        db.query.return_value.filter.return_value.first.return_value = para
        result = ParagraphAnnotation(
            paragraph_index=1,
            speaker_canonical_name="Bob",
            is_dialogue=False,
            emotion="sad",
            emotion_intensity=0.5,
            confidence=0.7,
        )
        _write_annotate(db, project_id=1, chapter=chapter, paragraph_index=1, result=result)
        db.commit.assert_called()


class TestWriteEdit:
    def test_with_changes(self, mock_db):
        db, _, para = mock_db
        result = TtsEditOutput(
            edited_text="edited",
            changes_made=["c1"],
            forbidden_content_removed=["forbidden1"],
            confidence=0.9,
            rationale="rat",
            difficulty="A",
            forbid_edit=False,
        )
        _write_edit(db, para, result)
        db.add.assert_called()
        db.commit.assert_called()
        assert para.status == "edited"

    def test_no_changes(self, mock_db):
        db, _, para = mock_db
        result = TtsEditOutput(
            edited_text="no change",
            changes_made=[],
            forbidden_content_removed=[],
            confidence=1.0,
            rationale="",
            difficulty="B",
            forbid_edit=False,
        )
        _write_edit(db, para, result)
        assert para.status == "edited"


class TestWriteSynthesize:
    def test_write(self, mock_db):
        db, chapter, para = mock_db
        seg = {
            "file_path": "/tmp/a.mp3",
            "format": "mp3",
            "duration_ms": 5000,
            "file_size_bytes": 10000,
            "engine": "kokoro",
            "voice_id": "v1",
        }
        _write_synthesize(db, project_id=1, chapter=chapter, para=para, segment_info=seg)
        db.add.assert_called()
        db.commit.assert_called()
        assert para.status == "synthesized"


class TestWriteQuality:
    def test_with_existing_tts_edit(self, mock_db):
        db, chapter, para = mock_db
        mock_tts_edit = MagicMock()
        mock_tts_edit.id = 42
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_tts_edit
        result = QualityJudgment(
            segment_id="seg1",
            speaker_clarity=0.9,
            emotion_match=0.8,
            prosody_naturalness=0.85,
            text_audio_alignment=0.9,
            overall_score=0.86,
            issues=[],
            needs_regeneration=False,
        )
        _write_quality(db, project_id=1, chapter=chapter, para=para, result=result)
        assert para.status == "quality_checked"

    def test_no_tts_edit_creates_dummy(self, mock_db):
        db, chapter, para = mock_db
        from src.audiobook_studio.models.tts_edit import TTSEdit as TTSEditModel

        mock_tts_edit_query = MagicMock()
        mock_tts_edit_query.order_by.return_value.first.return_value = None

        def query_side_effect(model):
            if model is TTSEditModel:
                return mock_tts_edit_query
            chain = MagicMock()
            chain.filter.return_value.first.return_value = None
            return chain

        db.query.side_effect = query_side_effect
        result = QualityJudgment(
            segment_id="seg2",
            speaker_clarity=0.8,
            emotion_match=0.7,
            prosody_naturalness=0.9,
            text_audio_alignment=0.85,
            overall_score=0.81,
            issues=[],
            needs_regeneration=True,
        )
        _write_quality(db, project_id=1, chapter=chapter, para=para, result=result)
        assert para.status == "quality_checked"


class TestWriteAudioPostprocess:
    def test_write(self, mock_db):
        db, _, para = mock_db
        params = AudioPostProcessParams(
            speech_rate=1.2,
            pitch_shift_semitones=2,
            needs_sfx=True,
            sfx_tags=["wind"],
        )
        _write_audio_postprocess(db, para, params)
        db.commit.assert_called()
        assert para.status == "audio_processed"
        assert para.speech_rate == 1.2
        assert para.needs_sfx is True

    def test_defaults(self, mock_db):
        db, _, para = mock_db
        params = AudioPostProcessParams()
        _write_audio_postprocess(db, para, params)
        assert para.needs_sfx is False
        assert para.speech_rate == 1.0
