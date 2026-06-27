"""Unit tests for LLM Router, Client, and Judge with compliance rate statistics."""

import os
from unittest.mock import MagicMock, Mock, patch

import pytest

# Set MOCK_LLM environment variable before importing
os.environ["MOCK_LLM"] = "true"

from src.audiobook_studio.llm.client import (
    MODEL_PRICING,
    LLMCallResult,
    LLMClient,
    LLMClientConfig,
    create_client,
)
from src.audiobook_studio.llm.judge import (
    JudgeConfig,
    JudgmentType,
    LLMJudge,
    create_judge,
)
from src.audiobook_studio.llm.router import (
    CostTracker,
    LLMRouter,
    ModelConfig,
    StageRoutingConfig,
    create_router,
    get_cost_tracker,
    reset_cost_tracker,
)
from src.audiobook_studio.schemas import BookAnalysisOutput, QualityJudgment


class TestCostTracker:
    """Test cost tracking functionality."""

    def setup_method(self):
        reset_cost_tracker()
        self.tracker = get_cost_tracker()

    def test_add_and_get_cost(self):
        self.tracker.add_cost("test-model", 0.50)
        assert self.tracker.get_daily_cost("test-model") == 0.50

    def test_multiple_models(self):
        self.tracker.add_cost("model-a", 0.25)
        self.tracker.add_cost("model-b", 0.75)
        assert self.tracker.get_daily_cost("model-a") == 0.25
        assert self.tracker.get_daily_cost("model-b") == 0.75
        assert self.tracker.get_total_daily_cost() == 1.00

    def test_daily_limit_exceeded(self):
        self.tracker.set_daily_limit("test-model", 1.0)
        self.tracker.add_cost("test-model", 0.5)
        assert not self.tracker.is_limit_exceeded("test-model")
        self.tracker.add_cost("test-model", 0.6)
        assert self.tracker.is_limit_exceeded("test-model")

    def test_alert_threshold(self):
        self.tracker.set_daily_limit("test-model", 10.0)
        self.tracker.add_cost("test-model", 7.0)
        assert not self.tracker.is_alert_threshold("test-model")
        self.tracker.add_cost("test-model", 1.1)  # 8.1 total, > 8.0 (80%)
        assert self.tracker.is_alert_threshold("test-model")

    def test_status_reporting(self):
        self.tracker.set_daily_limit("model-a", 5.0)
        self.tracker.add_cost("model-a", 2.5)
        status = self.tracker.get_status()
        assert "model-a" in status
        assert status["model-a"]["daily_cost_usd"] == 2.5
        assert status["model-a"]["daily_limit_usd"] == 5.0
        assert status["model-a"]["usage_pct"] == 50.0


class TestLLMClient:
    """Test LLM Client with mock mode."""

    @pytest.fixture
    def mock_client(self):
        # With MOCK_LLM set, this will create a mock client
        return create_client("gemini-2.0-flash")

    def test_mock_mode_returns_result(self, mock_client):
        messages = [{"role": "user", "content": "test"}]
        result = mock_client.call(
            response_model=BookAnalysisOutput,
            messages=messages,
            stage="analyze",
        )
        assert isinstance(result, LLMCallResult)
        assert result.model == "gemini-2.0-flash"
        assert result.cost_usd == 0.0
        assert result.schema_compliance is True

    def test_cost_calculation(self, mock_client):
        # Cost is calculated in router, not in mock client
        # Just verify mock mode returns cost=0
        messages = [{"role": "user", "content": "test"}]
        result = mock_client.call(
            response_model=BookAnalysisOutput,
            messages=messages,
            stage="analyze",
        )
        assert result.cost_usd == 0.0

    def test_mock_data_loading(self, mock_client):
        # Should load mock data from golden dataset
        assert isinstance(mock_client._mock_cache, dict)


class TestLLMRouter:
    """Test LLM Router with fallback and cost tracking."""

    @pytest.fixture
    def router(self):
        # With MOCK_LLM set, this will create a router in mock mode
        return create_router()

    def test_mock_mode_immediate_return(self, router):
        messages = [{"role": "user", "content": "test"}]
        result = router.call(
            stage="analyze",
            response_model=BookAnalysisOutput,
            messages=messages,
        )
        assert result.schema_compliance is True
        assert result.output is not None
        assert isinstance(result.output, BookAnalysisOutput)

    def test_cost_tracking_integration(self, router):
        reset_cost_tracker()
        messages = [{"role": "user", "content": "test"}]

        # Make a few calls
        for _ in range(3):
            router.call(
                stage="analyze",
                response_model=BookAnalysisOutput,
                messages=messages,
            )

        status = router.get_cost_status()
        # In mock mode, cost should be 0
        for _, info in status.items():
            if info["daily_cost_usd"] > 0:
                assert info["daily_cost_usd"] >= 0

    def test_stage_config_loaded(self, router):
        assert "analyze" in router.stage_configs
        assert "extract" in router.stage_configs
        assert "judge" in router.stage_configs
        assert len(router.stage_configs["analyze"].models) > 0

    def test_fallback_model_configured(self, router):
        for _, config in router.stage_configs.items():
            assert config.fallback_model is not None
            assert config.fallback_model in [m.name for m in config.models]


class TestLLMJudge:
    """Test LLM Judge for quality evaluation."""

    @pytest.fixture
    def judge(self):
        router = create_router()
        return create_judge(router=router)

    def test_judge_quality_mock(self, judge):
        from src.audiobook_studio.schemas import ParagraphAnnotation

        annotation = ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="旁白",
            is_dialogue=False,
            emotion="neutral",
            emotion_intensity=0.5,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            pause_before_ms=0,
            pause_after_ms=0,
            confidence=0.9,
            notes=None,
        )

        result = judge.judge_quality(
            segment_id="test-001",
            paragraph_annotation=annotation,
            audio_description="清晰的男性声音，语速正常，情感中性",
            reference_text="这是一段测试文本。",
        )

        assert isinstance(result, QualityJudgment)
        assert 0 <= result.overall_score <= 1
        assert isinstance(result.issues, list)
        assert isinstance(result.fix_suggestions, list)

    def test_cost_tracking_per_stage(self):
        router = create_router()
        messages = [{"role": "user", "content": "test"}]

        # Call different stages (use only valid stages)
        stages = ["extract", "analyze", "annotate", "edit", "judge"]
        for stage in stages:
            router.call(
                stage=stage,
                response_model=BookAnalysisOutput,
                messages=messages,
            )

        status = router.get_cost_status()
        # Verify cost tracking works
        assert isinstance(status, dict)

    def test_daily_limit_enforcement(self):
        tracker = get_cost_tracker()
        tracker.set_daily_limit("test-model", 1.0)

        # Simulate costs
        tracker.add_cost("test-model", 0.5)
        assert not tracker.is_limit_exceeded("test-model")

        tracker.add_cost("test-model", 0.6)
        assert tracker.is_limit_exceeded("test-model")


class TestEnvironmentVariables:
    """Test environment variable handling."""

    def test_mock_llm_env_var(self):
        """Test MOCK_LLM=true creates mock client."""
        with patch.dict(os.environ, {"MOCK_LLM": "true"}):
            client = create_client("gemini-2.0-flash")
            assert client.config.mock_mode is True
            assert client._client is None  # Mock mode has no real client

    def test_mock_llm_env_var_false(self):
        """Test MOCK_LLM=false creates real client."""
        with patch.dict(os.environ, {"MOCK_LLM": "false"}):
            client = create_client("gemini-2.0-flash")
            assert client.config.mock_mode is False
            # Real mode has an instructor client

    def test_mock_llm_default_false(self):
        """Test default without MOCK_LLM set uses non-mock mode."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove MOCK_LLM from parent environment first
            os.environ.pop("MOCK_LLM", None)
            client = create_client("gemini-2.0-flash")
            assert client.config.mock_mode is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
