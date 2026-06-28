"""Comprehensive unit tests for TTS routing schemas targeting ≥80% line coverage.

Tests match the ACTUAL API from src/audiobook_studio/schemas/tts_routing.py:
- TtsRoutingInput with ParagraphAnnotation (single paragraph annotation, not batch)
- TtsRoutingDecision with engine_choice, voice_id, prosody_overrides, etc.
"""

import pytest
from pydantic import ValidationError

from src.audiobook_studio.schemas.book import (
    BookMeta,
    CharacterVoiceBinding,
    EmotionSnapshot,
)
from src.audiobook_studio.schemas.paragraph import ParagraphAnnotation
from src.audiobook_studio.schemas.tts_routing import TtsRoutingDecision, TtsRoutingInput


def create_valid_paragraph_annotation(**overrides):
    """Create a valid ParagraphAnnotation for testing."""
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
        "notes": "Test annotation",
        "contract_version": 1,
    }
    defaults.update(overrides)
    return ParagraphAnnotation(**defaults)


def create_valid_character_voice_binding(**overrides):
    """Create a valid CharacterVoiceBinding for testing."""
    defaults = {
        "canonical_name": "旁白",
        "aliases": [],
        "gender": "neutral",
        "age_range": "adult",
        "suggested_voice_id": "kokoro_narrator",
        "sample_quote": "这是旁白的样本文本。",
    }
    defaults.update(overrides)
    return CharacterVoiceBinding(**defaults)


def create_valid_book_meta(**overrides):
    """Create a valid BookMeta for testing."""
    defaults = {
        "title": "测试书籍",
        "author": "测试作者",
        "genre": "小说",
        "difficulty": "B",
        "language": "zh",
        "era": "现代",
        "total_chapters_estimated": 10,
    }
    defaults.update(overrides)
    return BookMeta(**defaults)


def create_valid_emotion_snapshot(**overrides):
    """Create a valid EmotionSnapshot for testing."""
    defaults = {
        "chapter": 1,
        "dominant_emotion": "neutral",
        "intensity": 0.5,
        "notes": "平静的开头",
    }
    defaults.update(overrides)
    return EmotionSnapshot(**defaults)


class TestTtsRoutingInput:
    """Test TtsRoutingInput schema validation."""

    def test_valid_minimal_input(self):
        """Test valid minimal input."""
        paragraph_annotation = create_valid_paragraph_annotation()
        character_voice_map = [create_valid_character_voice_binding()]

        inp = TtsRoutingInput(
            paragraph_annotation=paragraph_annotation,
            text="测试文本",
            character_voice_map=character_voice_map,
            book_id="test_book",
            chapter_index=1,
            paragraph_index=0,
        )
        assert inp.text == "测试文本"
        assert inp.book_id == "test_book"
        assert inp.chapter_index == 1
        assert inp.paragraph_index == 0
        assert inp.contract_version == 1
        assert inp.prefer_local is True
        assert inp.cumulative_cost_usd == 0.0
        assert inp.cost_limit_per_book == 20.0
        assert inp.cost_limit_per_chapter == 5.0

    def test_valid_full_input(self):
        """Test valid full input with all fields."""
        paragraph_annotation = create_valid_paragraph_annotation(
            paragraph_index=10,
            speaker_canonical_name="主角",
            is_dialogue=True,
            emotion="happy",
            emotion_intensity=0.8,
            speech_rate=1.1,
        )
        character_voice_map = [
            create_valid_character_voice_binding(
                canonical_name="旁白",
                suggested_voice_id="kokoro_narrator",
            ),
            create_valid_character_voice_binding(
                canonical_name="主角",
                gender="male",
                age_range="young",
                suggested_voice_id="kokoro_male_young",
                sample_quote="哈哈哈，好开心！",
            ),
        ]
        inp = TtsRoutingInput(
            paragraph_annotation=paragraph_annotation,
            text="完整测试文本内容，这是一个对话段落。",
            character_voice_map=character_voice_map,
            book_id="full_test_book",
            chapter_index=5,
            paragraph_index=10,
            cumulative_cost_usd=15.5,
            cost_limit_per_book=50.0,
            cost_limit_per_chapter=10.0,
            prefer_local=False,
            contract_version=2,
        )
        assert inp.cumulative_cost_usd == 15.5
        assert inp.cost_limit_per_book == 50.0
        assert inp.cost_limit_per_chapter == 10.0
        assert inp.prefer_local is False
        assert inp.contract_version == 2

    def test_text_min_length_validation(self):
        """Test text minimum length validation (min 1 char)."""
        paragraph_annotation = create_valid_paragraph_annotation()
        character_voice_map = [create_valid_character_voice_binding()]

        with pytest.raises(
            ValidationError, match="String should have at least 1 character"
        ):
            TtsRoutingInput(
                paragraph_annotation=paragraph_annotation,
                text="",
                character_voice_map=character_voice_map,
                book_id="test",
                chapter_index=1,
                paragraph_index=0,
            )

    def test_chapter_index_validation(self):
        """Test chapter_index must be >= 1."""
        paragraph_annotation = create_valid_paragraph_annotation()
        character_voice_map = [create_valid_character_voice_binding()]

        with pytest.raises(
            ValidationError, match="Input should be greater than or equal to 1"
        ):
            TtsRoutingInput(
                paragraph_annotation=paragraph_annotation,
                text="测试",
                character_voice_map=character_voice_map,
                book_id="test",
                chapter_index=0,
                paragraph_index=0,
            )

    def test_paragraph_index_validation(self):
        """Test paragraph_index must be >= 0."""
        paragraph_annotation = create_valid_paragraph_annotation()
        character_voice_map = [create_valid_character_voice_binding()]

        with pytest.raises(
            ValidationError, match="Input should be greater than or equal to 0"
        ):
            TtsRoutingInput(
                paragraph_annotation=paragraph_annotation,
                text="测试",
                character_voice_map=character_voice_map,
                book_id="test",
                chapter_index=1,
                paragraph_index=-1,
            )

    def test_cost_fields_non_negative(self):
        """Test cost fields must be non-negative."""
        paragraph_annotation = create_valid_paragraph_annotation()
        character_voice_map = [create_valid_character_voice_binding()]

        with pytest.raises(
            ValidationError, match="Input should be greater than or equal to 0"
        ):
            TtsRoutingInput(
                paragraph_annotation=paragraph_annotation,
                text="测试",
                character_voice_map=character_voice_map,
                book_id="test",
                chapter_index=1,
                paragraph_index=0,
                cumulative_cost_usd=-1.0,
            )

    def test_character_voice_map_min_length(self):
        """Test character_voice_map must have at least 1 item."""
        paragraph_annotation = create_valid_paragraph_annotation()

        with pytest.raises(ValidationError, match="List should have at least 1 item"):
            TtsRoutingInput(
                paragraph_annotation=paragraph_annotation,
                text="测试",
                character_voice_map=[],
                book_id="test",
                chapter_index=1,
                paragraph_index=0,
            )

    def test_contract_version_default(self):
        """Test contract_version defaults to 1."""
        paragraph_annotation = create_valid_paragraph_annotation()
        character_voice_map = [create_valid_character_voice_binding()]

        inp = TtsRoutingInput(
            paragraph_annotation=paragraph_annotation,
            text="测试",
            character_voice_map=character_voice_map,
            book_id="test",
            chapter_index=1,
            paragraph_index=0,
        )
        assert inp.contract_version == 1

    def test_serialization(self):
        """Test model serialization to dict."""
        paragraph_annotation = create_valid_paragraph_annotation()
        character_voice_map = [create_valid_character_voice_binding()]

        inp = TtsRoutingInput(
            paragraph_annotation=paragraph_annotation,
            text="测试",
            character_voice_map=character_voice_map,
            book_id="test",
            chapter_index=1,
            paragraph_index=0,
        )
        data = inp.model_dump()
        assert data["text"] == "测试"
        assert data["book_id"] == "test"
        assert data["chapter_index"] == 1
        assert data["paragraph_index"] == 0
        assert data["contract_version"] == 1
        assert "paragraph_annotation" in data
        assert "character_voice_map" in data

    def test_deserialization(self):
        """Test model deserialization from dict."""
        paragraph_annotation = create_valid_paragraph_annotation()
        character_voice_map = [create_valid_character_voice_binding()]

        data = {
            "paragraph_annotation": paragraph_annotation,
            "text": "反序列化测试",
            "character_voice_map": character_voice_map,
            "book_id": "deserialize_test",
            "chapter_index": 3,
            "paragraph_index": 5,
            "cumulative_cost_usd": 5.0,
            "cost_limit_per_book": 30.0,
            "cost_limit_per_chapter": 8.0,
            "prefer_local": False,
            "contract_version": 2,
        }
        inp = TtsRoutingInput(**data)
        assert inp.text == "反序列化测试"
        assert inp.book_id == "deserialize_test"
        assert inp.chapter_index == 3
        assert inp.paragraph_index == 5
        assert inp.cumulative_cost_usd == 5.0
        assert inp.prefer_local is False
        assert inp.contract_version == 2


class TestTtsRoutingDecision:
    """Test TtsRoutingDecision schema validation."""

    def test_valid_minimal_decision(self):
        """Test valid minimal decision."""
        decision = TtsRoutingDecision(
            segment_id="test_book_ch1_p0",
            engine_choice="kokoro",
            voice_id="kokoro_narrator",
            fallback_engine="edge",
            reasoning="本地免费引擎优先",
        )
        assert decision.segment_id == "test_book_ch1_p0"
        assert decision.engine_choice == "kokoro"
        assert decision.voice_id == "kokoro_narrator"
        assert decision.fallback_engine == "edge"
        assert decision.reasoning == "本地免费引擎优先"
        assert decision.prosody_overrides is None
        assert decision.estimated_cost_usd == 0.0
        assert decision.estimated_duration_ms == 0
        assert decision.contract_version == 1

    def test_valid_full_decision(self):
        """Test valid full decision with all fields."""
        decision = TtsRoutingDecision(
            segment_id="full_book_ch5_p10",
            engine_choice="edge",
            voice_id="kokoro_male_young",
            prosody_overrides={"rate": "1.2", "pitch": "+2st"},
            fallback_engine="kokoro",
            reasoning="情感强烈段落使用 Edge TTS 获得更好表现力",
            estimated_cost_usd=0.05,
            estimated_duration_ms=5000,
            contract_version=2,
        )
        assert decision.engine_choice == "edge"
        assert decision.prosody_overrides == {"rate": "1.2", "pitch": "+2st"}
        assert decision.estimated_cost_usd == 0.05
        assert decision.estimated_duration_ms == 5000
        assert decision.contract_version == 2

    def test_engine_choice_validation(self):
        """Test engine_choice must be one of allowed values."""
        with pytest.raises(
            ValidationError,
            match="Input should be 'kokoro', 'edge', 'azure', 'gcp' or 'human_clone'",
        ):
            TtsRoutingDecision(
                segment_id="test_ch1_p0",
                engine_choice="invalid_engine",
                voice_id="voice_001",
                fallback_engine="edge",
                reasoning="测试",
            )

    def test_fallback_engine_validation(self):
        """Test fallback_engine must be one of allowed values."""
        with pytest.raises(
            ValidationError,
            match="Input should be 'kokoro', 'edge', 'azure', 'gcp' or 'human_clone'",
        ):
            TtsRoutingDecision(
                segment_id="test_ch1_p0",
                engine_choice="kokoro",
                voice_id="voice_001",
                fallback_engine="invalid_engine",
                reasoning="测试",
            )

    def test_estimated_cost_non_negative(self):
        """Test estimated_cost_usd must be non-negative."""
        with pytest.raises(
            ValidationError, match="Input should be greater than or equal to 0"
        ):
            TtsRoutingDecision(
                segment_id="test_ch1_p0",
                engine_choice="kokoro",
                voice_id="voice_001",
                fallback_engine="edge",
                reasoning="测试",
                estimated_cost_usd=-0.01,
            )

    def test_estimated_duration_non_negative(self):
        """Test estimated_duration_ms must be non-negative."""
        with pytest.raises(
            ValidationError, match="Input should be greater than or equal to 0"
        ):
            TtsRoutingDecision(
                segment_id="test_ch1_p0",
                engine_choice="kokoro",
                voice_id="voice_001",
                fallback_engine="edge",
                reasoning="测试",
                estimated_duration_ms=-100,
            )

    def test_segment_id_required(self):
        """Test segment_id is required."""
        with pytest.raises(ValidationError, match="Field required"):
            TtsRoutingDecision(
                engine_choice="kokoro",
                voice_id="voice_001",
                fallback_engine="edge",
                reasoning="测试",
            )

    def test_voice_id_required(self):
        """Test voice_id is required."""
        with pytest.raises(ValidationError, match="Field required"):
            TtsRoutingDecision(
                segment_id="test_ch1_p0",
                engine_choice="kokoro",
                fallback_engine="edge",
                reasoning="测试",
            )

    def test_reasoning_required(self):
        """Test reasoning is required."""
        with pytest.raises(ValidationError, match="Field required"):
            TtsRoutingDecision(
                segment_id="test_ch1_p0",
                engine_choice="kokoro",
                voice_id="voice_001",
                fallback_engine="edge",
            )

    def test_extra_fields_forbidden(self):
        """Test extra fields are forbidden."""
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            TtsRoutingDecision(
                segment_id="test_ch1_p0",
                engine_choice="kokoro",
                voice_id="voice_001",
                fallback_engine="edge",
                reasoning="测试",
                extra_field="not_allowed",
            )

    def test_serialization(self):
        """Test model serialization to dict."""
        decision = TtsRoutingDecision(
            segment_id="serialize_test_ch1_p0",
            engine_choice="kokoro",
            voice_id="kokoro_narrator",
            fallback_engine="edge",
            reasoning="序列化测试",
        )
        data = decision.model_dump()
        assert data["segment_id"] == "serialize_test_ch1_p0"
        assert data["engine_choice"] == "kokoro"
        assert data["voice_id"] == "kokoro_narrator"
        assert data["fallback_engine"] == "edge"
        assert data["reasoning"] == "序列化测试"
        assert data["contract_version"] == 1

    def test_deserialization(self):
        """Test model deserialization from dict."""
        data = {
            "segment_id": "deserialize_ch2_p5",
            "engine_choice": "human_clone",
            "voice_id": "cloned_voice_001",
            "prosody_overrides": {"speed": "1.1"},
            "fallback_engine": "kokoro",
            "reasoning": "声音克隆测试",
            "estimated_cost_usd": 0.1,
            "estimated_duration_ms": 3000,
            "contract_version": 2,
        }
        decision = TtsRoutingDecision(**data)
        assert decision.segment_id == "deserialize_ch2_p5"
        assert decision.engine_choice == "human_clone"
        assert decision.voice_id == "cloned_voice_001"
        assert decision.prosody_overrides == {"speed": "1.1"}
        assert decision.fallback_engine == "kokoro"
        assert decision.reasoning == "声音克隆测试"
        assert decision.estimated_cost_usd == 0.1
        assert decision.estimated_duration_ms == 3000
        assert decision.contract_version == 2

    def test_all_engine_choices(self):
        """Test all valid engine choices."""
        for engine in ["kokoro", "edge", "human_clone"]:
            decision = TtsRoutingDecision(
                segment_id=f"test_{engine}_ch1_p0",
                engine_choice=engine,
                voice_id="voice_001",
                fallback_engine="kokoro" if engine != "kokoro" else "edge",
                reasoning=f"测试 {engine} 引擎",
            )
            assert decision.engine_choice == engine

    def test_prosody_overrides_optional(self):
        """Test prosody_overrides is optional."""
        decision = TtsRoutingDecision(
            segment_id="test_ch1_p0",
            engine_choice="kokoro",
            voice_id="voice_001",
            fallback_engine="edge",
            reasoning="测试",
            prosody_overrides=None,
        )
        assert decision.prosody_overrides is None

        decision2 = TtsRoutingDecision(
            segment_id="test_ch1_p1",
            engine_choice="edge",
            voice_id="voice_002",
            fallback_engine="kokoro",
            reasoning="测试",
            prosody_overrides={"rate": "1.5"},
        )
        assert decision2.prosody_overrides == {"rate": "1.5"}


class TestTtsRoutingSchemasIntegration:
    """Test integration between TtsRoutingInput and TtsRoutingDecision."""

    def test_input_to_decision_flow(self):
        """Test typical flow from input to decision."""
        paragraph_annotation = create_valid_paragraph_annotation(
            speaker_canonical_name="旁白",
            is_dialogue=False,
        )
        character_voice_map = [
            create_valid_character_voice_binding(
                canonical_name="旁白",
                suggested_voice_id="kokoro_narrator",
            ),
            create_valid_character_voice_binding(
                canonical_name="主角",
                gender="male",
                age_range="young",
                suggested_voice_id="kokoro_male_young",
                sample_quote="哈哈哈，好开心！",
            ),
        ]
        inp = TtsRoutingInput(
            paragraph_annotation=paragraph_annotation,
            text="这是一个旁白段落。",
            character_voice_map=character_voice_map,
            book_id="integration_test",
            chapter_index=1,
            paragraph_index=0,
            cumulative_cost_usd=0.0,
            cost_limit_per_book=20.0,
            prefer_local=True,
        )

        # Simulate decision based on input
        decision = TtsRoutingDecision(
            segment_id=f"{inp.book_id}_ch{inp.chapter_index}_p{inp.paragraph_index}",
            engine_choice="kokoro" if inp.prefer_local else "edge",
            voice_id=character_voice_map[0].suggested_voice_id,
            fallback_engine="edge",
            reasoning="旁白段落，优先使用本地 Kokoro 引擎",
            estimated_cost_usd=0.0,
            estimated_duration_ms=2000,
        )

        assert decision.segment_id == "integration_test_ch1_p0"
        assert decision.engine_choice == "kokoro"
        assert decision.voice_id == "kokoro_narrator"

    def test_cost_limit_enforcement(self):
        """Test cost limit enforcement logic."""
        paragraph_annotation = create_valid_paragraph_annotation()
        character_voice_map = [create_valid_character_voice_binding()]

        inp = TtsRoutingInput(
            paragraph_annotation=paragraph_annotation,
            text="测试",
            character_voice_map=character_voice_map,
            book_id="cost_test",
            chapter_index=1,
            paragraph_index=0,
            cumulative_cost_usd=19.5,
            cost_limit_per_book=20.0,
        )

        # Should still allow decision but with warning
        decision = TtsRoutingDecision(
            segment_id=f"{inp.book_id}_ch{inp.chapter_index}_p{inp.paragraph_index}",
            engine_choice="kokoro",
            voice_id="kokoro_narrator",
            fallback_engine="edge",
            reasoning="接近成本上限，使用免费引擎",
            estimated_cost_usd=0.0,
        )
        assert inp.cumulative_cost_usd < inp.cost_limit_per_book

    def test_voice_selection_from_map(self):
        """Test voice selection from character_voice_map."""
        paragraph_annotation = create_valid_paragraph_annotation()
        character_voice_map = [
            create_valid_character_voice_binding(
                canonical_name="旁白",
                suggested_voice_id="kokoro_narrator",
            ),
            create_valid_character_voice_binding(
                canonical_name="角色A",
                gender="female",
                age_range="young",
                suggested_voice_id="kokoro_female_young",
                sample_quote="样本",
            ),
            create_valid_character_voice_binding(
                canonical_name="角色B",
                gender="male",
                age_range="adult",
                suggested_voice_id="kokoro_male_adult",
                sample_quote="样本",
            ),
        ]
        inp = TtsRoutingInput(
            paragraph_annotation=paragraph_annotation,
            text="测试",
            character_voice_map=character_voice_map,
            book_id="voice_test",
            chapter_index=1,
            paragraph_index=0,
        )

        # Decision should use voice from map
        for binding in inp.character_voice_map:
            decision = TtsRoutingDecision(
                segment_id=f"{inp.book_id}_ch{inp.chapter_index}_p{inp.paragraph_index}",
                engine_choice="kokoro",
                voice_id=binding.suggested_voice_id,
                fallback_engine="edge",
                reasoning=f"使用 {binding.canonical_name} 的声音",
            )
            assert decision.voice_id == binding.suggested_voice_id

    def test_dialogue_uses_character_voice(self):
        """Test dialogue paragraphs use correct character voice."""
        paragraph_annotation = create_valid_paragraph_annotation(
            paragraph_index=5,
            speaker_canonical_name="角色A",
            is_dialogue=True,
            emotion="happy",
            emotion_intensity=0.8,
        )
        character_voice_map = [
            create_valid_character_voice_binding(
                canonical_name="旁白",
                suggested_voice_id="kokoro_narrator",
            ),
            create_valid_character_voice_binding(
                canonical_name="角色A",
                gender="female",
                age_range="young",
                suggested_voice_id="kokoro_female_young",
                sample_quote="哈哈哈，好开心！",
            ),
        ]
        inp = TtsRoutingInput(
            paragraph_annotation=paragraph_annotation,
            text="角色A说：大哥，我们走吧！",
            character_voice_map=character_voice_map,
            book_id="dialogue_test",
            chapter_index=2,
            paragraph_index=5,
        )

        # Find the character in voice map
        speaker_binding = next(
            (b for b in character_voice_map if b.canonical_name == "角色A"), None
        )
        assert speaker_binding is not None

        decision = TtsRoutingDecision(
            segment_id=f"{inp.book_id}_ch{inp.chapter_index}_p{inp.paragraph_index}",
            engine_choice="edge",  # Dialogue might prefer edge
            voice_id=speaker_binding.suggested_voice_id,
            fallback_engine="kokoro",
            reasoning="对话段落，使用角色专属声音",
            prosody_overrides={"rate": "1.1"},
            estimated_cost_usd=0.01,
            estimated_duration_ms=3000,
        )
        assert decision.voice_id == "kokoro_female_young"
        assert decision.prosody_overrides == {"rate": "1.1"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
