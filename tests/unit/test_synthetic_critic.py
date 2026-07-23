"""
Tests for SyntheticCritic triad architecture (Issue 2.1).

Verifies:
1. Three heterogeneous critics (semantic/structural/objective) exist
2. Calibration dataset with ground truth labels
3. Weighted voting ensemble fusion
4. F1 score >= 0.7 on calibration set
5. Adaptive weight optimization
6. Mock mode evaluation
7. Serialization (to_dict / from_dict)
"""

import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from audiobook_studio.feedback.critics.base import (
    BaseCritic,
    CriticEnsemble,
    CriticEnsembleEvaluator,
    CriticResult,
    CriticType,
    CriticVerdict,
)
from audiobook_studio.feedback.critics.synthetic_critic import (
    DEFAULT_CALIBRATION_SAMPLES,
    CalibrationResult,
    CalibrationSample,
    SyntheticCritic,
    _compute_confusion_matrix,
    _compute_f1_per_class,
    create_synthetic_critic,
)

# Ensure src is on path


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def critic():
    """SyntheticCritic in mock mode."""
    return create_synthetic_critic(mock_mode=True)


@pytest.fixture
def custom_samples():
    """Small custom calibration dataset for deterministic tests."""
    return [
        CalibrationSample(
            sample_id="t_pass",
            description="Test pass",
            semantic_score=0.85,
            structural_score=0.80,
            objective_score=0.90,
            ground_truth_verdict=CriticVerdict.PASS,
            ground_truth_score=0.85,
        ),
        CalibrationSample(
            sample_id="t_warn",
            description="Test warning",
            semantic_score=0.65,
            structural_score=0.58,
            objective_score=0.75,
            ground_truth_verdict=CriticVerdict.WARNING,
            ground_truth_score=0.65,
        ),
        CalibrationSample(
            sample_id="t_fail",
            description="Test fail",
            semantic_score=0.25,
            structural_score=0.30,
            objective_score=0.30,
            ground_truth_verdict=CriticVerdict.FAIL,
            ground_truth_score=0.28,
        ),
    ]


# ═══════════════════════════════════════════════════════════════════════════
# 1. Architecture tests — three heterogeneous critics
# ═══════════════════════════════════════════════════════════════════════════


class TestTriadArchitecture:
    """Verify the three heterogeneous critics architecture."""

    def test_critic_types_exist(self):
        """Three critic types: SEMANTIC, STRUCTURAL, OBJECTIVE."""
        assert CriticType.SEMANTIC.value == "semantic"
        assert CriticType.STRUCTURAL.value == "structural"
        assert CriticType.OBJECTIVE.value == "objective"

    def test_critic_verdicts_exist(self):
        """Four verdict types: PASS, WARNING, FAIL, ABSTAIN."""
        assert CriticVerdict.PASS.value == "pass"
        assert CriticVerdict.WARNING.value == "warning"
        assert CriticVerdict.FAIL.value == "fail"
        assert CriticVerdict.ABSTAIN.value == "abstain"

    def test_synthetic_critic_has_three_weights(self, critic):
        """SyntheticCritic maintains separate weights for all three types."""
        weights = critic.get_weights()
        assert "semantic" in weights
        assert "structural" in weights
        assert "objective" in weights
        assert abs(sum(weights.values()) - 1.0) < 0.01

    def test_default_weights_objective_highest(self, critic):
        """Objective critic has highest default weight (hard metrics most reliable)."""
        weights = critic.get_weights()
        assert weights["objective"] >= weights["semantic"]
        assert weights["objective"] >= weights["structural"]

    def test_ensemble_evaluator_fuses_three(self):
        """CriticEnsembleEvaluator fuses results from three critics."""
        results = [
            CriticResult(
                critic_type=CriticType.SEMANTIC,
                verdict=CriticVerdict.PASS,
                score=0.85,
                confidence=0.8,
                reasoning="test",
                evidence={},
                tags=[],
            ),
            CriticResult(
                critic_type=CriticType.STRUCTURAL,
                verdict=CriticVerdict.WARNING,
                score=0.65,
                confidence=0.7,
                reasoning="test",
                evidence={},
                tags=[],
            ),
            CriticResult(
                critic_type=CriticType.OBJECTIVE,
                verdict=CriticVerdict.PASS,
                score=0.90,
                confidence=0.9,
                reasoning="test",
                evidence={},
                tags=[],
            ),
        ]
        evaluator = CriticEnsembleEvaluator(
            weights={
                CriticType.SEMANTIC: 0.3,
                CriticType.STRUCTURAL: 0.2,
                CriticType.OBJECTIVE: 0.5,
            }
        )
        ensemble = evaluator._fuse_results(results)
        # Scores: 0.85*0.3 + 0.65*0.2 + 0.90*0.5 = 0.835
        # With WARNING present, the fusion logic returns WARNING
        assert ensemble.final_verdict in (CriticVerdict.PASS, CriticVerdict.WARNING)
        assert len(ensemble.results) == 3


# ═══════════════════════════════════════════════════════════════════════════
# 2. Calibration dataset tests
# ═══════════════════════════════════════════════════════════════════════════


class TestCalibrationDataset:
    """Verify calibration dataset structure and coverage."""

    def test_default_samples_exist(self):
        """Default calibration samples are loaded."""
        assert len(DEFAULT_CALIBRATION_SAMPLES) == 20

    def test_samples_cover_all_verdicts(self):
        """Dataset includes PASS, WARNING, and FAIL samples."""
        verdicts = {s.ground_truth_verdict for s in DEFAULT_CALIBRATION_SAMPLES}
        assert CriticVerdict.PASS in verdicts
        assert CriticVerdict.WARNING in verdicts
        assert CriticVerdict.FAIL in verdicts

    def test_samples_have_triple_scores(self):
        """Each sample has scores for all three critics."""
        for sample in DEFAULT_CALIBRATION_SAMPLES:
            assert 0.0 <= sample.semantic_score <= 1.0
            assert 0.0 <= sample.structural_score <= 1.0
            assert 0.0 <= sample.objective_score <= 1.0

    def test_custom_calibration_samples(self, critic, custom_samples):
        """Can use custom calibration samples."""
        result = critic.calibrate(samples=custom_samples)
        assert result.total_samples == 3

    def test_sample_dataclass_fields(self):
        """CalibrationSample has all required fields."""
        sample = CalibrationSample(
            sample_id="test",
            description="test",
            semantic_score=0.8,
            structural_score=0.7,
            objective_score=0.9,
            ground_truth_verdict=CriticVerdict.PASS,
            ground_truth_score=0.8,
        )
        assert sample.sample_id == "test"
        assert sample.category == "general"
        assert sample.difficulty == "medium"


# ═══════════════════════════════════════════════════════════════════════════
# 3. F1 score verification (central acceptance criterion)
# ═══════════════════════════════════════════════════════════════════════════


class TestF1ScoreAcceptance:
    """Verify F1 >= 0.7 on calibration set (acceptance criterion)."""

    def test_f1_macro_at_least_0_7(self, critic):
        """F1 macro on default calibration set >= 0.7."""
        result = critic.calibrate()
        assert result.f1_macro >= 0.7, (
            f"F1 macro {result.f1_macro} < 0.7 threshold. " f"Per-class: {result.f1_per_class}"
        )

    def test_f1_per_class_all_positive(self, critic):
        """F1 for each class is > 0 (no class is completely missed)."""
        result = critic.calibrate()
        for label, f1 in result.f1_per_class.items():
            assert f1 > 0, f"F1 for class '{label}' is 0"

    def test_calibration_result_passed_flag(self, critic):
        """CalibrationResult.passed is True when F1 >= 0.7."""
        result = critic.calibrate()
        assert result.passed is True

    def test_calibration_result_fields(self, critic):
        """CalibrationResult has all expected fields."""
        result = critic.calibrate()
        assert hasattr(result, "f1_macro")
        assert hasattr(result, "f1_per_class")
        assert hasattr(result, "precision_macro")
        assert hasattr(result, "recall_macro")
        assert hasattr(result, "accuracy")
        assert hasattr(result, "total_samples")
        assert hasattr(result, "predictions")
        assert hasattr(result, "confusion_matrix")
        assert hasattr(result, "weights")
        assert hasattr(result, "passed")

    def test_confusion_matrix_structure(self, critic):
        """Confusion matrix has all three labels."""
        result = critic.calibrate()
        labels = ["pass", "warning", "fail"]
        for row in labels:
            assert row in result.confusion_matrix
            for col in labels:
                assert col in result.confusion_matrix[row]

    def test_accuracy_matches_predictions(self, critic):
        """Accuracy equals correct predictions / total."""
        result = critic.calibrate()
        correct = sum(1 for p in result.predictions if p["correct"])
        expected_accuracy = round(correct / result.total_samples, 4)
        assert result.accuracy == expected_accuracy


# ═══════════════════════════════════════════════════════════════════════════
# 4. Adaptive weight optimization
# ═══════════════════════════════════════════════════════════════════════════


class TestAdaptiveWeights:
    """Verify adaptive weight optimization improves F1."""

    def test_adaptive_f1_geq_default(self, critic):
        """Adaptive calibration F1 >= default calibration F1."""
        default_result = critic.calibrate()
        adaptive_result = critic.calibrate_with_adaptive_weights(n_iterations=10)
        assert adaptive_result.f1_macro >= default_result.f1_macro - 0.01

    def test_adaptive_weights_preserved(self, critic):
        """After adaptive calibration, best weights are applied."""
        critic.calibrate_with_adaptive_weights(n_iterations=5)
        weights = critic.get_weights()
        assert abs(sum(weights.values()) - 1.0) < 0.02

    def test_adaptive_with_custom_samples(self, critic, custom_samples):
        """Adaptive calibration works with custom samples."""
        result = critic.calibrate_with_adaptive_weights(samples=custom_samples, n_iterations=5)
        assert result.total_samples == 3
        assert result.f1_macro > 0


# ═══════════════════════════════════════════════════════════════════════════
# 5. Mock mode evaluation
# ═══════════════════════════════════════════════════════════════════════════


class TestMockEvaluation:
    """Verify mock mode evaluation path."""

    def test_mock_evaluation_returns_ensemble(self, critic):
        """run_mock_evaluation returns a CriticEnsemble."""
        ensemble = critic.run_mock_evaluation()
        assert isinstance(ensemble, CriticEnsemble)
        assert len(ensemble.results) == 3

    def test_mock_has_three_critic_types(self, critic):
        """Mock results cover all three critic types."""
        ensemble = critic.run_mock_evaluation()
        types = {r.critic_type for r in ensemble.results}
        assert CriticType.SEMANTIC in types
        assert CriticType.STRUCTURAL in types
        assert CriticType.OBJECTIVE in types

    def test_mock_scores_in_range(self, critic):
        """All mock scores are 0-1."""
        ensemble = critic.run_mock_evaluation()
        for r in ensemble.results:
            assert 0.0 <= r.score <= 1.0
            assert 0.0 <= r.confidence <= 1.0


# ═══════════════════════════════════════════════════════════════════════════
# 6. Weight management
# ═══════════════════════════════════════════════════════════════════════════


class TestWeightManagement:
    """Verify weight setting and normalization."""

    def test_set_weights_normalizes(self, critic):
        """Weights are normalized when set to non-unit sum."""
        critic.set_weights(
            {
                CriticType.SEMANTIC: 2.0,
                CriticType.STRUCTURAL: 2.0,
                CriticType.OBJECTIVE: 6.0,
            }
        )
        weights = critic.get_weights()
        assert abs(sum(weights.values()) - 1.0) < 0.01

    def test_set_weights_preserves_ratio(self, critic):
        """Normalization preserves weight ratios."""
        critic.set_weights(
            {
                CriticType.SEMANTIC: 1.0,
                CriticType.STRUCTURAL: 1.0,
                CriticType.OBJECTIVE: 3.0,
            }
        )
        weights = critic.get_weights()
        assert abs(weights["objective"] - 0.6) < 0.01
        assert abs(weights["semantic"] - 0.2) < 0.01


# ═══════════════════════════════════════════════════════════════════════════
# 7. Serialization
# ═══════════════════════════════════════════════════════════════════════════


class TestSerialization:
    """Verify serialization of results."""

    def test_critic_result_to_dict(self):
        """CriticResult serializes to dict."""
        result = CriticResult(
            critic_type=CriticType.SEMANTIC,
            verdict=CriticVerdict.PASS,
            score=0.85,
            confidence=0.9,
            reasoning="test",
            evidence={"a": 1},
            tags=["t1"],
        )
        d = result.to_dict()
        assert d["critic_type"] == "semantic"
        assert d["verdict"] == "pass"
        assert d["score"] == 0.85

    def test_critic_result_from_dict(self):
        """CriticResult deserializes from dict."""
        data = {
            "critic_type": "structural",
            "verdict": "warning",
            "score": 0.65,
            "confidence": 0.7,
            "reasoning": "test",
            "evidence": {},
            "tags": [],
        }
        result = CriticResult.from_dict(data)
        assert result.critic_type == CriticType.STRUCTURAL
        assert result.verdict == CriticVerdict.WARNING

    def test_calibration_result_to_dict(self, critic):
        """CalibrationResult serializes to dict."""
        result = critic.calibrate()
        d = result.to_dict()
        assert "f1_macro" in d
        assert "f1_per_class" in d
        assert "passed" in d
        assert d["f1_macro"] >= 0.7

    def test_ensemble_to_dict(self, critic):
        """CriticEnsemble serializes to dict."""
        ensemble = critic.run_mock_evaluation()
        d = ensemble.to_dict()
        assert "results" in d
        assert "final_verdict" in d
        assert "final_score" in d


# ═══════════════════════════════════════════════════════════════════════════
# 8. Score-to-verdict mapping
# ═══════════════════════════════════════════════════════════════════════════


class TestScoreToVerdict:
    """Verify score-to-verdict mapping logic."""

    def test_high_score_pass(self, critic):
        """score >= 0.7 maps to PASS."""
        assert critic._score_to_verdict(0.8) == CriticVerdict.PASS
        assert critic._score_to_verdict(0.7) == CriticVerdict.PASS

    def test_medium_score_warning(self, critic):
        """0.5 <= score < 0.7 maps to WARNING."""
        assert critic._score_to_verdict(0.6) == CriticVerdict.WARNING
        assert critic._score_to_verdict(0.5) == CriticVerdict.WARNING

    def test_low_score_fail(self, critic):
        """score < 0.5 maps to FAIL."""
        assert critic._score_to_verdict(0.4) == CriticVerdict.FAIL
        assert critic._score_to_verdict(0.0) == CriticVerdict.FAIL


# ═══════════════════════════════════════════════════════════════════════════
# 9. Helper function tests
# ═══════════════════════════════════════════════════════════════════════════


class TestHelperFunctions:
    """Test internal helper functions."""

    def test_confusion_matrix(self):
        """_compute_confusion_matrix produces correct counts."""
        y_true = ["pass", "fail", "warning", "pass"]
        y_pred = ["pass", "fail", "pass", "warning"]
        labels = ["pass", "warning", "fail"]
        matrix = _compute_confusion_matrix(y_true, y_pred, labels)
        assert matrix["pass"]["pass"] == 1
        assert matrix["pass"]["warning"] == 1
        assert matrix["fail"]["fail"] == 1
        assert matrix["warning"]["pass"] == 1

    def test_f1_per_class(self):
        """_compute_f1_per_class computes correct F1 scores."""
        # Perfect predictions → F1 = 1.0 for all
        matrix = {
            "pass": {"pass": 3, "warning": 0, "fail": 0},
            "warning": {"pass": 0, "warning": 2, "fail": 0},
            "fail": {"pass": 0, "warning": 0, "fail": 1},
        }
        f1 = _compute_f1_per_class(matrix, ["pass", "warning", "fail"])
        assert f1["pass"] == 1.0
        assert f1["warning"] == 1.0
        assert f1["fail"] == 1.0

    def test_f1_all_wrong(self):
        """F1 = 0 when all predictions are wrong."""
        matrix = {
            "pass": {"pass": 0, "warning": 2, "fail": 0},
            "warning": {"pass": 0, "warning": 0, "fail": 2},
            "fail": {"pass": 1, "warning": 0, "fail": 0},
        }
        f1 = _compute_f1_per_class(matrix, ["pass", "warning", "fail"])
        assert f1["pass"] == 0.0
        assert f1["warning"] == 0.0
        assert f1["fail"] == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# 10. Factory function tests
# ═══════════════════════════════════════════════════════════════════════════


class TestFactoryFunction:
    """Verify create_synthetic_critic factory."""

    def test_create_mock_mode(self):
        """Factory creates critic in mock mode."""
        critic = create_synthetic_critic(mock_mode=True)
        assert critic.mock_mode is True

    def test_create_with_custom_weights(self):
        """Factory respects custom weights."""
        weights = {
            CriticType.SEMANTIC: 0.4,
            CriticType.STRUCTURAL: 0.1,
            CriticType.OBJECTIVE: 0.5,
        }
        critic = create_synthetic_critic(mock_mode=True, weights=weights)
        assert critic.get_weights()["semantic"] == 0.4

    def test_create_with_custom_thresholds(self):
        """Factory respects custom thresholds."""
        critic = create_synthetic_critic(
            mock_mode=True,
            pass_threshold=0.8,
            warning_threshold=0.6,
        )
        assert critic.pass_threshold == 0.8
        assert critic.warning_threshold == 0.6


# ═══════════════════════════════════════════════════════════════════════════
# 11. Ensemble fusion edge cases
# ═══════════════════════════════════════════════════════════════════════════


class TestEnsembleEdgeCases:
    """Test edge cases in ensemble fusion."""

    def test_no_critics_abstain(self):
        """Empty critics → ABSTAIN verdict."""
        evaluator = CriticEnsembleEvaluator(
            semantic_critic=None,
            structural_critic=None,
            objective_critic=None,
        )
        ensemble = evaluator.evaluate(Path("x"), None, None, "text")
        assert ensemble.final_verdict == CriticVerdict.ABSTAIN

    def test_single_fail_overrides(self):
        """Even one FAIL with low overall score can produce FAIL final verdict."""
        results = [
            CriticResult(
                critic_type=CriticType.SEMANTIC,
                verdict=CriticVerdict.FAIL,
                score=0.3,
                confidence=0.8,
                reasoning="test",
                evidence={},
                tags=[],
            ),
            CriticResult(
                critic_type=CriticType.STRUCTURAL,
                verdict=CriticVerdict.PASS,
                score=0.8,
                confidence=0.7,
                reasoning="test",
                evidence={},
                tags=[],
            ),
            CriticResult(
                critic_type=CriticType.OBJECTIVE,
                verdict=CriticVerdict.PASS,
                score=0.75,
                confidence=0.9,
                reasoning="test",
                evidence={},
                tags=[],
            ),
        ]
        evaluator = CriticEnsembleEvaluator(
            weights={
                CriticType.SEMANTIC: 0.3,
                CriticType.STRUCTURAL: 0.2,
                CriticType.OBJECTIVE: 0.5,
            }
        )
        ensemble = evaluator._fuse_results(results)
        # Verdict should reflect that there's at least one FAIL
        assert ensemble.final_verdict in (CriticVerdict.WARNING, CriticVerdict.FAIL)

    def test_all_pass_gives_pass(self):
        """All PASS → final PASS."""
        results = [
            CriticResult(
                critic_type=CriticType.SEMANTIC,
                verdict=CriticVerdict.PASS,
                score=0.85,
                confidence=0.8,
                reasoning="test",
                evidence={},
                tags=[],
            ),
            CriticResult(
                critic_type=CriticType.STRUCTURAL,
                verdict=CriticVerdict.PASS,
                score=0.80,
                confidence=0.7,
                reasoning="test",
                evidence={},
                tags=[],
            ),
            CriticResult(
                critic_type=CriticType.OBJECTIVE,
                verdict=CriticVerdict.PASS,
                score=0.90,
                confidence=0.9,
                reasoning="test",
                evidence={},
                tags=[],
            ),
        ]
        evaluator = CriticEnsembleEvaluator(
            weights={
                CriticType.SEMANTIC: 0.3,
                CriticType.STRUCTURAL: 0.2,
                CriticType.OBJECTIVE: 0.5,
            }
        )
        ensemble = evaluator._fuse_results(results)
        assert ensemble.final_verdict == CriticVerdict.PASS
        assert ensemble.final_score >= 0.7
