"""Tests for feedback/processor module."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from src.audiobook_studio.feedback.processor import (
    PATTERN_TAXONOMY,
    DiffAnalysisResult,
    AggregateAnalysis,
    _compute_text_similarity,
    _extract_key_differences,
    _infer_pattern_tags,
    analyze_single_feedback,
    analyze_batch,
    _generate_recommendations,
    get_trend_report,
)


class TestComputeTextSimilarity:
    """Tests for _compute_text_similarity function."""

    def test_identical_strings(self):
        assert _compute_text_similarity("hello world", "hello world") == 1.0

    def test_completely_different(self):
        sim = _compute_text_similarity("hello", "world")
        assert 0 <= sim < 1.0

    def test_empty_strings(self):
        assert _compute_text_similarity("", "") == 1.0

    def test_one_empty(self):
        assert _compute_text_similarity("hello", "") == 0.0
        assert _compute_text_similarity("", "hello") == 0.0

    def test_partial_similarity(self):
        sim = _compute_text_similarity("hello world", "hello there")
        assert 0.5 < sim < 1.0


class TestExtractKeyDifferences:
    """Tests for _extract_key_differences function."""

    def test_missing_key_in_llm(self):
        llm = {"a": 1}
        cor = {"a": 1, "b": 2}
        diffs = _extract_key_differences(llm, cor)
        assert any("LLM 缺失字段 'b'" in d for d in diffs)

    def test_extra_key_in_llm(self):
        llm = {"a": 1, "b": 2}
        cor = {"a": 1}
        diffs = _extract_key_differences(llm, cor)
        assert any("LLM 多余字段 'b'" in d for d in diffs)

    def test_different_values(self):
        llm = {"key": "completely different text"}
        cor = {"key": "another totally different value"}
        diffs = _extract_key_differences(llm, cor)
        assert any("字段 'key' 文本差异大" in d for d in diffs)

    def test_string_similarity(self):
        llm = {"text": "hello world"}
        cor = {"text": "hello there"}
        diffs = _extract_key_differences(llm, cor)
        assert any("文本差异大" in d for d in diffs)

    def test_no_differences(self):
        llm = {"a": 1, "b": "test"}
        cor = {"a": 1, "b": "test"}
        diffs = _extract_key_differences(llm, cor)
        assert len(diffs) == 0


class TestInferPatternTags:
    """Tests for _infer_pattern_tags function."""

    def test_edit_for_tts_dialogue(self):
        llm = {"speaker": "A"}
        cor = {"speaker": "B"}
        tags = _infer_pattern_tags("edit_for_tts", llm, cor, "对话归属错误", [])
        assert "dialogue_attribution" in tags

    def test_edit_for_tts_emotion_too_mild(self):
        llm = {"emotion": "neutral"}
        cor = {"emotion": "happy"}
        tags = _infer_pattern_tags("edit_for_tts", llm, cor, "情感不足，需要更强烈", [])
        assert "emotion_too_mild" in tags

    def test_edit_for_tts_emotion_too_strong(self):
        llm = {"emotion": "excited"}
        cor = {"emotion": "calm"}
        tags = _infer_pattern_tags("edit_for_tts", llm, cor, "情感过度，太强了", [])
        assert "emotion_too_strong" in tags

    def test_edit_for_tts_emotion_wrong(self):
        llm = {"emotion": "happy"}
        cor = {"emotion": "sad"}
        tags = _infer_pattern_tags("edit_for_tts", llm, cor, "情感类型错误", [])
        assert "emotion_wrong" in tags

    def test_edit_for_tts_speaker_wrong(self):
        tags = _infer_pattern_tags("edit_for_tts", {}, {}, "说话人识别错误", [])
        assert "speaker_wrong" in tags

    def test_edit_for_tts_pause_missing(self):
        tags = _infer_pattern_tags("edit_for_tts", {}, {}, "缺少停顿", [])
        assert "pause_missing" in tags

    def test_edit_for_tts_pause_too_long(self):
        tags = _infer_pattern_tags("edit_for_tts", {}, {}, "停顿过长", [])
        assert "pause_too_long" in tags

    def test_edit_for_tts_sfx_missing(self):
        tags = _infer_pattern_tags("edit_for_tts", {}, {}, "缺少音效", [])
        assert "sfx_missing" in tags

    def test_edit_for_tts_text_colloquial(self):
        llm = {"edited_text": "longer formal text"}
        cor = {"edited_text": "short"}
        tags = _infer_pattern_tags("edit_for_tts", llm, cor, "文本过于书面化", [])
        assert "text_colloquial" in tags

    def test_edit_for_tts_text_formal(self):
        llm = {"edited_text": "short"}
        cor = {"edited_text": "longer formal text"}
        tags = _infer_pattern_tags("edit_for_tts", llm, cor, "文本过于口语化", [])
        assert "text_formal" in tags

    def test_quality_judge_clipping(self):
        tags = _infer_pattern_tags("quality_judge", {}, {}, "削波失真", [])
        assert "clipping" in tags

    def test_quality_judge_silence(self):
        tags = _infer_pattern_tags("quality_judge", {}, {}, "静音段", [])
        assert "silence" in tags

    def test_quality_judge_low_volume(self):
        tags = _infer_pattern_tags("quality_judge", {}, {}, "音量过低", [])
        assert "low_volume" in tags

    def test_quality_judge_prosody_robotic(self):
        tags = _infer_pattern_tags("quality_judge", {}, {}, "机器人感", [])
        assert "prosody_robotic" in tags

    def test_quality_judge_prosody_flat(self):
        tags = _infer_pattern_tags("quality_judge", {}, {}, "语调平淡", [])
        assert "prosody_flat" in tags

    def test_deduplication(self):
        tags = _infer_pattern_tags(
            "edit_for_tts", {}, {},
            "对话归属错误，说话人识别错误",  # Both map to same pattern
            []
        )
        # Should not have duplicates
        assert len(tags) == len(set(tags))


class TestAnalyzeSingleFeedback:
    """Tests for analyze_single_feedback function."""

    def test_basic_analysis(self):
        mock_record = MagicMock()
        mock_record.feedback_id = "fb-123"
        mock_record.stage = "edit_for_tts"
        mock_record.llm_output = {"emotion": "neutral", "text": "hello"}
        mock_record.corrected_output = {"emotion": "happy", "text": "hello"}
        mock_record.rationale = "情感不足，需要更强烈"

        result = analyze_single_feedback(mock_record)

        assert result.feedback_id == "fb-123"
        assert result.stage == "edit_for_tts"
        assert "emotion_too_mild" in result.pattern_tags
        assert result.similarity_score < 1.0
        assert len(result.key_differences) > 0

    def test_no_differences(self):
        mock_record = MagicMock()
        mock_record.feedback_id = "fb-456"
        mock_record.stage = "edit_for_tts"
        mock_record.llm_output = {"emotion": "happy", "text": "hello"}
        mock_record.corrected_output = {"emotion": "happy", "text": "hello"}
        mock_record.rationale = "无差异"

        result = analyze_single_feedback(mock_record)

        assert result.similarity_score == 1.0
        assert len(result.pattern_tags) == 0
        assert len(result.key_differences) == 0

    def test_diff_summary_generated(self):
        mock_record = MagicMock()
        mock_record.feedback_id = "fb-789"
        mock_record.stage = "edit_for_tts"
        mock_record.llm_output = {"a": 1, "b": 2}
        mock_record.corrected_output = {"a": 1, "b": 3}
        mock_record.rationale = "修改理由 情感不足"

        result = analyze_single_feedback(mock_record)

        assert "Stage: edit_for_tts" in result.diff_summary
        assert "Key diffs" in result.diff_summary
        # With emotion pattern detected, Patterns should be present
        assert "Patterns:" in result.diff_summary


class TestAnalyzeBatch:
    """Tests for analyze_batch function."""

    def test_no_unprocessed_feedback(self):
        mock_db = MagicMock()
        with patch("src.audiobook_studio.feedback.collector.list_unprocessed_feedback", return_value=[]):
            result = analyze_batch(mock_db)

            assert result.total_analyzed == 0
            assert result.pattern_frequency == {}
            assert result.stage_distribution == {}
            assert result.top_patterns == []
            assert "没有未处理的反馈记录" in result.recommendations[0]

    def test_batch_analysis(self):
        mock_db = MagicMock()

        # Create mock records
        mock_record1 = MagicMock()
        mock_record1.feedback_id = "fb-1"
        mock_record1.stage = "edit_for_tts"
        mock_record1.llm_output = {"emotion": "neutral"}
        mock_record1.corrected_output = {"emotion": "happy"}
        mock_record1.rationale = "情感不足"

        mock_record2 = MagicMock()
        mock_record2.feedback_id = "fb-2"
        mock_record2.stage = "quality_judge"
        mock_record2.llm_output = {"score": 0.5}
        mock_record2.corrected_output = {"score": 0.8}
        mock_record2.rationale = "削波失真"

        with patch("src.audiobook_studio.feedback.collector.list_unprocessed_feedback",
                   return_value=[mock_record1, mock_record2]):
            with patch("src.audiobook_studio.feedback.collector.mark_feedback_processed") as mock_mark:
                result = analyze_batch(mock_db, limit=10)

                assert result.total_analyzed == 2
                assert "edit_for_tts" in result.stage_distribution
                assert "quality_judge" in result.stage_distribution
                assert len(result.top_patterns) > 0
                assert mock_mark.call_count == 2
                mock_db.commit.assert_called_once()


class TestGenerateRecommendations:
    """Tests for _generate_recommendations function."""

    def test_no_patterns(self):
        recs = _generate_recommendations([], {})
        assert "未检测到显著模式" in recs[0]

    def test_with_patterns(self):
        top_patterns = [
            ("emotion_too_mild", 10),
            ("dialogue_attribution", 5),
        ]
        stage_dist = {"edit_for_tts": 15}

        recs = _generate_recommendations(top_patterns, stage_dist)

        assert len(recs) >= 2
        assert "emotion_too_mild" in recs[0]
        assert "dialogue_attribution" in recs[1]
        assert "edit_for_tts" in recs[2]
        assert "优先优化" in recs[2]


class TestGetTrendReport:
    """Tests for get_trend_report function."""

    def test_trend_report(self):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter1 = MagicMock()
        mock_filter2 = MagicMock()

        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter1
        mock_filter1.filter.return_value = mock_filter2

        mock_record1 = MagicMock()
        mock_record1.stage = "edit_for_tts"
        mock_record1.source = "human_edit"
        mock_record1.pattern_tags = ["emotion_too_mild", "dialogue_attribution"]

        mock_record2 = MagicMock()
        mock_record2.stage = "quality_judge"
        mock_record2.source = "quality_judge"
        mock_record2.pattern_tags = ["clipping"]

        mock_filter2.all.return_value = [mock_record1, mock_record2]

        result = get_trend_report(mock_db, project_id=1, days=7)

        assert result["period_days"] == 7
        assert result["total_feedback"] == 2
        assert "edit_for_tts" in result["stage_distribution"]
        assert "quality_judge" in result["stage_distribution"]
        assert "human_edit" in result["source_distribution"]
        assert "quality_judge" in result["source_distribution"]
        assert "emotion_too_mild" in result["pattern_frequency"]
        assert "dialogue_attribution" in result["pattern_frequency"]
        assert "clipping" in result["pattern_frequency"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])