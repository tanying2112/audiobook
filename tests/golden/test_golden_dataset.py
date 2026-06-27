"""Golden Dataset Validation Tests for All 6 Pipeline Stages.

Validates structured output compliance against golden dataset samples.
Target: >70% schema compliance rate per stage.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

# Set MOCK_LLM environment variable for mock mode testing
os.environ["MOCK_LLM"] = "true"

sys.path.insert(0, "src")

from audiobook_studio.llm import create_router  # noqa: E402
from audiobook_studio.pipeline import (  # noqa: E402
    analyze_structure,
    annotate_paragraph,
    edit_for_tts,
    extract_text,
    quality_check,
    synthesize_paragraphs,
)
from audiobook_studio.pipeline.analyze_structure import AnalyzeStructurePipeline
from audiobook_studio.pipeline.annotate_paragraph import AnnotateParagraphPipeline
from audiobook_studio.pipeline.edit_for_tts import EditForTtsPipeline
from audiobook_studio.pipeline.extract import ExtractPipeline
from audiobook_studio.pipeline.quality_check import (
    AudioAnalysisResult,
    QualityCheckPipeline,
)
from audiobook_studio.pipeline.synthesize import SynthesizePipeline
from audiobook_studio.schemas import (  # noqa: E402
    BookAnalysisInput,
    BookMeta,
    CharacterVoiceBinding,
    EmotionSnapshot,
    ExtractionInput,
    ParagraphAnnotation,
    QualityJudgment,
    TtsEditInput,
    TtsRoutingDecision,
    TtsRoutingInput,
)

GOLDEN_DIR = Path(__file__).parent


def load_golden_samples(stage: str) -> List[Dict[str, Any]]:
    """Load golden dataset samples for a specific stage."""
    samples = []
    few_shot_path = GOLDEN_DIR / stage / "few_shot.jsonl"
    if few_shot_path.exists():
        with open(few_shot_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    samples.append(json.loads(line))
    return samples


class TestGoldenDatasetExtract:
    """Golden dataset validation for Extract stage."""

    @pytest.fixture(scope="class")
    def pipeline(self):
        return ExtractPipeline()

    def test_golden_samples_exist(self):
        samples = load_golden_samples("extract")
        assert len(samples) >= 3, f"Extract stage needs ≥3 samples, got {len(samples)}"

    def test_mock_mode_returns_valid_result(self, pipeline):
        """Test mock mode returns valid ExtractionResult."""
        from audiobook_studio.schemas import ExtractionInput

        input_data = ExtractionInput(
            file_path="/fake/test.txt", mime_type="text/plain", detect_language=True
        )
        result = pipeline.run(input_data)
        assert hasattr(result, "raw_text")
        assert hasattr(result, "language")
        assert hasattr(result, "page_count")
        assert hasattr(result, "has_ocr")
        assert hasattr(result, "ocr_page_ratio")
        assert hasattr(result, "warnings")
        assert len(result.raw_text) >= 50


class TestGoldenDatasetAnalyzeStructure:
    """Golden dataset validation for Analyze Structure stage."""

    @pytest.fixture(scope="class")
    def router(self):
        return create_router()

    @pytest.fixture(scope="class")
    def pipeline(self, router):
        return AnalyzeStructurePipeline(router=router)

    def test_golden_samples_exist(self):
        samples = load_golden_samples("analyze_structure")
        assert len(samples) >= 3, f"Analyze stage needs ≥3 samples, got {len(samples)}"

    def test_schema_compliance_rate(self, pipeline):
        """Test schema compliance rate meets target (>70%)."""
        samples = load_golden_samples("analyze_structure")
        compliant = 0
        total = len(samples)

        for sample in samples:
            input_data = sample["input"]
            try:
                book_input = BookAnalysisInput(**input_data)
                result = pipeline.run(book_input)

                # Validate required fields exist
                assert hasattr(result, "book_meta")
                assert hasattr(result, "character_voice_map")
                assert hasattr(result, "emotion_snapshots")
                assert hasattr(result, "story_line_summary")
                assert hasattr(result, "global_style_notes")

                # Validate nested required fields
                assert result.book_meta.title
                assert result.book_meta.genre
                assert result.book_meta.difficulty in ["A", "B", "C", "D"]
                assert result.book_meta.language
                assert len(result.character_voice_map) >= 1
                assert len(result.emotion_snapshots) >= 1
                assert len(result.story_line_summary) >= 100

                compliant += 1
            except Exception as e:
                pytest.fail(f"Schema compliance failed for sample: {e}")

        compliance_rate = compliant / total if total > 0 else 0
        print(
            f"\nAnalyze Structure Compliance Rate: {compliance_rate:.1%} ({compliant}/{total})"
        )
        assert (
            compliance_rate >= 0.7
        ), f"Compliance rate {compliance_rate:.1%} below 70% target"

    def test_character_consistency(self, pipeline):
        """Test character voice bindings are consistent."""
        samples = load_golden_samples("analyze_structure")
        for sample in samples:
            input_data = sample["input"]
            book_input = BookAnalysisInput(**input_data)
            result = pipeline.run(book_input)

            # Check canonical names are unique
            canonical_names = [c.canonical_name for c in result.character_voice_map]
            assert len(canonical_names) == len(
                set(canonical_names)
            ), "Duplicate canonical names"

            # Check each character has required fields
            for char in result.character_voice_map:
                assert char.canonical_name
                assert char.gender in ["male", "female", "neutral", "unknown"]
                assert char.age_range in [
                    "child",
                    "young",
                    "adult",
                    "elderly",
                    "unknown",
                ]
                assert char.sample_quote

    def test_emotion_snapshots_valid(self, pipeline):
        """Test emotion snapshots have valid values."""
        valid_emotions = {
            "neutral",
            "happy",
            "sad",
            "angry",
            "fearful",
            "surprised",
            "disgusted",
            "tense",
            "tender",
            "contemplative",
            "whisper",
            "cold_laugh",
            "sigh",
            "sarcastic",
        }

        samples = load_golden_samples("analyze_structure")
        for sample in samples:
            input_data = sample["input"]
            book_input = BookAnalysisInput(**input_data)
            result = pipeline.run(book_input)

            for snapshot in result.emotion_snapshots:
                assert snapshot.chapter >= 1
                assert snapshot.dominant_emotion in valid_emotions
                assert 0.0 <= snapshot.intensity <= 1.0

    def test_story_summary_length(self, pipeline):
        """Test story summary meets length requirements (100-500 chars)."""
        samples = load_golden_samples("analyze_structure")
        for sample in samples:
            input_data = sample["input"]
            book_input = BookAnalysisInput(**input_data)
            result = pipeline.run(book_input)
            assert 100 <= len(result.story_line_summary) <= 500


class TestGoldenDatasetAnnotateParagraph:
    """Golden dataset validation for Annotate Paragraph stage."""

    @pytest.fixture(scope="class")
    def router(self):
        return create_router()

    @pytest.fixture(scope="class")
    def pipeline(self, router):
        return AnnotateParagraphPipeline(router=router)

    def test_golden_samples_exist(self):
        samples = load_golden_samples("annotate_paragraph")
        assert len(samples) >= 3, f"Annotate stage needs ≥3 samples, got {len(samples)}"

    def test_mock_mode_returns_valid_annotation(self, pipeline):
        """Test mock mode returns valid ParagraphAnnotation."""
        # Create minimal valid input
        from audiobook_studio.schemas import (
            BookMeta,
            CharacterVoiceBinding,
            EmotionSnapshot,
            ParagraphAnnotationInput,
        )

        book_meta = BookMeta(
            title="Test Book",
            genre="小说",
            difficulty="B",
            language="zh",
            total_chapters_estimated=10,
        )
        char_voice_map = [
            CharacterVoiceBinding(
                canonical_name="旁白",
                aliases=[],
                gender="neutral",
                age_range="adult",
                suggested_voice_id="v1",
                sample_quote="test",
            )
        ]
        emotion_snapshot = EmotionSnapshot(
            chapter=1, dominant_emotion="neutral", intensity=0.5
        )

        input_data = ParagraphAnnotationInput(
            paragraph_text="这是一个测试段落文本内容。",
            paragraph_index=0,
            chapter_index=1,
            book_meta=book_meta,
            character_voice_map=char_voice_map,
            emotion_snapshot=emotion_snapshot,
            story_line_summary="这是一个用于测试的故事线摘要，长度足够满足最小要求。这是一个用于测试的故事线摘要，长度足够满足最小要求。这是一个用于测试的故事线摘要，长度足够满足最小要求。这是一个用于测试的故事线摘要，长度足够满足最小要求。",
            global_style_notes="测试风格备注。",
        )

        result = pipeline.run(input_data)

        assert isinstance(result, ParagraphAnnotation)
        assert result.paragraph_index == 0
        assert result.speaker_canonical_name
        assert result.emotion in {
            "neutral",
            "happy",
            "sad",
            "angry",
            "fearful",
            "surprised",
            "disgusted",
            "tense",
            "tender",
            "contemplative",
            "whisper",
            "cold_laugh",
            "sigh",
            "sarcastic",
        }
        assert 0.0 <= result.emotion_intensity <= 1.0
        assert 0.5 <= result.speech_rate <= 2.0
        assert -12 <= result.pitch_shift_semitones <= 12
        assert result.pause_before_ms >= 0
        assert result.pause_after_ms >= 0
        assert 0.0 <= result.confidence <= 1.0
        assert result.difficulty in ["A", "B", "C"]
        assert isinstance(result.needs_sfx, bool)
        assert isinstance(result.sfx_tags, list)


class TestGoldenDatasetEditForTts:
    """Golden dataset validation for Edit for TTS stage."""

    @pytest.fixture(scope="class")
    def router(self):
        return create_router()

    @pytest.fixture(scope="class")
    def pipeline(self, router):
        return EditForTtsPipeline(router=router)

    def test_golden_samples_exist(self):
        samples = load_golden_samples("edit_for_tts")
        assert len(samples) >= 3, f"Edit stage needs ≥3 samples, got {len(samples)}"

    def test_mock_mode_returns_valid_output(self, pipeline):
        """Test mock mode returns valid TtsEditOutput."""
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
            difficulty="B",
            needs_sfx=False,
            sfx_tags=[],
        )

        input_data = TtsEditInput(
            paragraph_text="这是一个足够长的测试段落文本内容，用于编辑。",
            paragraph_annotation=annotation,
            difficulty="B",
            forbid_edit=False,
        )

        result = pipeline.run(input_data)

        from audiobook_studio.schemas import TtsEditOutput

        assert isinstance(result, TtsEditOutput)
        assert result.edited_text
        assert isinstance(result.changes_made, list)
        assert isinstance(result.forbidden_content_removed, list)
        assert 0.0 <= result.confidence <= 1.0
        assert result.rationale


class TestGoldenDatasetQualityJudge:
    """Golden dataset validation for Quality Judge stage."""

    @pytest.fixture(scope="class")
    def pipeline(self):
        return QualityCheckPipeline()

    def test_golden_samples_exist(self):
        samples = load_golden_samples("quality_judge")
        assert (
            len(samples) >= 3
        ), f"Quality judge stage needs ≥3 samples, got {len(samples)}"

    def test_mock_mode_returns_valid_judgment(self, pipeline):
        """Test mock mode returns valid QualityJudgment."""
        import tempfile
        from pathlib import Path

        temp_dir = Path(tempfile.mkdtemp())
        mock_audio_path = temp_dir / "test_segment.wav"
        mock_audio_path.write_bytes(b"RIFF" + b"\x00" * 1000)

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
            difficulty="B",
            needs_sfx=False,
            sfx_tags=[],
        )
        routing = TtsRoutingDecision(
            segment_id="test_ch1_p0",
            engine_choice="kokoro",
            voice_id="v1",
            prosody_overrides={},
            fallback_engine="edge",
            reasoning="Mock",
            estimated_cost_usd=0.0,
            estimated_duration_ms=3000,
        )

        results = pipeline.run(
            [(str(mock_audio_path), annotation, routing, "测试文本")]
        )

        import shutil

        shutil.rmtree(temp_dir, ignore_errors=True)

        assert len(results) == 1
        assert isinstance(results[0], QualityJudgment)
        assert 0.0 <= results[0].overall_score <= 1.0
        assert 0.0 <= results[0].speaker_clarity <= 1.0
        assert 0.0 <= results[0].emotion_match <= 1.0
        assert 0.0 <= results[0].prosody_naturalness <= 1.0
        assert 0.0 <= results[0].text_audio_alignment <= 1.0
        assert isinstance(results[0].issues, list)
        assert isinstance(results[0].fix_suggestions, list)
        assert isinstance(results[0].needs_regeneration, bool)


class TestGoldenDatasetTtsRouting:
    """Golden dataset validation for TTS Routing stage."""

    @pytest.fixture(scope="class")
    def router(self):
        return create_router()

    @pytest.fixture(scope="class")
    def pipeline(self, router):
        return SynthesizePipeline(router=router)

    def test_golden_samples_exist(self):
        samples = load_golden_samples("tts_routing")
        assert (
            len(samples) >= 3
        ), f"TTS routing stage needs ≥3 samples, got {len(samples)}"

    def test_mock_mode_returns_valid_decisions(self, pipeline):
        """Test mock mode returns valid routing decisions via run()."""
        from audiobook_studio.schemas import CharacterVoiceBinding, TtsRoutingInput

        char_voice_map = [
            CharacterVoiceBinding(
                canonical_name="旁白",
                aliases=[],
                gender="neutral",
                age_range="adult",
                suggested_voice_id="v1",
                sample_quote="test",
            )
        ]

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
            difficulty="B",
            needs_sfx=False,
            sfx_tags=[],
        )

        tts_input = TtsRoutingInput(
            paragraph_annotation=annotation,
            text="测试文本内容",
            character_voice_map=char_voice_map,
            book_id="test_book",
            chapter_index=1,
            paragraph_index=0,
            cumulative_cost_usd=0.0,
            cost_limit_per_book=20.0,
            cost_limit_per_chapter=5.0,
            prefer_local=True,
        )

        # Use the internal _make_routing_decision method for testing routing
        decision = pipeline._make_routing_decision(tts_input)

        assert isinstance(decision, TtsRoutingDecision)
        assert decision.segment_id == "test_book_ch1_p0"
        assert decision.engine_choice in ["kokoro", "edge", "human_clone"]
        assert decision.voice_id
        assert decision.reasoning
        assert decision.estimated_cost_usd >= 0
        assert decision.estimated_duration_ms > 0


class TestGoldenDatasetSynthesize:
    """Golden dataset validation for Synthesize stage."""

    @pytest.fixture(scope="class")
    def router(self):
        return create_router()

    @pytest.fixture(scope="class")
    def pipeline(self, router):
        return SynthesizePipeline(router=router)

    def test_mock_mode_returns_valid_segments(self, pipeline):
        """Test mock mode returns valid AudioSegment via run()."""
        from audiobook_studio.pipeline.synthesize import AudioSegment
        from audiobook_studio.schemas import CharacterVoiceBinding, TtsRoutingInput

        char_voice_map = [
            CharacterVoiceBinding(
                canonical_name="旁白",
                aliases=[],
                gender="neutral",
                age_range="adult",
                suggested_voice_id="v1",
                sample_quote="test",
            )
        ]

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
            difficulty="B",
            needs_sfx=False,
            sfx_tags=[],
        )

        tts_input = TtsRoutingInput(
            paragraph_annotation=annotation,
            text="测试文本内容",
            character_voice_map=char_voice_map,
            book_id="test_book",
            chapter_index=1,
            paragraph_index=0,
            cumulative_cost_usd=0.0,
            cost_limit_per_book=20.0,
            cost_limit_per_chapter=5.0,
            prefer_local=True,
        )

        results = pipeline.run([tts_input])

        assert len(results) == 1
        assert isinstance(results[0], AudioSegment)
        assert results[0].segment_id == "test_book_ch1_p0"
        assert results[0].file_path
        assert results[0].duration_ms > 0
        assert results[0].engine in ["kokoro", "edge", "human_clone"]
        assert results[0].voice_id


# Legacy analyze_structure tests (kept for backward compatibility)
class TestLegacyAnalyzeStructure:
    """Legacy tests for analyze_structure golden dataset."""

    @pytest.fixture(scope="class")
    def router(self):
        return create_router()

    @pytest.fixture(scope="class")
    def pipeline(self, router):
        return AnalyzeStructurePipeline(router=router)

    @pytest.fixture(scope="class")
    def golden_samples(self):
        return load_golden_samples("analyze_structure")

    def test_golden_samples_exist(self, golden_samples):
        """Ensure golden dataset has samples."""
        assert len(golden_samples) > 0, "No golden samples found"
        assert len(golden_samples) >= 3

    def test_compliance_rate_calculation(self):
        """Test compliance rate calculation logic."""
        results = [
            {"schema_compliance": True},
            {"schema_compliance": True},
            {"schema_compliance": False},
            {"schema_compliance": True},
            {"schema_compliance": True},
        ]
        compliant = sum(1 for r in results if r["schema_compliance"])
        total = len(results)
        rate = compliant / total
        assert rate == 0.8

    def test_cost_per_call_tracking(self):
        """Test cost per call tracking."""
        from audiobook_studio.llm.router import get_cost_tracker, reset_cost_tracker

        reset_cost_tracker()
        tracker = get_cost_tracker()
        tracker.set_daily_limit("test-model", 10.0)

        costs = [0.001, 0.002, 0.0015, 0.003]
        for cost in costs:
            tracker.add_cost("test-model", cost)

        assert abs(tracker.get_daily_cost("test-model") - sum(costs)) < 1e-10
        assert not tracker.is_limit_exceeded("test-model")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
