"""Tests for Module 4.2: SOP Reflection Self-Evolution System."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.pipeline.sop_reflection import (
    CorrectionCollector,
    GenreDetector,
    ReflectionEngine,
    ReflectionResult,
    RuleApplier,
    SOPBackgroundThread,
    SOPConfig,
    UserCorrection,
    get_correction_collector,
    get_genre_detector,
    get_rule_applier,
    get_sop_config,
    start_sop_background_thread,
    stop_sop_background_thread,
)


class TestSOPConfig:
    """Tests for SOPConfig."""

    def test_load_default_config(self):
        """Test loading default config when file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "agent_sop.json"
            config = SOPConfig(config_path)
            assert "genres" in config._config
            assert "default" in config._config["genres"]
            assert config.config_path.exists()

    def test_load_existing_config(self):
        """Test loading existing config file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "agent_sop.json"
            # Create a config file
            import json

            test_config = {
                "version": "1.0",
                "genres": {
                    "测试类型": {
                        "name": "测试类型",
                        "rules": {"emotion_defaults": {"默认": "neutral"}},
                        "learning_stats": {"corrections_received": 0, "confidence": 0.5},
                    }
                },
                "global_settings": {"learning_enabled": True},
            }
            with open(config_path, "w") as f:
                json.dump(test_config, f)

            config = SOPConfig(config_path)
            assert "测试类型" in config._config["genres"]

    def test_get_genre_rules(self):
        """Test getting rules for a genre."""
        config = SOPConfig()
        rules = config.get_genre_rules("玄幻")
        assert "emotion_defaults" in rules
        assert "speech_rate" in rules
        assert "pitch_shifts" in rules
        assert "voice_bindings" in rules

    def test_get_genre_rules_fallback(self):
        """Test fallback to default for unknown genre."""
        config = SOPConfig()
        rules = config.get_genre_rules("未知类型")
        assert "emotion_defaults" in rules  # Should get default rules

    def test_normalize_genre(self):
        """Test genre normalization."""
        config = SOPConfig()
        assert config._normalize_genre("玄幻") == "玄幻"
        assert config._normalize_genre("仙侠") == "玄幻"  # alias
        assert config._normalize_genre("未知") == "default"

    def test_update_genre_rules(self):
        """Test updating genre rules."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "agent_sop.json"
            config = SOPConfig(config_path)

            new_rules = {"emotion_defaults": {"learned_test": "intense"}}
            success = config.update_genre_rules("玄幻", new_rules, 0.8, "Test reasoning")
            assert success

            rules = config.get_genre_rules("玄幻")
            assert "learned_test" in rules["emotion_defaults"]

    def test_record_correction(self):
        """Test recording correction count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "agent_sop.json"
            config = SOPConfig(config_path)

            initial = config.get_genre_config("玄幻")["learning_stats"]["corrections_received"]
            config.record_correction("玄幻")
            after = config.get_genre_config("玄幻")["learning_stats"]["corrections_received"]
            assert after == initial + 1

    def test_global_settings(self):
        """Test global settings access."""
        config = SOPConfig()
        assert config.is_learning_enabled() is True
        assert config.get_min_corrections_for_update() == 3
        assert config.get_confidence_threshold() == 0.65
        assert config.get_reflection_model() == "gpt-4o-mini"
        assert config.get_reflection_temperature() == 0.3


class TestCorrectionCollector:
    """Tests for CorrectionCollector."""

    def test_add_correction(self):
        """Test adding a correction."""
        collector = CorrectionCollector()
        correction = UserCorrection(
            timestamp="2026-07-17T10:00:00Z",
            project_id=1,
            chapter_index=1,
            paragraph_index=1,
            field="emotion",
            original_value="neutral",
            corrected_value="intense",
            genre="玄幻",
        )
        success = collector.add_correction(correction)
        assert success
        assert collector.queue_size() == 1

    def test_add_correction_dict(self):
        """Test adding correction from dict."""
        collector = CorrectionCollector()
        data = {
            "project_id": 1,
            "chapter_index": 1,
            "paragraph_index": 1,
            "field": "emotion",
            "original_value": "neutral",
            "corrected_value": "intense",
            "genre": "玄幻",
        }
        success = collector.add_correction_dict(data)
        assert success
        assert collector.queue_size() == 1

    def test_get_batch(self):
        """Test getting batch of corrections."""
        collector = CorrectionCollector()
        for i in range(5):
            c = UserCorrection(
                timestamp=f"2026-07-17T10:{i:02d}:00Z",
                project_id=1,
                chapter_index=1,
                paragraph_index=i,
                field="emotion",
                original_value="neutral",
                corrected_value="intense",
                genre="玄幻",
            )
            collector.add_correction(c)

        batch = collector.get_batch(max_size=3, timeout=0.1)
        assert len(batch) == 3
        assert collector.queue_size() == 2

    def test_cache_project_genre(self):
        """Test caching project genre."""
        collector = CorrectionCollector()
        collector.cache_project_genre(1, "玄幻")
        collector.cache_project_genre(2, "都市")

        assert collector.get_project_genre(1) == "玄幻"
        assert collector.get_project_genre(2) == "都市"
        assert collector.get_project_genre(3) is None


class TestGenreDetector:
    """Tests for GenreDetector."""

    def test_detect_from_text(self):
        """Test genre detection from text."""
        detector = GenreDetector()

        # 玄幻 keywords
        assert detector.detect_from_text("主角修仙筑基金丹元婴渡劫飞升") == "玄幻"
        # 都市 keywords
        assert detector.detect_from_text("公司总裁职场办公室会议谈判") == "都市"
        # 历史 keywords
        assert detector.detect_from_text("皇帝朝廷大臣皇上奏折朝堂") == "历史"
        # 科幻 keywords
        assert detector.detect_from_text("星际飞船人工智能虚拟赛博机甲") == "科幻"
        # 悬疑 keywords
        assert detector.detect_from_text("凶手线索推理侦探尸体现场") == "悬疑"
        # 言情 keywords
        assert detector.detect_from_text("心动喜欢吻表白男友女友") == "言情"
        # Unknown
        assert detector.detect_from_text("随机文本内容") == "default"

    def test_detect_from_chapter_analysis(self):
        """Test genre detection from chapter analysis."""
        detector = GenreDetector()

        # Scene tags with 玄幻 keywords
        analyzed = {
            "book_meta": {"genre": "小说"},
            "scene_tags": ["宗门", "灵气", "丹田"],
            "story_line_summary": "修仙故事",
        }
        assert detector.detect_from_chapter_analysis(analyzed) == "玄幻"

        # Scene tags with 都市 keywords
        analyzed2 = {
            "book_meta": {"genre": "小说"},
            "scene_tags": ["公司", "办公室"],
            "story_line_summary": "职场故事",
        }
        assert detector.detect_from_chapter_analysis(analyzed2) == "都市"

        # Historical from book_meta
        analyzed3 = {
            "book_meta": {"genre": "历史"},
            "scene_tags": [],
            "story_line_summary": "",
        }
        assert detector.detect_from_chapter_analysis(analyzed3) == "历史"

        # Default fallback
        analyzed4 = {
            "book_meta": {"genre": "小说"},
            "scene_tags": [],
            "story_line_summary": "",
        }
        assert detector.detect_from_chapter_analysis(analyzed4) == "default"


class TestReflectionEngine:
    """Tests for ReflectionEngine."""

    def test_reflect_no_corrections(self):
        """Test reflection with no corrections."""
        config = SOPConfig()
        engine = ReflectionEngine(config)
        result = engine.reflect("玄幻", [])
        assert result.confidence == 0.0
        assert result.proposed_rules == {}

    def test_reflect_insufficient_corrections(self):
        """Test reflection with insufficient corrections."""
        config = SOPConfig()
        engine = ReflectionEngine(config)
        corrections = [
            UserCorrection(
                timestamp="2026-07-17T10:00:00Z",
                project_id=1,
                chapter_index=1,
                paragraph_index=1,
                field="emotion",
                original_value="neutral",
                corrected_value="intense",
                genre="玄幻",
            ),
            UserCorrection(
                timestamp="2026-07-17T10:01:00Z",
                project_id=1,
                chapter_index=1,
                paragraph_index=2,
                field="emotion",
                original_value="neutral",
                corrected_value="intense",
                genre="玄幻",
            ),
        ]
        result = engine.reflect("玄幻", corrections)
        # Need at least 3 corrections per field
        assert result.confidence == 0.0

    def test_reflect_sufficient_corrections(self):
        """Test reflection with sufficient corrections."""
        config = SOPConfig()
        engine = ReflectionEngine(config)
        corrections = []
        # 4 emotion corrections
        for i in range(4):
            corrections.append(
                UserCorrection(
                    timestamp=f"2026-07-17T10:{i:02d}:00Z",
                    project_id=1,
                    chapter_index=1,
                    paragraph_index=i,
                    field="emotion",
                    original_value="neutral",
                    corrected_value="intense",
                    genre="玄幻",
                )
            )
        # 3 speech_rate corrections
        for i in range(3):
            corrections.append(
                UserCorrection(
                    timestamp=f"2026-07-17T10:{i+10:02d}:00Z",
                    project_id=1,
                    chapter_index=1,
                    paragraph_index=i + 10,
                    field="speech_rate",
                    original_value=1.0,
                    corrected_value=1.15,
                    genre="玄幻",
                )
            )

        result = engine.reflect("玄幻", corrections)
        assert result.confidence > 0.0
        assert "emotion_defaults" in result.proposed_rules
        assert "speech_rate" in result.proposed_rules

    def test_reflect_pitch_shift(self):
        """Test reflection detecting pitch shift pattern."""
        config = SOPConfig()
        engine = ReflectionEngine(config)
        corrections = []
        for i in range(3):
            corrections.append(
                UserCorrection(
                    timestamp=f"2026-07-17T10:{i:02d}:00Z",
                    project_id=1,
                    chapter_index=1,
                    paragraph_index=i,
                    field="pitch_shift_semitones",
                    original_value=0,
                    corrected_value=-5,
                    genre="玄幻",
                )
            )

        result = engine.reflect("玄幻", corrections)
        assert result.confidence > 0.0
        assert "pitch_shifts" in result.proposed_rules


class TestRuleApplier:
    """Tests for RuleApplier."""

    def test_apply_to_annotation_input(self):
        """Test applying rules to annotation input."""
        from src.audiobook_studio.schemas import (
            BookMeta,
            CharacterVoiceBinding,
            EmotionSnapshot,
            ParagraphAnnotationInput,
        )

        config = SOPConfig()
        applier = RuleApplier(config)

        book_meta = BookMeta(
            title="测试小说",
            author="作者",
            genre="小说",
            difficulty="B",
            language="zh",
            total_chapters_estimated=10,
        )
        emotion_snapshot = EmotionSnapshot(chapter=1, dominant_emotion="neutral", intensity=0.5, notes="测试")
        voice_map = [
            CharacterVoiceBinding(
                canonical_name="主角",
                aliases=[],
                gender="male",
                age_range="young",
                suggested_voice_id="zh-CN-YunxiNeural",
                sample_quote="测试文本",
            )
        ]

        input_data = ParagraphAnnotationInput(
            paragraph_text="这是一个测试文本内容",
            paragraph_index=1,
            chapter_index=1,
            book_meta=book_meta,
            character_voice_map=voice_map,
            emotion_snapshot=emotion_snapshot,
            story_line_summary="这是一个测试故事摘要，包含足够的字符数以满足最小长度要求。" * 10,
            global_style_notes="测试风格",
        )

        enhanced = applier.apply_to_annotation_input(input_data, "玄幻")
        # Should apply protagonist voice binding from 玄幻 rules
        assert enhanced.character_voice_map[0].suggested_voice_id == "zh-CN-YunxiNeural"

    def test_apply_to_audio_postprocess(self):
        """Test applying rules to audio post-process."""
        config = SOPConfig()
        applier = RuleApplier(config)

        # Use "combat" which exists in 玄幻 speech_rate rules
        segment = {"speed": 1.0, "pitch_hz": 0.0}
        enhanced = applier.apply_to_audio_postprocess(segment, "玄幻", "combat")
        # Should apply speech_rate for combat (1.15 in rules)
        assert enhanced["speed"] == 1.15

        # Test pitch shift with valid role
        segment2 = {"speed": 1.0, "pitch_hz": 0.0}
        enhanced2 = applier.apply_to_audio_postprocess(segment2, "玄幻", "demon")
        # Should apply pitch shift for demon (-5 semitones -> -30 Hz approx)
        assert enhanced2["pitch_hz"] != 0.0


class TestSOPBackgroundThread:
    """Tests for SOPBackgroundThread."""

    def test_start_stop(self):
        """Test starting and stopping background thread."""
        config = SOPConfig()
        collector = CorrectionCollector()
        engine = ReflectionEngine(config)

        thread = SOPBackgroundThread(config, collector, engine, check_interval=1.0)
        thread.start()
        assert thread._thread.is_alive()

        thread.stop(timeout=2.0)
        assert not thread._thread.is_alive()

    def test_start_twice(self):
        """Test starting thread twice doesn't create duplicate."""
        config = SOPConfig()
        collector = CorrectionCollector()
        engine = ReflectionEngine(config)

        thread = SOPBackgroundThread(config, collector, engine, check_interval=1.0)
        thread.start()
        first_thread = thread._thread
        thread.start()  # Should not create new thread
        assert thread._thread is first_thread
        thread.stop(timeout=2.0)


class TestGlobalInstances:
    """Tests for global instance functions."""

    def test_get_sop_config(self):
        """Test get_sop_config returns singleton."""
        config1 = get_sop_config()
        config2 = get_sop_config()
        assert config1 is config2

    def test_get_correction_collector(self):
        """Test get_correction_collector returns singleton."""
        c1 = get_correction_collector()
        c2 = get_correction_collector()
        assert c1 is c2

    def test_get_genre_detector(self):
        """Test get_genre_detector returns singleton."""
        d1 = get_genre_detector()
        d2 = get_genre_detector()
        assert d1 is d2

    def test_get_rule_applier(self):
        """Test get_rule_applier returns singleton."""
        a1 = get_rule_applier()
        a2 = get_rule_applier()
        assert a1 is a2


class TestIntegration:
    """Integration tests for full SOP reflection pipeline."""

    def test_full_pipeline_correction_to_rules(self):
        """Test full pipeline: corrections -> reflection -> rule update."""
        # Use temp config
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "agent_sop.json"
            config = SOPConfig(config_path)
            collector = CorrectionCollector()
            engine = ReflectionEngine(config)

            # Submit corrections
            corrections = []
            for i in range(4):
                c = UserCorrection(
                    timestamp=f"2026-07-17T10:{i:02d}:00Z",
                    project_id=1,
                    chapter_index=1,
                    paragraph_index=i,
                    field="emotion",
                    original_value="neutral",
                    corrected_value="intense",
                    genre="玄幻",
                )
                corrections.append(c)
                collector.add_correction(c)

            for i in range(3):
                c = UserCorrection(
                    timestamp=f"2026-07-17T10:{i+10:02d}:00Z",
                    project_id=1,
                    chapter_index=1,
                    paragraph_index=i + 10,
                    field="speech_rate",
                    original_value=1.0,
                    corrected_value=1.15,
                    genre="玄幻",
                )
                corrections.append(c)
                collector.add_correction(c)

            # Reflect
            result = engine.reflect("玄幻", corrections)
            assert result.confidence >= config.get_confidence_threshold()

            # Apply rules
            success = config.update_genre_rules("玄幻", result.proposed_rules, result.confidence, result.reasoning)
            assert success

            # Verify rules updated
            rules = config.get_genre_rules("玄幻")
            assert "learned_0" in rules["emotion_defaults"]
            assert "learned_0" in rules["speech_rate"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
