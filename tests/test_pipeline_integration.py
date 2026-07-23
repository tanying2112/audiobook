"""Integration tests for full pipeline in mock mode."""

import os

os.environ["MOCK_LLM"] = "true"

import sys

import pytest

from audiobook_studio.pipeline import (
    analyze_structure,
    annotate_paragraph,
    edit_for_tts,
    extract_text,
    quality_check,
    synthesize_paragraphs,
)
from audiobook_studio.schemas import (
    BookAnalysisInput,
    BookAnalysisOutput,
    BookMeta,
    CharacterVoiceBinding,
    EmotionSnapshot,
    ExtractionInput,
    ExtractionResult,
    ParagraphAnnotation,
    ParagraphAnnotationInput,
    QualityJudgment,
    TtsEditInput,
    TtsEditOutput,
    TtsRoutingDecision,
    TtsRoutingInput,
)


def test_extract_mock():
    result = extract_text(
        file_path="/fake/path/test.pdf",
        mime_type="application/pdf",
        detect_language=True,
        mock_mode=True,
    )
    assert isinstance(result, ExtractionResult)
    assert result.language == "zh"
    assert result.page_count == 5
    assert result.has_ocr is False


def test_analyze_structure_mock():
    test_text = "第一章  测试文本内容..."
    result = analyze_structure(test_text, title_hint="测试书", mock_mode=True)
    assert isinstance(result, BookAnalysisOutput)
    assert result.book_meta.title == "Test Book"
    assert len(result.character_voice_map) >= 1
    assert len(result.emotion_snapshots) >= 1


def test_annotate_paragraph_mock():
    book_meta = BookMeta(
        title="测试",
        author="作者",
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
            suggested_voice_id="v1",
            sample_quote="测试",
        ),
        CharacterVoiceBinding(
            canonical_name="主角",
            aliases=[],
            gender="male",
            age_range="young",
            suggested_voice_id="v2",
            sample_quote="测试",
        ),
    ]
    emotion_snapshot = EmotionSnapshot(chapter=1, dominant_emotion="neutral", intensity=0.5)

    result = annotate_paragraph(
        paragraph_text="测试段落文本内容...",
        paragraph_index=0,
        chapter_index=1,
        book_meta=book_meta,
        character_voice_map=character_voice_map,
        emotion_snapshot=emotion_snapshot,
        story_line_summary="这是一个用于测试的模拟故事摘要，包含足够的字符数以满足最小长度要求，用于验证模拟模式下的段落标注功能是否正常工作。为了确保字符长度超过一百个字符，我在这里继续添加更多的描述性文本内容，包括对故事背景、人物关系、情节发展等方面的详细说明。",
        global_style_notes="测试文风",
        mock_mode=True,
    )
    assert isinstance(result, ParagraphAnnotation)
    assert result.speaker_canonical_name == "旁白"
    assert result.confidence == 0.9


def test_edit_for_tts_mock():
    from audiobook_studio.schemas import ParagraphAnnotation

    annotation = ParagraphAnnotation(
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
    )

    result = edit_for_tts(
        paragraph_text="测试文本",
        paragraph_annotation=annotation,
        difficulty="B",
        mock_mode=True,
    )
    assert isinstance(result, TtsEditOutput)
    assert "mock_mode_no_changes" in result.changes_made


def test_synthesize_mock():
    from audiobook_studio.schemas import CharacterVoiceBinding, ParagraphAnnotation

    annotation = ParagraphAnnotation(
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
    )
    char_map = [
        CharacterVoiceBinding(
            canonical_name="旁白",
            aliases=[],
            gender="neutral",
            age_range="adult",
            suggested_voice_id="v1",
            sample_quote="测试",
        ),
    ]

    inputs = [
        TtsRoutingInput(
            paragraph_annotation=annotation,
            text="测试文本",
            character_voice_map=char_map,
            book_id="test_book",
            chapter_index=1,
            paragraph_index=0,
            cumulative_cost_usd=0.0,
            cost_limit_per_book=20.0,
            cost_limit_per_chapter=5.0,
            prefer_local=True,
        )
    ]

    segments = synthesize_paragraphs(inputs, mock_mode=True)
    assert len(segments) == 1
    assert segments[0].engine == "kokoro"


def test_quality_check_mock():
    from audiobook_studio.schemas import ParagraphAnnotation, TtsRoutingDecision

    annotation = ParagraphAnnotation(
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
    )
    routing = TtsRoutingDecision(
        segment_id="test_ch1_p0",
        engine_choice="kokoro",
        voice_id="v1",
        prosody_overrides={},
        fallback_engine="edge",
        reasoning="mock",
        estimated_cost_usd=0.0,
        estimated_duration_ms=3000,
    )

    inputs = [("./output/test.mp3", annotation, routing, "参考文本")]
    judgments = quality_check(inputs, mock_mode=True)

    assert len(judgments) == 1
    assert isinstance(judgments[0], QualityJudgment)
    assert judgments[0].overall_score > 0.5


def test_full_pipeline_mock():
    # 1. Extract
    extraction = extract_text("/fake/book.pdf", "application/pdf", mock_mode=True)
    assert extraction.raw_text

    # 2. Analyze structure
    analysis = analyze_structure(extraction.raw_text, title_hint="测试书", mock_mode=True)
    assert analysis.book_meta.title

    # 3. Annotate first paragraph
    para_text = "第一章  这是测试段落。"
    annotation = annotate_paragraph(
        paragraph_text=para_text,
        paragraph_index=0,
        chapter_index=1,
        book_meta=analysis.book_meta,
        character_voice_map=analysis.character_voice_map,
        emotion_snapshot=analysis.emotion_snapshots[0],
        story_line_summary="这是一个用于测试的模拟故事摘要，包含足够的字符数以满足最小长度要求，用于验证模拟模式下的段落标注功能是否正常工作。为了确保字符长度超过一百个字符，我在这里继续添加更多的描述性文本内容，包括对故事背景、人物关系、情节发展等方面的详细说明。",
        global_style_notes=analysis.global_style_notes,
        mock_mode=True,
    )
    assert annotation.speaker_canonical_name

    # 4. Edit for TTS
    edited = edit_for_tts(
        paragraph_text=para_text,
        paragraph_annotation=annotation,
        difficulty=analysis.book_meta.difficulty,
        mock_mode=True,
    )
    assert edited.edited_text

    # 5. Synthesize
    char_map = [
        CharacterVoiceBinding(
            canonical_name=c.canonical_name,
            aliases=c.aliases,
            gender=c.gender,
            age_range=c.age_range,
            suggested_voice_id=c.suggested_voice_id,
            sample_quote=c.sample_quote,
        )
        for c in analysis.character_voice_map
    ]
    routing_input = TtsRoutingInput(
        paragraph_annotation=annotation,
        text=para_text,
        character_voice_map=char_map,
        book_id="test",
        chapter_index=1,
        paragraph_index=0,
        cumulative_cost_usd=0.0,
        cost_limit_per_book=20.0,
        cost_limit_per_chapter=5.0,
        prefer_local=True,
    )
    segments = synthesize_paragraphs([routing_input], mock_mode=True)
    assert len(segments) == 1

    # 6. Quality check
    from audiobook_studio.schemas import TtsRoutingDecision

    routing_decision = TtsRoutingDecision(
        segment_id="test_ch1_p0",
        engine_choice="kokoro",
        voice_id="v1",
        prosody_overrides={},
        fallback_engine="edge",
        reasoning="mock",
        estimated_cost_usd=0.0,
        estimated_duration_ms=3000,
    )
    judgments = quality_check([("./output/test.mp3", annotation, routing_decision, para_text)], mock_mode=True)
    assert len(judgments) == 1
    assert judgments[0].overall_score > 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
