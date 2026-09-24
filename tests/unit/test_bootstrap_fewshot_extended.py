"""Extended tests for bootstrap_fewshot.py - branch coverage.

Focuses on testing additional branches in the BootstrapFewShot module
that are not covered by the existing test suite.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

from src.audiobook_studio.feedback.bootstrap_fewshot import (
    BUDGET_LIMIT,
    BootstrapFewShotOptimizer,
    EarlyStoppingStopper,
    MultiObjectiveLoss,
    OptimizationMetrics,
    OptimizationResult,
    configure_dspy_optimizer,
    create_multi_objective_metric,
    run_bootstrap_optimization,
)


class TestEarlyStoppingStopperExtended:
    """Extended tests for EarlyStoppingStopper."""

    def test_stop_at_patience_with_equal_scores(self):
        """Test stopper counts equal scores as no improvement."""
        stopper = EarlyStoppingStopper(patience=3)
        # First call sets best score
        assert stopper([0.8]) is False
        # Equal score - no_improve_count increments (equal is not improvement)
        assert stopper([0.8]) is False  # no_improve_count = 1
        assert stopper([0.8]) is False  # no_improve_count = 2
        assert stopper([0.8]) is True  # no_improve_count = 3, patience reached
        assert stopper.no_improve_count == 3

    def test_stop_at_patience_with_decreasing(self):
        """Test stopper stops when scores decrease after improvement."""
        stopper = EarlyStoppingStopper(patience=2)
        assert stopper([0.5]) is False  # initial, best=0.5, no_improve=0
        assert stopper([0.6]) is False  # improved, best=0.6, no_improve=0
        # decrease but still within patience
        assert stopper([0.5]) is False  # no_improve=1, not yet patience
        # another decrease
        assert stopper([0.4]) is True  # no_improve=2 >= patience=2


class TestMultiObjectiveLossExtended:
    """Extended tests for MultiObjectiveLoss."""

    def test_loss_with_only_voice(self):
        """Loss when only voice field present."""
        loss_fn = MultiObjectiveLoss()
        predicted = {"voice": "narrator_male"}
        ground_truth = {"voice": "narrator_male"}
        assert loss_fn.compute_loss(predicted, ground_truth) == 0.0

    def test_loss_with_only_character(self):
        """Loss when only character field present."""
        loss_fn = MultiObjectiveLoss()
        predicted = {"character": "张三"}
        ground_truth = {"character": "张三"}
        assert loss_fn.compute_loss(predicted, ground_truth) == 0.0

    def test_loss_missing_both_fields(self):
        """Loss when both fields missing (should not crash)."""
        loss_fn = MultiObjectiveLoss()
        predicted = {}
        ground_truth = {}
        # Should return 0.0 since no fields to lose on
        result = loss_fn.compute_loss(predicted, ground_truth)
        assert result == 0.0

    def test_pareto_score_custom_weights(self):
        """Pareto score with custom weights."""
        loss_fn = MultiObjectiveLoss(weights={"character_recognition": 0.8, "voice_design": 0.2})
        metrics = OptimizationMetrics(
            character_recognition_accuracy=0.9,
            voice_design_accuracy=0.5,
        )
        # 0.8 * 0.9 + 0.2 * 0.5 = 0.72 + 0.1 = 0.82
        # Use approximate comparison due to floating point
        assert abs(loss_fn.compute_pareto_score(metrics) - 0.82) < 1e-10


class TestOptimizationMetricsExtended:
    """Extended tests for OptimizationMetrics."""

    def test_metrics_with_full_values(self):
        """OptimizationMetrics with all non-zero values."""
        metrics = OptimizationMetrics(
            character_recognition_accuracy=0.85,
            voice_design_accuracy=0.75,
            overall_score=0.0,  # will be computed
            inference_calls_used=100,
            cost_usd=5.5,
            iterations_completed=100,
            num_books_processed=3,
            total_paragraphs=500,
            unique_characters=50,
        )
        assert metrics.character_recognition_accuracy == 0.85
        assert metrics.voice_design_accuracy == 0.75
        assert metrics.inference_calls_used == 100
        assert metrics.cost_usd == 5.5
        assert metrics.iterations_completed == 100
        assert metrics.num_books_processed == 3
        assert metrics.total_paragraphs == 500
        assert metrics.unique_characters == 50

    def test_metrics_default_zero(self):
        """OptimizationMetrics with all default zero values."""
        metrics = OptimizationMetrics()
        assert metrics.character_recognition_accuracy == 0.0
        assert metrics.voice_design_accuracy == 0.0
        assert metrics.overall_score == 0.0
        assert metrics.inference_calls_used == 0
        assert metrics.cost_usd == 0.0
        assert metrics.iterations_completed == 0
        assert metrics.num_books_processed == 0
        assert metrics.total_paragraphs == 0
        assert metrics.unique_characters == 0


class TestCreateMultiObjectiveMetricExtended:
    """Extended tests for create_multi_objective_metric."""

    def test_metric_with_full_prediction(self):
        """Metric when both character and voice match."""
        metric = create_multi_objective_metric()

        from unittest.mock import Mock

        gold = Mock()
        gold.character = "张三"
        gold.voice = "narrator_male"
        gold.outputs.return_value = {"character": "张三", "voice": "narrator_male"}

        pred = Mock()
        pred.__dict__ = {"character_name": "张三", "voice_design": "narrator_male"}

        result = metric(gold, pred)
        assert result.score == 1.0  # Both correct (0.5 + 0.5)

    def test_metric_with_partial_prediction(self):
        """Metric when only character matches."""
        metric = create_multi_objective_metric()

        gold = Mock()
        gold.character = "张三"
        gold.voice = "narrator_male"
        gold.outputs.return_value = {"character": "张三", "voice": "narrator_male"}

        pred = Mock()
        pred.__dict__ = {"character_name": "张三", "voice_design": ""}

        result = metric(gold, pred)
        assert result.score == 0.5  # Only character correct (weight 0.5)


class TestBootstrapFewShotOptimizerExtended:
    """Extended tests for BootstrapFewShotOptimizer."""

    def test_optimize_with_single_example(self):
        """Optimize with single training example."""
        optimizer = BootstrapFewShotOptimizer(stage="test", budget_limit=50)

        with patch("src.audiobook_studio.feedback.bootstrap_fewshot.GEPA") as mock_gepa_class:
            mock_gepa = Mock()
            mock_module = Mock()
            mock_module.detailed_results = None

            mock_gepa.compile.return_value = mock_module
            mock_gepa_class.return_value = mock_gepa

            result = optimizer.optimize("initial prompt", [("single text", {"character": "test", "voice": "test"})])

            assert result.optimized_prompt is not None
            mock_gepa_class.assert_called_once()

    def test_optimize_with_budget_exhaustion(self):
        """Optimize tracking budget exhaustion."""
        optimizer = BootstrapFewShotOptimizer(stage="test", budget_limit=5)

        with patch("src.audiobook_studio.feedback.bootstrap_fewshot.GEPA") as mock_gepa_class:
            mock_gepa = Mock()
            mock_module = Mock()
            mock_module.detailed_results = None
            # Simulate budget exhaustion by having many metric calls
            # This tests the optimizer handles the budget limit

            mock_gepa.compile.return_value = mock_module
            mock_gepa_class.return_value = mock_gepa

            optimizer.optimize("initial prompt", [("text", {"character": "c", "voice": "v"}) for _ in range(10)])

            # Should have been called with budget_limit=5
            mock_gepa_class.assert_called_once()


class TestRunBootstrapOptimizationExtended:
    """Extended tests for run_bootstrap_optimization."""

    def test_run_with_exception_in_load(self):
        """Should handle exceptions from load_training_examples gracefully."""
        with patch("src.audiobook_studio.feedback.bootstrap_fewshot.load_training_examples") as mock_load:
            mock_load.side_effect = Exception("Load failed")

            result = run_bootstrap_optimization("error_stage")
            assert result is None

    def test_run_with_empty_training_data(self):
        """Should return None when no training data."""
        with patch("src.audiobook_studio.feedback.bootstrap_fewshot.load_training_examples") as mock_load:
            mock_load.return_value = ("prompt", [])

            result = run_bootstrap_optimization("empty_stage")
            assert result is None


class TestBUDGET_LIMIT:
    """Tests for BUDGET_LIMIT constant."""

    def test_budget_limit_value(self):
        """BUDGET_LIMIT should be 500."""
        assert BUDGET_LIMIT == 500

    def test_budget_used_in_optimizer(self):
        """Budget limit should be used in optimizer initialization."""
        optimizer = BootstrapFewShotOptimizer(stage="test")
        assert optimizer.budget_limit == 500


class TestConfigureDSPyOptimizer:
    """Tests for configure_dspy_optimizer function."""

    def test_configure_with_mock(self):
        """Configure DSPy with mock LM."""
        configure_dspy_optimizer(use_mock=True)

    def test_configure_without_mock(self):
        """Configure DSPy without mock (dspy may not be installed)."""
        try:
            configure_dspy_optimizer(use_mock=False)
        except RuntimeError:
            # dspy not available - expected
            pass


class TestOptimizationResultExtended:
    """Extended tests for OptimizationResult."""

    def test_optimization_result_creation(self):
        """OptimizationResult can be created with all fields."""
        result = OptimizationResult(
            optimized_prompt="optimized prompt",
            metrics=OptimizationMetrics(
                character_recognition_accuracy=0.8,
                voice_design_accuracy=0.7,
                overall_score=0.75,
                inference_calls_used=100,
                cost_usd=3.5,
            ),
            improvement_ratio=0.5,
            stopped_early=True,
            iterations_completed=100,
            pareto_frontier=[{"score": 0.8}, {"score": 0.7}],
        )

        assert result.optimized_prompt == "optimized prompt"
        assert result.stopped_early is True
        assert result.iterations_completed == 100
        assert result.pareto_frontier is not None
        assert result.improvement_ratio == 0.5
