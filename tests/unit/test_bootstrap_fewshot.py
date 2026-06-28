"""Unit tests for BootstrapFewShot Optimizer with DSPy GEPA integration.

Tests:
- MultiObjectiveLoss computation
- EarlyStoppingStopper behavior
- BootstrapFewShotOptimizer core functionality
- run_bootstrap_optimization entry point
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.audiobook_studio.feedback.bootstrap_fewshot import (
    BUDGET_LIMIT,
    BootstrapFewShotOptimizer,
    EarlyStoppingStopper,
    MultiObjectiveLoss,
    OptimizationMetrics,
    OptimizationResult,
    create_multi_objective_metric,
    load_training_examples,
    run_bootstrap_optimization,
)


class TestMultiObjectiveLoss:
    """Tests for MultiObjectiveLoss class."""

    def test_default_weights(self):
        """Default weights should be 0.5 each."""
        loss = MultiObjectiveLoss()
        assert loss.weights == {"character_recognition": 0.5, "voice_design": 0.5}

    def test_custom_weights(self):
        """Custom weights should be accepted."""
        loss = MultiObjectiveLoss(
            weights={"character_recognition": 0.7, "voice_design": 0.3}
        )
        assert loss.weights == {"character_recognition": 0.7, "voice_design": 0.3}

    def test_compute_loss_character_correct(self):
        """Loss should be 0 when character is correct."""
        loss_fn = MultiObjectiveLoss()
        predicted = {"character": "张三"}
        ground_truth = {"character": "张三"}
        assert loss_fn.compute_loss(predicted, ground_truth) == 0.0

    def test_compute_loss_character_wrong(self):
        """Loss should include weighted character error."""
        loss_fn = MultiObjectiveLoss()
        predicted = {"character": "张三"}
        ground_truth = {"character": "李四"}
        assert loss_fn.compute_loss(predicted, ground_truth) == 0.5

    def test_compute_loss_voice_correct(self):
        """Loss should be 0 when voice is correct."""
        loss_fn = MultiObjectiveLoss()
        predicted = {"voice": "narrator_male"}
        ground_truth = {"voice": "narrator_male"}
        assert loss_fn.compute_loss(predicted, ground_truth) == 0.0

    def test_compute_loss_both_wrong(self):
        """Loss should sum both weighted errors."""
        loss_fn = MultiObjectiveLoss()
        predicted = {"character": "张三", "voice": "narrator_male"}
        ground_truth = {"character": "李四", "voice": "dialogue_female"}
        # Both wrong: 0.5 + 0.5 = 1.0
        assert loss_fn.compute_loss(predicted, ground_truth) == 1.0

    def test_compute_pareto_score(self):
        """Pareto score should combine weighted accuracies."""
        loss_fn = MultiObjectiveLoss()
        metrics = OptimizationMetrics(
            character_recognition_accuracy=0.8,
            voice_design_accuracy=0.6,
        )
        # 0.5 * 0.8 + 0.5 * 0.6 = 0.7
        assert loss_fn.compute_pareto_score(metrics) == 0.7


class TestEarlyStoppingStopper:
    """Tests for EarlyStoppingStopper class."""

    def test_no_stop_on_improvement(self):
        """Should not stop when improving."""
        stopper = EarlyStoppingStopper(patience=3)
        assert stopper([0.5]) is False
        assert stopper([0.6]) is False  # Improved
        assert (
            stopper([0.6]) is False
        )  # Equal to best - no_improve_count increments to 1
        assert stopper.no_improve_count == 1  # Equal score counts as no improvement

    def test_stop_after_patience(self):
        """Should stop after patience exhausted."""
        stopper = EarlyStoppingStopper(patience=3)
        stopper([0.8])  # Initial best
        assert stopper([0.7]) is False  # no_improve_count = 1
        assert stopper([0.6]) is False  # no_improve_count = 2
        assert stopper([0.5]) is True  # no_improve_count = 3, patience reached
        assert stopper.no_improve_count == 3

    def test_empty_scores(self):
        """Should handle empty scores gracefully."""
        stopper = EarlyStoppingStopper(patience=3)
        assert stopper([]) is False


class TestCreateMultiObjectiveMetric:
    """Tests for create_multi_objective_metric function."""

    def test_character_correct(self):
        """Metric should return score 1 when character matches."""
        metric = create_multi_objective_metric()

        gold = Mock()
        gold.character = "张三"
        gold.voice = "narrator_male"
        gold.outputs.return_value = {"character": "张三", "voice": "narrator_male"}

        pred = type(
            "obj",
            (object,),
            {"__dict__": {"character_name": "张三", "voice_design": ""}},
        )()

        result = metric(gold, pred)
        assert result.score == 0.5  # Only character correct (weight 0.5)
        assert "correct" in result.feedback.lower() or "Character" in result.feedback

    def test_voice_correct(self):
        """Metric should return score for voice match."""
        metric = create_multi_objective_metric()

        gold = Mock()
        gold.character = "张三"
        gold.voice = "narrator_male"
        gold.outputs.return_value = {"character": "张三", "voice": "narrator_male"}

        pred = type(
            "obj",
            (object,),
            {"__dict__": {"character_name": "", "voice_design": "narrator_male"}},
        )()

        result = metric(gold, pred)
        assert result.score == 0.5  # Only voice correct (weight 0.5)

    def test_both_correct(self):
        """Metric should return combined score when both match."""
        metric = create_multi_objective_metric()

        gold = Mock()
        gold.character = "张三"
        gold.voice = "narrator_male"
        gold.outputs.return_value = {"character": "张三", "voice": "narrator_male"}

        pred = type(
            "obj",
            (object,),
            {"__dict__": {"character_name": "张三", "voice_design": "narrator_male"}},
        )()

        result = metric(gold, pred)
        assert result.score == 1.0  # Both correct (weight 0.5 + 0.5)


class TestBootstrapFewShotOptimizer:
    """Tests for BootstrapFewShotOptimizer class."""

    @pytest.fixture
    def sample_training_data(self):
        """Sample training data for testing."""
        return [
            (
                "张三说：'今天天气真好！'",
                {"character": "张三", "voice": "dialogue_male"},
            ),
            (
                "李红问道：'你确定要这样做吗？'",
                {"character": "李红", "voice": "dialogue_female"},
            ),
            (
                "旁白描述道：这是一个阴雨天。",
                {"character": "旁白", "voice": "narrator"},
            ),
        ]

    def test_initialization(self):
        """Optimizer should initialize with correct parameters."""
        optimizer = BootstrapFewShotOptimizer(
            stage="annotate_paragraph",
            budget_limit=500,
            early_stop_patience=10,
        )
        assert optimizer.stage == "annotate_paragraph"
        assert optimizer.budget_limit == 500
        assert optimizer.early_stop_patience == 10
        assert optimizer.loss_fn.weights["character_recognition"] == 0.5
        assert optimizer.loss_fn.weights["voice_design"] == 0.5

    def test_custom_weights(self):
        """Optimizer should accept custom weights."""
        optimizer = BootstrapFewShotOptimizer(
            stage="test",
            char_weight=0.7,
            voice_weight=0.3,
        )
        assert optimizer.loss_fn.weights["character_recognition"] == 0.7
        assert optimizer.loss_fn.weights["voice_design"] == 0.3

    def test_optimize_empty_training_data(self, sample_training_data):
        """Should handle empty training data gracefully."""
        optimizer = BootstrapFewShotOptimizer(stage="test")
        result = optimizer.optimize("initial prompt", [])

        assert result.optimized_prompt == "initial prompt"
        assert result.iterations_completed == 0
        assert result.stopped_early is False
        assert result.improvement_ratio == 0.0

    def test_optimize_with_training_data(self, sample_training_data):
        """Should run optimization with training data."""
        optimizer = BootstrapFewShotOptimizer(stage="test", budget_limit=100)

        # Mock GEPA compile to avoid actual LLM calls
        with patch(
            "src.audiobook_studio.feedback.bootstrap_fewshot.GEPA"
        ) as mock_gepa_class:
            mock_gepa = Mock()
            mock_module = Mock()
            mock_module.detailed_results = None

            # Set up the mock to return a module with no improvements
            mock_gepa.compile.return_value = mock_module
            mock_gepa_class.return_value = mock_gepa

            result = optimizer.optimize("initial prompt", sample_training_data)

        assert result.optimized_prompt is not None
        # GEPA should have been called
        mock_gepa_class.assert_called_once()
        mock_gepa.compile.assert_called_once()


class TestLoadTrainingExamples:
    """Tests for load_training_examples function."""

    def test_load_from_stage_few_shot(self):
        """Should load examples from stage-specific few_shot.jsonl."""
        # Use annotate_paragraph which has few_shot.jsonl
        prompt, examples = load_training_examples("annotate_paragraph")

        assert prompt is not None
        assert len(examples) >= 3  # At least the 3 examples in few_shot.jsonl

    def test_load_from_bootstrap_fallback(self):
        """Should fallback to bootstrap_examples.json if stage has no few_shot."""
        prompt, examples = load_training_examples(
            "nonexistent_stage", "tests/golden/bootstrap_examples.json"
        )

        assert prompt is not None
        assert len(examples) >= 1  # At least some examples

    def test_returns_character_and_voice_targets(self):
        """Training examples should have character and voice fields."""
        prompt, examples = load_training_examples("annotate_paragraph")

        for text, target in examples:
            assert "character" in target
            assert "voice" in target


class TestRunBootstrapOptimization:
    """Tests for run_bootstrap_optimization entry point."""

    def test_run_with_valid_stage(self):
        """Should run optimization for valid stage."""
        # Mock GEPA to avoid actual LLM calls
        with patch(
            "src.audiobook_studio.feedback.bootstrap_fewshot.BootstrapFewShotOptimizer"
        ) as mock_optimizer_class:
            mock_optimizer = Mock()
            mock_optimizer.optimize.return_value = OptimizationResult(
                optimized_prompt="optimized",
                metrics=OptimizationMetrics(
                    character_recognition_accuracy=0.8,
                    voice_design_accuracy=0.7,
                    overall_score=0.75,
                ),
                improvement_ratio=0.5,
                stopped_early=True,
                iterations_completed=100,
            )
            mock_optimizer_class.return_value = mock_optimizer

            result = run_bootstrap_optimization("annotate_paragraph")

        assert result is not None
        assert result.improvement_ratio == 0.5
        assert mock_optimizer.optimize.called

    def test_run_with_no_training_data(self):
        """Should return None for stage with no training data."""
        with patch(
            "src.audiobook_studio.feedback.bootstrap_fewshot.load_training_examples"
        ) as mock_load:
            mock_load.return_value = ("prompt", [])

            result = run_bootstrap_optimization("empty_stage")

        assert result is None

    def test_run_catches_exceptions(self):
        """Should catch and log exceptions gracefully."""
        with patch(
            "src.audiobook_studio.feedback.bootstrap_fewshot.load_training_examples"
        ) as mock_load:
            mock_load.side_effect = Exception("Test error")

            result = run_bootstrap_optimization("error_stage")

        assert result is None


class TestOptimizationResult:
    """Tests for OptimizationResult dataclass."""

    def test_default_values(self):
        """Should have correct default values."""
        result = OptimizationResult(
            optimized_prompt="test",
            metrics=OptimizationMetrics(),
            improvement_ratio=0.0,
        )
        assert result.stopped_early is False
        assert result.iterations_completed == 0
        assert result.pareto_frontier is None


class TestOptimizationMetrics:
    """Tests for OptimizationMetrics dataclass."""

    def test_default_values(self):
        """Should have correct default values."""
        metrics = OptimizationMetrics()
        assert metrics.character_recognition_accuracy == 0.0
        assert metrics.voice_design_accuracy == 0.0
        assert metrics.overall_score == 0.0
        assert metrics.inference_calls_used == 0
        assert metrics.cost_usd == 0.0
        assert metrics.iterations_completed == 0
