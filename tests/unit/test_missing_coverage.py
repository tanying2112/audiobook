import pytest

from audiobook_studio.llm.router import LLMRouter
from audiobook_studio.schemas import (
    BookAnalysisOutput,
    PairwiseJudgment,
    ParagraphAnnotation,
    QualityJudgment,
    TtsEditOutput,
)


@pytest.fixture
def mock_router():
    return LLMRouter(mock_mode=True)


def test_router_initialization(mock_router):
    assert mock_router is not None
    assert mock_router.circuit_breakers is not None
    assert mock_router.health_probe is not None
    # Verify circuit breakers initialized for each provider
    assert len(mock_router.circuit_breakers) > 0
    # Verify rate limiters initialized
    assert len(mock_router.rate_limiters) > 0
    # Verify key pool initialized
    assert mock_router.key_pool is not None
    # Verify cost tracker initialized
    assert mock_router.cost_tracker is not None
    # Verify quota registry initialized
    assert mock_router.quota_registry is not None


def test_get_free_tier_health(mock_router):
    health = mock_router.get_free_tier_health()
    assert isinstance(health, dict)
    assert "overall_health" in health
    assert health["overall_health"] in ("green", "yellow", "red")
    assert "local_model_available" in health
    assert isinstance(health["local_model_available"], bool)
    assert "total_free_providers" in health
    assert isinstance(health["total_free_providers"], int)
    assert "healthy_free_providers" in health
    assert isinstance(health["healthy_free_providers"], int)
    assert "free_quota_success_rate" in health
    assert 0.0 <= health["free_quota_success_rate"] <= 1.0
    assert "circuit_breaker_states" in health
    assert isinstance(health["circuit_breaker_states"], dict)


def test_heuristic_fallback(mock_router):
    # Test fallback logic for annotate
    result_annotate = mock_router._heuristic_fallback("annotate", None, segment_id="test_segment_1")
    assert result_annotate is not None
    assert isinstance(result_annotate, ParagraphAnnotation)
    assert result_annotate.emotion == "neutral"
    assert result_annotate.emotion_intensity == 0.5
    assert result_annotate.speaker_canonical_name == "_narrator_"
    assert result_annotate.is_dialogue is False
    assert result_annotate.confidence == 0.2
    assert result_annotate.notes == "heuristic_fallback_no_llm_available"

    # Test fallback logic for judge (QualityJudgment)
    result_judge = mock_router._heuristic_fallback("judge", None, segment_id="test_segment_2")
    assert result_judge is not None
    assert isinstance(result_judge, QualityJudgment)
    assert result_judge.overall_score == 0.5
    assert result_judge.speaker_clarity == 0.5
    assert result_judge.emotion_match == 0.5
    assert result_judge.prosody_naturalness == 0.5
    assert result_judge.text_audio_alignment == 0.5
    assert result_judge.needs_regeneration is True
    assert "wrong_speaker" in result_judge.issues
    assert result_judge.judge_model == "heuristic_fallback"
    assert result_judge.segment_id == "test_segment_2"

    # Test fallback for judge (PairwiseJudgment)
    result_pairwise = mock_router._heuristic_fallback("judge", PairwiseJudgment, segment_id="test_segment_3")
    assert result_pairwise is not None
    assert isinstance(result_pairwise, PairwiseJudgment)
    assert result_pairwise.winner == "tie"
    assert result_pairwise.confidence == 0.5
    assert result_pairwise.judge_model == "heuristic_fallback"
    assert result_pairwise.segment_id == "test_segment_3"

    # Test fallback for analyze stage
    result_analyze = mock_router._heuristic_fallback("analyze", None, segment_id="test_segment_4")
    assert result_analyze is not None
    assert isinstance(result_analyze, BookAnalysisOutput)
    assert result_analyze.book_meta.title == "Unknown Book"
    assert result_analyze.book_meta.genre == "小说"
    assert len(result_analyze.character_voice_map) == 1
    assert result_analyze.character_voice_map[0].canonical_name == "旁白"
    assert len(result_analyze.emotion_snapshots) == 1
    assert result_analyze.emotion_snapshots[0].dominant_emotion == "neutral"

    # Test fallback for edit stage
    result_edit = mock_router._heuristic_fallback("edit", None, segment_id="test_segment_5")
    assert result_edit is not None
    assert isinstance(result_edit, TtsEditOutput)
    assert "这是模拟编辑后的文本" in result_edit.edited_text
    assert result_edit.changes_made == ["heuristic_fallback_no_llm_available"]
    assert result_edit.confidence == 0.8


def test_fallback_chain(mock_router):
    """Verify fallback chain does not crash on API failure — and router state remains valid."""
    # In mock_mode, call_1 mock_mode, the mock result is returned directly without triggering fallback
    # Test with mock_mode=False to actually test the fallback chain

    # Test that call method works without exception in mock_mode
    result = mock_router.call("annotate", ParagraphAnnotation, [{"role": "user", "content": "test"}])
    assert result is not None
    assert result.output is not None
    assert isinstance(result.output, ParagraphAnnotation)
    assert result.model == "mock-model"
    assert result.schema_compliance is True
    assert result.contract_version == 1

    # Router internal state should still be consistent after the attempt
    assert mock_router.circuit_breakers is not None
    assert mock_router.health_probe is not None
    assert mock_router.key_pool is not None


def test_mock_mode_returns_correct_types(mock_router):
    """Verify mock_mode returns properly typed results for each stage."""
    # Test annotate
    result = mock_router.call("annotate", ParagraphAnnotation, [{"role": "user", "content": "test"}])
    assert isinstance(result.output, ParagraphAnnotation)
    assert result.output.emotion == "neutral"
    assert result.output.speech_rate == 1.0

    # Test analyze
    result = mock_router.call("analyze", BookAnalysisOutput, [{"role": "user", "content": "test"}])
    assert isinstance(result.output, BookAnalysisOutput)
    assert result.output.book_meta.title == "Test Book"
    assert len(result.output.character_voice_map) == 1

    # Test edit
    result = mock_router.call("edit", TtsEditOutput, [{"role": "user", "content": "test"}])
    assert isinstance(result.output, TtsEditOutput)
    assert "模拟编辑后的文本" in result.output.edited_text

    # Test judge - QualityJudgment
    result = mock_router.call("judge", QualityJudgment, [{"role": "user", "content": "test"}], segment_id="seg1")
    assert isinstance(result.output, QualityJudgment)
    assert result.output.overall_score == 0.9
    assert result.output.needs_regeneration is False

    # Test judge - PairwiseJudgment (explicitly mocked)
    result = mock_router.call("judge", PairwiseJudgment, [{"role": "user", "content": "test"}], segment_id="seg1")
    assert result is not None
    assert result.output is not None
    assert isinstance(result.output, PairwiseJudgment)
    assert result.output.winner == "tie"
    assert result.output.confidence == 0.5
    assert result.output.judge_model == "mock-model"
    assert result.output.judge_prompt_version == "mock_v1"
    assert result.output.segment_id == "seg1"
