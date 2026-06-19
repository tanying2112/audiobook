"""Comprehensive unit tests for orchestrator pipeline targeting ≥80% line coverage.

Tests match the ACTUAL API from src/audiobook_studio/pipeline/orchestrator.py:
- run_stage() with all 7 stages: extract, analyze, annotate, edit, audio_postprocess, synthesize, quality
- DB write functions: _write_extract, _write_analyze, _write_annotate, _write_edit,
  _write_synthesize, _write_quality, _write_audio_postprocess
- Mock mode behavior for testing without external APIs
- FeedbackCollector integration for self-iteration
"""

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, PropertyMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.audiobook_studio.database import Base
from src.audiobook_studio.models import (
    AudioSegment,
    Chapter,
    Paragraph,
    Project,
    Quality,
    TTSEdit,
)
from src.audiobook_studio.pipeline.feedback_collector import FeedbackCollector
from src.audiobook_studio.pipeline.orchestrator import (
    _write_analyze,
    _write_annotate,
    _write_audio_postprocess,
    _write_edit,
    _write_extract,
    _write_quality,
    _write_synthesize,
    run_stage,
)

# Create in-memory SQLite database for testing
TEST_ENGINE = create_engine("sqlite:///:memory:", echo=False)
TestingSessionLocal = sessionmaker(bind=TEST_ENGINE)


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database session for each test."""
    Base.metadata.create_all(TEST_ENGINE)
    session = TestingSessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(TEST_ENGINE)


@pytest.fixture
def sample_project(db_session):
    """Create a sample project."""
    project = Project(
        title="Test Book",
        author="Test Author",
        genre="小说",
        language="zh",
        difficulty="B",
    )
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)
    return project


@pytest.fixture
def sample_chapter(db_session, sample_project):
    """Create a sample chapter."""
    chapter = Chapter(
        project_id=sample_project.id,
        index=1,
        raw_text="第一章 开始\n\n这是测试内容。",
        extract_status="completed",
    )
    db_session.add(chapter)
    db_session.commit()
    db_session.refresh(chapter)
    return chapter


@pytest.fixture
def sample_paragraph(db_session, sample_project, sample_chapter):
    """Create a sample paragraph."""
    para = Paragraph(
        project_id=sample_project.id,
        chapter_id=sample_chapter.id,
        index=0,
        chapter_index=1,
        text="这是测试段落内容。",
        speaker="旁白",
        is_dialogue=False,
        emotion="neutral",
        emotion_intensity=0.5,
        status="annotated",
    )
    db_session.add(para)
    db_session.commit()
    db_session.refresh(para)
    return para


@pytest.fixture
def sample_paragraph_with_edit(db_session, sample_project, sample_chapter):
    """Create a sample paragraph with edited_text for quality testing."""
    para = Paragraph(
        project_id=sample_project.id,
        chapter_id=sample_chapter.id,
        index=0,
        chapter_index=1,
        text="这是测试段落内容。",
        speaker="旁白",
        is_dialogue=False,
        emotion="neutral",
        emotion_intensity=0.5,
        status="edited",
        edited_text="这是编辑后的测试段落文本内容。",
        edit_confidence=0.9,
        edit_difficulty="B",
        edit_forbid_edit=False,
    )
    db_session.add(para)
    db_session.commit()
    db_session.refresh(para)
    return para


@pytest.fixture
def mock_extraction_result():
    """Create a valid ExtractionResult for testing."""
    from src.audiobook_studio.schemas import ExtractionResult

    return ExtractionResult(
        raw_text="这是一个用于测试的模拟提取文本，包含足够的字符数以满足最小长度要求。第一章  从前有一个小女孩，她戴着红色的帽子，大家都叫她小红帽。",
        language="zh",
        page_count=5,
        has_ocr=False,
        ocr_page_ratio=0.0,
        warnings=[],
    )


@pytest.fixture
def mock_book_analysis_output():
    """Create a valid BookAnalysisOutput for testing."""
    from src.audiobook_studio.schemas import (
        BookAnalysisOutput,
        BookMeta,
        CharacterVoiceBinding,
        EmotionSnapshot,
    )

    return BookAnalysisOutput(
        book_meta=BookMeta(
            title="Mock Title",
            author="Mock Author",
            genre="小说",
            difficulty="B",
            language="zh",
            era="现代",
            total_chapters_estimated=10,
        ),
        character_voice_map=[
            CharacterVoiceBinding(
                canonical_name="旁白",
                aliases=[],
                gender="neutral",
                age_range="adult",
                suggested_voice_id="kokoro_narrator",
                sample_quote="这是旁白的样本文本。",
            ),
        ],
        emotion_snapshots=[
            EmotionSnapshot(
                chapter=1,
                dominant_emotion="neutral",
                intensity=0.5,
                notes="平静的开头",
            ),
        ],
        story_line_summary="这是一个关于测试的故事，主角经历各种冒险最终成功，并在过程中获得了宝贵的友谊和成长。"
        * 3,
        global_style_notes="Mock style notes.",
    )


@pytest.fixture
def mock_paragraph_annotation():
    """Create a valid ParagraphAnnotation for testing."""
    from src.audiobook_studio.schemas import ParagraphAnnotation

    return ParagraphAnnotation(
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
        notes="Test annotation",
    )


@pytest.fixture
def mock_tts_edit_output():
    """Create a valid TtsEditOutput for testing."""
    from src.audiobook_studio.schemas import TtsEditOutput

    return TtsEditOutput(
        edited_text="这是一个足够长的测试段落文本内容，用于编辑。",
        changes_made=["mock_mode_no_changes"],
        forbidden_content_removed=[],
        confidence=0.9,
        rationale="Mock mode: no actual editing",
    )


@pytest.fixture
def mock_quality_judgment():
    """Create a valid QualityJudgment for testing."""
    from src.audiobook_studio.schemas import QualityJudgment
    from src.audiobook_studio.schemas.quality import FixSuggestion

    return QualityJudgment(
        segment_id="test_book_ch1_p0",
        speaker_clarity=0.9,
        emotion_match=0.85,
        prosody_naturalness=0.9,
        text_audio_alignment=0.95,
        overall_score=0.9,
        issues=[],
        fix_suggestions=[],
        needs_regeneration=False,
        contract_version=1,
    )


@pytest.fixture
def mock_audio_segments():
    """Create mock AudioSegment dataclasses for testing."""
    from src.audiobook_studio.models.audio_segment import AudioSegment

    return [
        AudioSegment(
            file_path="/tmp/test_segment_0.mp3",
            duration_ms=5000,
            engine="kokoro",
            voice_id="kokoro_narrator",
        ),
    ]


class TestWriteExtract:
    """Test _write_extract function."""

    def test_write_extract_creates_new_chapter(
        self, db_session, sample_project, mock_extraction_result
    ):
        """Test _write_extract creates a new chapter when none exists."""
        chapter = _write_extract(
            db_session,
            project_id=sample_project.id,
            chapter_index=1,
            result=mock_extraction_result,
        )

        assert chapter is not None
        assert chapter.project_id == sample_project.id
        assert chapter.index == 1
        assert chapter.raw_text == mock_extraction_result.raw_text
        assert chapter.extract_status == "completed"

    def test_write_extract_updates_existing_chapter_by_id(
        self, db_session, sample_project, sample_chapter, mock_extraction_result
    ):
        """Test _write_extract updates existing chapter when chapter_id provided."""
        # Modify the existing chapter
        sample_chapter.raw_text = "Old text"
        sample_chapter.extract_status = "pending"
        db_session.commit()

        chapter = _write_extract(
            db_session,
            project_id=sample_project.id,
            chapter_index=1,
            result=mock_extraction_result,
            chapter_id=sample_chapter.id,
        )

        assert chapter.id == sample_chapter.id
        assert chapter.raw_text == mock_extraction_result.raw_text
        assert chapter.extract_status == "completed"

    def test_write_extract_uses_existing_chapter_by_index(
        self, db_session, sample_project, sample_chapter, mock_extraction_result
    ):
        """Test _write_extract finds existing chapter by project_id and index."""
        sample_chapter.raw_text = "Old text"
        sample_chapter.extract_status = "pending"
        db_session.commit()

        chapter = _write_extract(
            db_session,
            project_id=sample_project.id,
            chapter_index=1,
            result=mock_extraction_result,
        )

        assert chapter.id == sample_chapter.id
        assert chapter.raw_text == mock_extraction_result.raw_text


class TestWriteAnalyze:
    """Test _write_analyze function."""

    def test_write_analyze_updates_chapter(
        self, db_session, sample_chapter, mock_book_analysis_output
    ):
        """Test _write_analyze updates chapter with analysis output."""
        _write_analyze(db_session, sample_chapter, mock_book_analysis_output)

        db_session.refresh(sample_chapter)
        assert sample_chapter.analyzed_json is not None
        assert "book_meta" in sample_chapter.analyzed_json
        assert sample_chapter.analyze_status == "completed"
        assert sample_chapter.analyzed_json["book_meta"]["title"] == "Mock Title"


class TestWriteAnnotate:
    """Test _write_annotate function."""

    def test_write_annotate_creates_new_paragraph(
        self,
        db_session,
        sample_project,
        sample_chapter,
        sample_paragraph,
        mock_paragraph_annotation,
    ):
        """Test _write_annotate updates existing paragraph (requires text field)."""
        para = _write_annotate(
            db_session,
            project_id=sample_project.id,
            chapter=sample_chapter,
            paragraph_index=0,
            result=mock_paragraph_annotation,
        )

        assert para is not None
        assert para.id == sample_paragraph.id
        assert para.project_id == sample_project.id
        assert para.chapter_id == sample_chapter.id
        assert para.index == 0
        assert para.speaker_canonical_name == "旁白"
        assert para.is_dialogue is False
        assert para.emotion == "neutral"
        assert para.status == "annotated"

    def test_write_annotate_updates_existing_paragraph(
        self,
        db_session,
        sample_project,
        sample_chapter,
        sample_paragraph,
        mock_paragraph_annotation,
    ):
        """Test _write_annotate updates existing paragraph."""
        sample_paragraph.speaker_canonical_name = "旧说话人"
        sample_paragraph.emotion = "happy"
        sample_paragraph.status = "pending"
        db_session.commit()

        para = _write_annotate(
            db_session,
            project_id=sample_project.id,
            chapter=sample_chapter,
            paragraph_index=0,
            result=mock_paragraph_annotation,
        )

        assert para.id == sample_paragraph.id
        assert para.speaker_canonical_name == "旁白"
        assert para.emotion == "neutral"
        assert para.status == "annotated"


class TestWriteEdit:
    """Test _write_edit function."""

    def test_write_edit_creates_tts_edit_record(self, db_session, sample_paragraph):
        """Test _write_edit creates TTSEdit record and updates paragraph."""
        # Create a mock result that satisfies production code expectations
        # (changes_made should be list of objects with model_dump())
        mock_change = MagicMock()
        mock_change.model_dump.return_value = {"type": "test_change"}

        mock_result = MagicMock()
        mock_result.edited_text = "这是编辑后的文本内容。"
        mock_result.changes_made = [mock_change]
        mock_result.forbidden_content_removed = []
        mock_result.confidence = 0.9
        mock_result.rationale = "Test edit rationale"
        mock_result.difficulty = "B"
        mock_result.forbid_edit = False

        tts_edit = _write_edit(db_session, sample_paragraph, mock_result)
        assert tts_edit is not None

        assert tts_edit is not None
        assert tts_edit.paragraph_id == sample_paragraph.id
        assert tts_edit.edited_text == "这是编辑后的文本内容。"
        assert tts_edit.confidence == 0.9

        # Check paragraph was updated
        db_session.refresh(sample_paragraph)
        assert sample_paragraph.edited_text == "这是编辑后的文本内容。"
        assert sample_paragraph.edit_confidence == 0.9
        assert sample_paragraph.status == "edited"


class TestWriteSynthesize:
    """Test _write_synthesize function."""

    def test_write_synthesize_creates_audio_segment(
        self, db_session, sample_project, sample_chapter, sample_paragraph
    ):
        """Test _write_synthesize creates AudioSegment record."""
        seg_dict = {
            "file_path": "/tmp/test_synthesis.mp3",
            "duration_ms": 5000,
            "engine": "kokoro",
            "voice_id": "kokoro_narrator",
            "format": "mp3",
        }

        audio = _write_synthesize(
            db_session, sample_project.id, sample_chapter, sample_paragraph, seg_dict
        )

        assert audio is not None
        assert audio.project_id == sample_project.id
        assert audio.chapter_id == sample_chapter.id
        assert audio.paragraph_id == sample_paragraph.id
        assert audio.file_path == "/tmp/test_synthesis.mp3"
        assert audio.duration_ms == 5000
        assert audio.engine == "kokoro"
        assert audio.voice_id == "kokoro_narrator"
        assert audio.status == "completed"

        # Check paragraph was linked
        db_session.refresh(sample_paragraph)
        assert sample_paragraph.audio_segment_id == audio.id
        assert sample_paragraph.status == "synthesized"


class TestWriteQuality:
    """Test _write_quality function."""

    def test_write_quality_creates_quality_record_with_existing_tts_edit(
        self, db_session, sample_project, sample_chapter, sample_paragraph, mock_quality_judgment
    ):
        """Test _write_quality works when TTSEdit already exists."""
        # Create a TTSEdit first
        tts_edit = TTSEdit(
            project_id=sample_project.id,
            chapter_id=sample_chapter.id,
            paragraph_id=sample_paragraph.id,
            edited_text="编辑后文本",
            changes_made=[],
            confidence=0.9,
        )
        db_session.add(tts_edit)
        db_session.commit()
        db_session.refresh(tts_edit)

        quality = _write_quality(
            db_session, sample_project.id, sample_chapter, sample_paragraph, mock_quality_judgment
        )

        assert quality is not None
        assert quality.tts_edit_id == tts_edit.id
        assert quality.overall_score == 0.9

        # Check paragraph was updated
        db_session.refresh(sample_paragraph)
        assert sample_paragraph.quality_overall_score == 0.9
        assert sample_paragraph.status == "quality_checked"

    def test_write_quality_creates_tts_edit_if_missing(
        self, db_session, sample_project, sample_chapter, sample_paragraph_with_edit, mock_quality_judgment
    ):
        """Test _write_quality auto-creates TTSEdit when none exists but paragraph has edited_text."""
        # Ensure no TTSEdit exists
        db_session.query(TTSEdit).filter(TTSEdit.paragraph_id == sample_paragraph_with_edit.id).delete()
        db_session.commit()

        quality = _write_quality(
            db_session, sample_project.id, sample_chapter, sample_paragraph_with_edit, mock_quality_judgment
        )

        assert quality is not None
        assert quality.tts_edit_id is not None

        # Verify a TTSEdit was created
        created_tts_edit = db_session.query(TTSEdit).filter(TTSEdit.id == quality.tts_edit_id).first()
        assert created_tts_edit is not None
        assert created_tts_edit.edited_text == sample_paragraph_with_edit.edited_text
        assert created_tts_edit.rationale == "Auto-created for quality check"

        # Check paragraph was updated
        db_session.refresh(sample_paragraph_with_edit)
        assert sample_paragraph_with_edit.quality_overall_score == 0.9
        assert sample_paragraph_with_edit.status == "quality_checked"

    def test_write_quality_handles_missing_edited_text(
        self, db_session, sample_project, sample_chapter, sample_paragraph, mock_quality_judgment
    ):
        """Test _write_quality handles case where no TTSEdit exists and no edited_text."""
        # Ensure no TTSEdit exists and paragraph has no edited_text
        db_session.query(TTSEdit).filter(TTSEdit.paragraph_id == sample_paragraph.id).delete()
        sample_paragraph.edited_text = None
        db_session.commit()

        quality = _write_quality(
            db_session, sample_project.id, sample_chapter, sample_paragraph, mock_quality_judgment
        )

        assert quality is not None
        assert quality.tts_edit_id is None  # Should be None when no TTSEdit can be created

        # Check paragraph was still updated
        db_session.refresh(sample_paragraph)
        assert sample_paragraph.quality_overall_score == 0.9
        assert sample_paragraph.status == "quality_checked"


class TestWriteAudioPostProcess:
    """Test _write_audio_postprocess function."""

    def test_write_audio_postprocess_updates_paragraph(
        self, db_session, sample_paragraph
    ):
        """Test _write_audio_postprocess updates paragraph with audio params."""
        from src.audiobook_studio.schemas import AudioPostProcessParams

        params = AudioPostProcessParams(
            speech_rate=1.1,
            pitch_shift_semitones=2,
            needs_sfx=True,
            sfx_tags=["door_creak", "wind"],
        )

        _write_audio_postprocess(db_session, sample_paragraph, params)

        db_session.refresh(sample_paragraph)
        assert sample_paragraph.speech_rate == 1.1
        assert sample_paragraph.pitch_shift_semitones == 2
        assert sample_paragraph.needs_sfx is True
        assert sample_paragraph.sfx_tags == ["door_creak", "wind"]
        assert sample_paragraph.status == "audio_processed"


class TestRunStageExtract:
    """Test run_stage for extract stage."""

    def test_run_stage_extract(
        self, db_session, sample_project, mock_extraction_result
    ):
        """Test run_stage with extract stage."""
        with patch(
            "src.audiobook_studio.pipeline.orchestrator.ExtractPipeline"
        ) as MockPipeline:
            mock_pipeline = MockPipeline.return_value
            mock_pipeline.run.return_value = mock_extraction_result

            result = run_stage(
                "extract",
                db_session,
                project_id=sample_project.id,
                chapter_index=1,
                mock_mode=True,
                file_path="/fake/test.pdf",
                mime_type="application/pdf",
            )

            assert result == mock_extraction_result
            assert hasattr(result, "_chapter_id")
            mock_pipeline.run.assert_called_once()

            # Check chapter was created
            chapter = (
                db_session.query(Chapter)
                .filter(
                    Chapter.project_id == sample_project.id,
                    Chapter.index == 1,
                )
                .first()
            )
            assert chapter is not None
            assert chapter.raw_text == mock_extraction_result.raw_text


class TestRunStageAnalyze:
    """Test run_stage for analyze stage."""

    def test_run_stage_analyze(
        self, db_session, sample_project, sample_chapter, mock_book_analysis_output
    ):
        """Test run_stage with analyze stage."""
        with patch(
            "src.audiobook_studio.pipeline.orchestrator.AnalyzeStructurePipeline"
        ) as MockPipeline:
            mock_pipeline = MockPipeline.return_value
            mock_pipeline.run.return_value = mock_book_analysis_output

            result = run_stage(
                "analyze",
                db_session,
                project_id=sample_project.id,
                chapter_index=1,
                mock_mode=True,
                raw_text="第1章 测试\n\n内容",
                title_hint="测试",
                author_hint="作者",
                target_difficulty="B",
            )

            assert result == mock_book_analysis_output
            mock_pipeline.run.assert_called_once()

            # Check chapter was updated
            db_session.refresh(sample_chapter)
            assert sample_chapter.analyze_status == "completed"
            assert sample_chapter.analyzed_json["book_meta"]["title"] == "Mock Title"


class TestRunStageAnnotate:
    """Test run_stage for annotate stage."""

    def test_run_stage_annotate(
        self,
        db_session,
        sample_project,
        sample_chapter,
        sample_paragraph,
        mock_paragraph_annotation,
    ):
        """Test run_stage with annotate stage."""
        with patch(
            "src.audiobook_studio.pipeline.orchestrator.AnnotateParagraphPipeline"
        ) as MockPipeline:
            mock_pipeline = MockPipeline.return_value
            mock_pipeline.run.return_value = mock_paragraph_annotation

            # Create a proper BookMeta for the test
            from src.audiobook_studio.schemas import (
                BookMeta,
                CharacterVoiceBinding,
                EmotionSnapshot,
            )

            book_meta = BookMeta(
                title="测试书籍",
                author="测试作者",
                genre="小说",
                difficulty="B",
                language="zh",
                era="现代",
                total_chapters_estimated=10,
            )
            character_voice_map = [
                CharacterVoiceBinding(
                    canonical_name="旁白",
                    aliases=[],
                    gender="neutral",
                    age_range="adult",
                    suggested_voice_id="kokoro_narrator",
                    sample_quote="这是旁白的样本文本。",
                ),
            ]
            emotion_snapshot = EmotionSnapshot(
                chapter=1,
                dominant_emotion="neutral",
                intensity=0.5,
                notes="平静的开头",
            )

            result = run_stage(
                "annotate",
                db_session,
                project_id=sample_project.id,
                chapter_index=1,
                paragraph_index=0,
                mock_mode=True,
                paragraph_text="这是测试段落文本内容。",
                book_meta=book_meta,
                character_voice_map=character_voice_map,
                emotion_snapshot=emotion_snapshot,
                story_line_summary="这是一个关于测试的故事，主角经历各种冒险最终成功，并在过程中获得了宝贵的友谊和成长。"
                * 3,
                global_style_notes="文风轻松幽默，适合有声书朗读。",
            )

            assert result == mock_paragraph_annotation
            assert hasattr(result, "_paragraph_id")
            mock_pipeline.run.assert_called_once()

            # Check paragraph was updated (using existing fixture with text)
            db_session.refresh(sample_paragraph)
            assert sample_paragraph.speaker_canonical_name == "旁白"


class TestRunStageEdit:
    """Test run_stage for edit stage."""

    def test_run_stage_edit(self, db_session, sample_paragraph):
        """Test run_stage with edit stage."""
        with patch(
            "src.audiobook_studio.pipeline.orchestrator.EditForTtsPipeline"
        ) as MockPipeline:
            mock_pipeline = MockPipeline.return_value
            # Create a mock result that has changes_made as list of objects with model_dump()
            mock_change = MagicMock()
            mock_change.model_dump.return_value = {"type": "test_change"}

            mock_result = MagicMock()
            mock_result.edited_text = "这是编辑后的文本内容。"
            mock_result.changes_made = [mock_change]
            mock_result.forbidden_content_removed = []
            mock_result.confidence = 0.9
            mock_result.rationale = "Test edit rationale"
            mock_result.difficulty = "B"
            mock_result.forbid_edit = False

            mock_pipeline.run.return_value = mock_result

            result = run_stage(
                "edit",
                db_session,
                paragraph_id=sample_paragraph.id,
                mock_mode=True,
                paragraph_text="这是测试段落文本内容。",
                paragraph_annotation=mock_result,
                difficulty="B",
                forbid_edit=False,
            )

            assert result.edited_text == "这是编辑后的文本内容。"
            mock_pipeline.run.assert_called_once()

            # Check paragraph was updated
            db_session.refresh(sample_paragraph)
            assert sample_paragraph.edited_text == "这是编辑后的文本内容。"
            assert sample_paragraph.status == "edited"


class TestRunStageAudioPostProcess:
    """Test run_stage for audio_postprocess stage."""

    def test_run_stage_audio_postprocess(
        self, db_session, sample_project, sample_chapter, sample_paragraph
    ):
        """Test run_stage with audio_postprocess stage."""
        # Add analyzed_json to chapter
        sample_chapter.analyzed_json = {
            "character_voice_map": [
                {
                    "canonical_name": "旁白",
                    "aliases": [],
                    "gender": "neutral",
                    "age_range": "adult",
                    "suggested_voice_id": "kokoro_narrator",
                    "sample_quote": "样本",
                }
            ]
        }
        db_session.commit()

        with patch(
            "src.audiobook_studio.pipeline.orchestrator.AudioPostProcessor"
        ) as MockProcessor:
            mock_processor = MockProcessor.return_value
            from src.audiobook_studio.schemas import AudioPostProcessParams

            mock_processor.process.return_value = AudioPostProcessParams(
                speech_rate=1.0,
                pitch_shift_semitones=0,
                needs_sfx=False,
                sfx_tags=[],
            )

            result = run_stage(
                "audio_postprocess",
                db_session,
                project_id=sample_project.id,
                chapter_index=1,
                paragraph_index=0,
            )

            assert result is not None
            assert isinstance(result, AudioPostProcessParams)

            # Check paragraph was updated
            db_session.refresh(sample_paragraph)
            assert sample_paragraph.speech_rate == 1.0
            assert sample_paragraph.status == "audio_processed"


class TestRunStageSynthesize:
    """Test run_stage for synthesize stage."""

    def test_run_stage_synthesize(
        self,
        db_session,
        sample_project,
        sample_chapter,
        sample_paragraph,
        mock_audio_segments,
    ):
        """Test run_stage with synthesize stage."""
        with patch(
            "src.audiobook_studio.pipeline.orchestrator.SynthesizePipeline"
        ) as MockPipeline:
            mock_pipeline = MockPipeline.return_value
            mock_pipeline.run.return_value = mock_audio_segments

            result = run_stage(
                "synthesize",
                db_session,
                project_id=sample_project.id,
                chapter_index=1,
                paragraph_index=0,
                mock_mode=True,
                text="合成测试文本",
                voice_id="kokoro_narrator",
                engine="kokoro",
            )

            assert result == mock_audio_segments
            mock_pipeline.run.assert_called_once()

            # Check audio segment was created
            audio = (
                db_session.query(AudioSegment)
                .filter(
                    AudioSegment.project_id == sample_project.id,
                    AudioSegment.chapter_id == sample_chapter.id,
                    AudioSegment.paragraph_id == sample_paragraph.id,
                )
                .first()
            )
            assert audio is not None
            assert audio.file_path == "/tmp/test_segment_0.mp3"


class TestRunPipelineMockSynthesize:
    """Test Orchestrator.run_pipeline_mock synthesis routing inputs."""

    def test_run_pipeline_mock_passes_valid_synthesize_routing_inputs(
        self, tmp_path
    ):
        """Test mock pipeline synthesis receives field-validated routing inputs."""
        from src.audiobook_studio.orchestrator import Orchestrator

        source_path = tmp_path / "mock_book.txt"
        source_path.write_text(
            "这是第一段旁白文本。\n\n这是第二段角色A文本。",
            encoding="utf-8",
        )

        extraction_result = SimpleNamespace(
            raw_text=(
                "这是第一段旁白文本，内容足够用于 mock pipeline 合成。\n\n"
                "这是第二段角色A文本，用于验证合成阶段路由输入。"
            )
        )

        analysis_payload = {
            "book_meta": {
                "title": "Mock Book",
                "author": "Mock Author",
                "genre": "小说",
                "difficulty": "B",
                "language": "zh",
                "era": "现代",
                "total_chapters_estimated": 1,
            },
            "character_voice_map": [
                {
                    "canonical_name": "旁白",
                    "aliases": [],
                    "gender": "neutral",
                    "age_range": "adult",
                    "suggested_voice_id": "zh-CN-XiaoxiaoNeural",
                    "sample_quote": "这是第一段旁白文本。",
                },
                {
                    "canonical_name": "角色A",
                    "aliases": [],
                    "gender": "neutral",
                    "age_range": "adult",
                    "suggested_voice_id": "zh-CN-YunxiNeural",
                    "sample_quote": "这是第二段角色A文本。",
                },
            ],
            "paragraphs": [
                {
                    "id": 1,
                    "chapter_id": 1,
                    "chapter_index": 1,
                    "paragraph_index": 1,
                    "text": "这是第一段旁白文本，内容足够用于 mock pipeline 合成。",
                    "speaker_canonical_name": "旁白",
                    "is_dialogue": False,
                    "emotion": "neutral",
                    "emotion_intensity": 0.5,
                    "speech_rate": 1.0,
                    "pitch_shift_semitones": 0,
                },
                {
                    "id": 2,
                    "chapter_id": 1,
                    "chapter_index": 1,
                    "paragraph_index": 2,
                    "text": "这是第二段角色A文本，用于验证合成阶段路由输入。",
                    "speaker_canonical_name": "角色A",
                    "is_dialogue": True,
                    "emotion": "curious",
                    "emotion_intensity": 0.7,
                    "speech_rate": 1.0,
                    "pitch_shift_semitones": 1,
                },
            ],
        }

        with patch(
            "src.audiobook_studio.orchestrator.ExtractPipeline"
        ) as mock_extract_cls, patch(
            "src.audiobook_studio.orchestrator.AnalyzeStructurePipeline"
        ) as mock_analyze_cls, patch(
            "src.audiobook_studio.orchestrator.SynthesizePipeline"
        ) as mock_synthesize_cls:
            mock_extract_cls.return_value.run.return_value = extraction_result
            mock_analyze_cls.return_value.run.return_value = analysis_payload
            mock_synthesize_cls.return_value.run.return_value = [
                SimpleNamespace(file_path="segment_1.mp3"),
                SimpleNamespace(file_path="segment_2.mp3"),
            ]

            result = Orchestrator().run_pipeline_mock(
                file_path=str(source_path),
                output_dir=str(tmp_path / "output"),
            )

            assert result.status == "completed"
            assert result.error is None
            assert result.stages == ["extract", "analyze", "synthesize"]
            assert len(result.audio_segments) == 2

            mock_extract_cls.return_value.run.assert_called_once()
            mock_analyze_cls.return_value.run.assert_called_once()
            mock_synthesize_cls.assert_called_once()
            mock_synthesize_cls.return_value.run.assert_called_once()

            # 获取合成阶段的调用参数
            call_args = mock_synthesize_cls.return_value.run.call_args.args[0]

            # 基础长度校验
            assert len(call_args) >= 2

            # --- 验证第 1 段 (旁白) ---
            p1 = call_args[0]
            assert p1.paragraph_annotation.notes == "Mock annotation"
            assert p1.character_voice_map[0].canonical_name == "旁白"
            assert p1.character_voice_map[0].suggested_voice_id == "zh-CN-XiaoxiaoNeural"
            assert p1.character_voice_map[0].aliases == []
            assert p1.character_voice_map[0].gender == "neutral"

            # --- 验证第 2 段 (角色A) ---
            p2 = call_args[1]
            assert p2.paragraph_annotation.notes == "Mock annotation"
            assert p2.character_voice_map[1].canonical_name == "角色A"
            assert p2.character_voice_map[1].suggested_voice_id == "zh-CN-YunxiNeural"
            assert p2.character_voice_map[1].aliases == []
            assert p2.character_voice_map[1].gender == "neutral"


class TestRunStageQuality:
    """Test run_stage for quality stage."""

    def test_run_stage_quality(
        self, db_session, sample_project, sample_chapter, sample_paragraph_with_edit
    ):
        """Test run_stage with quality stage."""
        with patch(
            "src.audiobook_studio.pipeline.orchestrator.QualityCheckPipeline"
        ) as MockPipeline:
            mock_pipeline = MockPipeline.return_value
            from src.audiobook_studio.schemas import QualityJudgment

            mock_pipeline.run.return_value = QualityJudgment(
                segment_id="test_book_ch1_p0",
                speaker_clarity=0.9,
                emotion_match=0.85,
                prosody_naturalness=0.9,
                text_audio_alignment=0.95,
                overall_score=0.9,
                issues=[],
                fix_suggestions=[],
                needs_regeneration=False,
                contract_version=1,
            )

            result = run_stage(
                "quality",
                db_session,
                project_id=sample_project.id,
                chapter_index=1,
                paragraph_index=0,
                mock_mode=True,
                segment_id="test_book_ch1_p0",
                audio_path="/tmp/test.mp3",
                text="测试文本",
                annotation=None,
            )

            assert result.overall_score == 0.9
            mock_pipeline.run.assert_called_once()

            # Check quality record was created
            quality = (
                db_session.query(Quality)
                .filter(
                    Quality.project_id == sample_project.id,
                    Quality.chapter_id == sample_chapter.id,
                    Quality.paragraph_id == sample_paragraph_with_edit.id,
                )
                .first()
            )
            assert quality is not None
            assert quality.overall_score == 0.9
            assert quality.tts_edit_id is not None

            # Check paragraph was updated
            db_session.refresh(sample_paragraph_with_edit)
            assert sample_paragraph_with_edit.quality_overall_score == 0.9
            assert sample_paragraph_with_edit.status == "quality_checked"


class TestRunStageErrors:
    """Test run_stage error handling."""

    def test_run_stage_unknown_stage(self, db_session, sample_project):
        """Test run_stage raises error for unknown stage."""
        with pytest.raises(ValueError, match="Unknown pipeline stage"):
            run_stage(
                "unknown_stage",
                db_session,
                project_id=sample_project.id,
            )

    def test_run_stage_audio_postprocess_missing_paragraph(
        self, db_session, sample_project
    ):
        """Test run_stage audio_postprocess requires paragraph."""
        with pytest.raises(
            ValueError,
            match="audio_postprocess requires paragraph_id or paragraph_index",
        ):
            run_stage(
                "audio_postprocess",
                db_session,
                project_id=sample_project.id,
                chapter_index=1,
            )


class TestRunStageWithFeedbackCollector:
    """Test run_stage with FeedbackCollector integration."""

    def test_run_stage_extract_with_feedback(
        self, db_session, sample_project, mock_extraction_result
    ):
        """Test run_stage extract stage captures feedback."""
        mock_collector = MagicMock(spec=FeedbackCollector)
        mock_capture = MagicMock()
        mock_capture._disabled = False
        mock_collector.capture_stage.return_value = mock_capture

        with patch(
            "src.audiobook_studio.pipeline.orchestrator.ExtractPipeline"
        ) as MockPipeline:
            mock_pipeline = MockPipeline.return_value
            mock_pipeline.run.return_value = mock_extraction_result

            result = run_stage(
                "extract",
                db_session,
                project_id=sample_project.id,
                chapter_index=1,
                mock_mode=True,
                file_path="/fake/test.pdf",
                mime_type="application/pdf",
                feedback_collector=mock_collector,
            )

            assert result == mock_extraction_result
            mock_collector.capture_stage.assert_called_once()
            mock_capture.set_llm_output.assert_called_once()

    def test_run_stage_analyze_with_feedback(
        self, db_session, sample_project, sample_chapter, mock_book_analysis_output
    ):
        """Test run_stage analyze stage captures feedback."""
        mock_collector = MagicMock(spec=FeedbackCollector)
        mock_capture = MagicMock()
        mock_capture._disabled = False
        mock_collector.capture_stage.return_value = mock_capture

        with patch(
            "src.audiobook_studio.pipeline.orchestrator.AnalyzeStructurePipeline"
        ) as MockPipeline:
            mock_pipeline = MockPipeline.return_value
            mock_pipeline.run.return_value = mock_book_analysis_output

            result = run_stage(
                "analyze",
                db_session,
                project_id=sample_project.id,
                chapter_index=1,
                mock_mode=True,
                raw_text="第1章 测试\n\n内容",
                title_hint="测试",
                author_hint="作者",
                target_difficulty="B",
                feedback_collector=mock_collector,
            )

            assert result == mock_book_analysis_output
            mock_collector.capture_stage.assert_called_once()
            mock_capture.set_llm_output.assert_called_once()

    def test_run_stage_annotate_with_feedback(
        self,
        db_session,
        sample_project,
        sample_chapter,
        sample_paragraph,
        mock_paragraph_annotation,
    ):
        """Test run_stage annotate stage captures feedback."""
        mock_collector = MagicMock(spec=FeedbackCollector)
        mock_capture = MagicMock()
        mock_capture._disabled = False
        mock_collector.capture_stage.return_value = mock_capture

        with patch(
            "src.audiobook_studio.pipeline.orchestrator.AnnotateParagraphPipeline"
        ) as MockPipeline:
            mock_pipeline = MockPipeline.return_value
            mock_pipeline.run.return_value = mock_paragraph_annotation

            from src.audiobook_studio.schemas import (
                BookMeta,
                CharacterVoiceBinding,
                EmotionSnapshot,
            )

            book_meta = BookMeta(
                title="测试书籍",
                author="测试作者",
                genre="小说",
                difficulty="B",
                language="zh",
                era="现代",
                total_chapters_estimated=10,
            )
            character_voice_map = [
                CharacterVoiceBinding(
                    canonical_name="旁白",
                    aliases=[],
                    gender="neutral",
                    age_range="adult",
                    suggested_voice_id="kokoro_narrator",
                    sample_quote="这是旁白的样本文本。",
                ),
            ]
            emotion_snapshot = EmotionSnapshot(
                chapter=1,
                dominant_emotion="neutral",
                intensity=0.5,
                notes="平静的开头",
            )

            result = run_stage(
                "annotate",
                db_session,
                project_id=sample_project.id,
                chapter_index=1,
                paragraph_index=0,
                mock_mode=True,
                paragraph_text="这是测试段落文本内容。",
                book_meta=book_meta,
                character_voice_map=character_voice_map,
                emotion_snapshot=emotion_snapshot,
                story_line_summary="这是一个关于测试的故事，主角经历各种冒险最终成功，并在过程中获得了宝贵的友谊和成长。"
                * 3,
                global_style_notes="文风轻松幽默，适合有声书朗读。",
                feedback_collector=mock_collector,
            )

            assert result == mock_paragraph_annotation
            mock_collector.capture_stage.assert_called_once()
            mock_capture.set_llm_output.assert_called_once()

    def test_run_stage_edit_with_feedback(self, db_session, sample_paragraph):
        """Test run_stage edit stage captures feedback."""
        mock_collector = MagicMock(spec=FeedbackCollector)
        mock_capture = MagicMock()
        mock_capture._disabled = False
        mock_collector.capture_stage.return_value = mock_capture

        with patch(
            "src.audiobook_studio.pipeline.orchestrator.EditForTtsPipeline"
        ) as MockPipeline:
            mock_pipeline = MockPipeline.return_value
            mock_change = MagicMock()
            mock_change.model_dump.return_value = {"type": "test_change"}

            mock_result = MagicMock()
            mock_result.edited_text = "这是编辑后的文本内容。"
            mock_result.changes_made = [mock_change]
            mock_result.forbidden_content_removed = []
            mock_result.confidence = 0.9
            mock_result.rationale = "Test edit rationale"
            mock_result.difficulty = "B"
            mock_result.forbid_edit = False

            mock_pipeline.run.return_value = mock_result

            result = run_stage(
                "edit",
                db_session,
                project_id=sample_paragraph.project_id,
                paragraph_id=sample_paragraph.id,
                mock_mode=True,
                paragraph_text="这是测试段落文本内容。",
                paragraph_annotation=mock_result,
                difficulty="B",
                forbid_edit=False,
                feedback_collector=mock_collector,
            )

            assert result.edited_text == "这是编辑后的文本内容。"
            mock_collector.capture_stage.assert_called_once()
            mock_capture.set_llm_output.assert_called_once()

    def test_run_stage_audio_postprocess_with_feedback(
        self, db_session, sample_project, sample_chapter, sample_paragraph
    ):
        """Test run_stage audio_postprocess stage captures feedback."""
        mock_collector = MagicMock(spec=FeedbackCollector)
        mock_capture = MagicMock()
        mock_capture._disabled = False
        mock_collector.capture_stage.return_value = mock_capture

        sample_chapter.analyzed_json = {
            "character_voice_map": [
                {
                    "canonical_name": "旁白",
                    "aliases": [],
                    "gender": "neutral",
                    "age_range": "adult",
                    "suggested_voice_id": "kokoro_narrator",
                    "sample_quote": "样本",
                }
            ]
        }
        db_session.commit()

        with patch(
            "src.audiobook_studio.pipeline.orchestrator.AudioPostProcessor"
        ) as MockProcessor:
            mock_processor = MockProcessor.return_value
            from src.audiobook_studio.schemas import AudioPostProcessParams

            mock_processor.process.return_value = AudioPostProcessParams(
                speech_rate=1.0,
                pitch_shift_semitones=0,
                needs_sfx=False,
                sfx_tags=[],
            )

            result = run_stage(
                "audio_postprocess",
                db_session,
                project_id=sample_project.id,
                chapter_index=1,
                paragraph_index=0,
                feedback_collector=mock_collector,
            )

            assert result is not None
            mock_collector.capture_stage.assert_called_once()
            mock_capture.set_llm_output.assert_called_once()

    def test_run_stage_synthesize_with_feedback(
        self,
        db_session,
        sample_project,
        sample_chapter,
        sample_paragraph,
        mock_audio_segments,
    ):
        """Test run_stage synthesize stage captures feedback."""
        mock_collector = MagicMock(spec=FeedbackCollector)
        mock_capture = MagicMock()
        mock_capture._disabled = False
        mock_collector.capture_stage.return_value = mock_capture

        with patch(
            "src.audiobook_studio.pipeline.orchestrator.SynthesizePipeline"
        ) as MockPipeline:
            mock_pipeline = MockPipeline.return_value
            mock_pipeline.run.return_value = mock_audio_segments

            result = run_stage(
                "synthesize",
                db_session,
                project_id=sample_project.id,
                chapter_index=1,
                paragraph_index=0,
                mock_mode=True,
                text="合成测试文本",
                voice_id="kokoro_narrator",
                engine="kokoro",
                feedback_collector=mock_collector,
            )

            assert result == mock_audio_segments
            mock_collector.capture_stage.assert_called_once()
            mock_capture.set_llm_output.assert_called_once()

    def test_run_stage_quality_with_feedback(
        self, db_session, sample_project, sample_chapter, sample_paragraph_with_edit
    ):
        """Test run_stage quality stage captures feedback with quality_judge source."""
        mock_collector = MagicMock(spec=FeedbackCollector)
        mock_capture = MagicMock()
        mock_capture._disabled = False
        mock_collector.capture_stage.return_value = mock_capture

        with patch(
            "src.audiobook_studio.pipeline.orchestrator.QualityCheckPipeline"
        ) as MockPipeline:
            mock_pipeline = MockPipeline.return_value
            from src.audiobook_studio.schemas import QualityJudgment

            mock_pipeline.run.return_value = QualityJudgment(
                segment_id="test_book_ch1_p0",
                speaker_clarity=0.9,
                emotion_match=0.85,
                prosody_naturalness=0.9,
                text_audio_alignment=0.95,
                overall_score=0.9,
                issues=[],
                fix_suggestions=[],
                needs_regeneration=False,
                contract_version=1,
            )

            result = run_stage(
                "quality",
                db_session,
                project_id=sample_project.id,
                chapter_index=1,
                paragraph_index=0,
                mock_mode=True,
                segment_id="test_book_ch1_p0",
                audio_path="/tmp/test.mp3",
                text="测试文本",
                annotation=None,
                feedback_collector=mock_collector,
            )

            mock_collector.capture_stage.assert_called_once()
            mock_capture.set_llm_output.assert_called_once()
            mock_capture.set_source.assert_called_with("quality_judge")

    def test_run_stage_without_feedback_collector(
        self, db_session, sample_project, mock_extraction_result
    ):
        """Test run_stage works without feedback_collector (backward compatibility)."""
        with patch(
            "src.audiobook_studio.pipeline.orchestrator.ExtractPipeline"
        ) as MockPipeline:
            mock_pipeline = MockPipeline.return_value
            mock_pipeline.run.return_value = mock_extraction_result

            result = run_stage(
                "extract",
                db_session,
                project_id=sample_project.id,
                chapter_index=1,
                mock_mode=True,
                file_path="/fake/test.pdf",
                mime_type="application/pdf",
                # No feedback_collector
            )

            assert result == mock_extraction_result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
