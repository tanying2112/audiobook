"""End-to-end integration test for the full 6-stage pipeline.

This test runs the pipeline extract → analyze → annotate → edit → synthesize →
quality_check using a short piece of text and verifies that each stage produces
expected outputs and that the final quality judgment is obtained.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "src")

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
    BookAnalysisOutput,
    BookMeta,
    CharacterVoiceBinding,
    EmotionSnapshot,
    ExtractionResult,
    ParagraphAnnotation,
    QualityJudgment,
    TtsEditOutput,
    TtsRoutingDecision,
    TtsRoutingInput,
)


def test_e2e_short_story_mock():
    """Run the full pipeline in mock mode with a short story."""
    # 1. Extract text (simulate from a file)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("第一章  这是一个非常短的测试故事。"
                "主人公旁白介绍了背景。"
                "主角说了话。"
                "故事结束。")
        temp_path = f.name

    extraction: ExtractionResult = extract_text(
        file_path=temp_path,
        mime_type="text/plain",
        detect_language=True,
        mock_mode=True,
    )
    assert isinstance(extraction, ExtractionResult)
    assert extraction.raw_text
    assert extraction.language == "zh"

    # 2. Analyze structure
    analysis: BookAnalysisOutput = analyze_structure(
        extraction.raw_text, title_hint="测试故事", mock_mode=True
    )
    assert isinstance(analysis, BookAnalysisOutput)
    assert analysis.book_meta.title
    assert len(analysis.character_voice_map) >= 1
    assert len(analysis.emotion_snapshots) >= 1

    # 3. Annotate first paragraph (use the first sentence)
    first_para = "第一章  这是一个非常短的测试故事。"
    # Build minimal book_meta, character_voice_map, emotion_snapshot from analysis
    book_meta = analysis.book_meta
    character_voice_map = analysis.character_voice_map
    emotion_snapshot = analysis.emotion_snapshots[0] if analysis.emotion_snapshots else EmotionSnapshot(
        chapter=1, dominant_emotion="neutral", intensity=0.5
    )

    annotation: ParagraphAnnotation = annotate_paragraph(
        paragraph_text=first_para,
        paragraph_index=0,
        chapter_index=1,
        book_meta=book_meta,
        character_voice_map=character_voice_map,
        emotion_snapshot=emotion_snapshot,
        story_line_summary=analysis.story_line_summary,
        global_style_notes=analysis.global_style_notes,
        mock_mode=True,
    )
    assert isinstance(annotation, ParagraphAnnotation)
    assert annotation.speaker_canonical_name in [v.canonical_name for v in character_voice_map]
    assert annotation.confidence > 0

    # 4. Edit for TTS
    edited: TtsEditOutput = edit_for_tts(
        paragraph_text=first_para,
        paragraph_annotation=annotation,
        difficulty=book_meta.difficulty,
        mock_mode=True,
    )
    assert isinstance(edited, TtsEditOutput)
    assert edited.edited_text
    assert "mock_mode_no_changes" in edited.changes_made

    # 5. Synthesize
    routing_input = TtsRoutingInput(
        paragraph_annotation=annotation,
        text=edited.edited_text,
        character_voice_map=character_voice_map,
        book_id="test_book",
        chapter_index=1,
        paragraph_index=0,
        cumulative_cost_usd=0.0,
        cost_limit_per_book=20.0,
        cost_limit_per_chapter=5.0,
        prefer_local=True,
    )

    segments = synthesize_paragraphs([routing_input], mock_mode=True)
    assert len(segments) == 1
    assert segments[0].engine in ("kokoro", "edge")  # mock may choose either

    # 6. Quality check
    # Build a dummy routing decision (in mock mode, we can use the one from synthesize?)
    # For simplicity, create a routing decision matching the segment
    routing_decision = TtsRoutingDecision(
        segment_id="test_ch1_p0",
        engine_choice=segments[0].engine,
        voice_id=character_voice_map[0].suggested_voice_id if character_voice_map else "v1",
        prosody_overrides={},
        fallback_engine="edge",
        reasoning="mock",
        estimated_cost_usd=0.0,
        estimated_duration_ms=3000,
    )

    # We need an audio file path; in mock mode, quality_check will still run but
    # the audio analysis will be mocked. We'll fake a path.
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as audio_file:
        audio_file.write(b"fake audio data")
        audio_path = audio_file.name

    judgments: list[QualityJudgment] = quality_check(
        inputs=[(audio_path, annotation, routing_decision, edited.edited_text)],
        mock_mode=True,
    )
    assert len(judgments) == 1
    judgment: QualityJudgment = judgments[0]
    assert isinstance(judgment, QualityJudgment)
    assert judgment.overall_score > 0
    # In mock mode, the judgment should have been mocked in llm/client.py
    # The mock quality judgment has overall_score=0.94 (see llm/client.py)
    assert judgment.overall_score == 0.9

    # Cleanup
    Path(temp_path).unlink(missing_ok=True)
    Path(audio_path).unlink(missing_ok=True)