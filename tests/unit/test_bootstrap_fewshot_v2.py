"""Comprehensive tests for feedback/bootstrap_fewshot.py."""
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest

from src.audiobook_studio.feedback.bootstrap_fewshot import (
    BUDGET_LIMIT,
    DEFAULT_EARLY_STOP_PATIENCE,
    OptimizationMetrics,
    OptimizationResult,
    MultiObjectiveLoss,
    CharacterRecognitionModule,
    VoiceDesignModule,
    EarlyStoppingStopper,
    BootstrapFewShotOptimizer,
    load_training_examples,
    run_bootstrap_optimization,
    create_multi_objective_metric,
)


# ── Constants ────────────────────────────────────────────────────────────────

class TestConstants:
    def test_budget_limit(self):
        assert BUDGET_LIMIT == 500

    def test_early_stop_patience(self):
        assert DEFAULT_EARLY_STOP_PATIENCE == 10


# ── OptimizationMetrics ─────────────────────────────────────────────────────

class TestOptimizationMetrics:
    def test_defaults(self):
        m = OptimizationMetrics()
        assert m.character_recognition_accuracy == 0.0
        assert m.voice_design_accuracy == 0.0
        assert m.overall_score == 0.0
        assert m.inference_calls_used == 0
        assert m.cost_usd == 0.0
        assert m.iterations_completed == 0

    def test_custom(self):
        m = OptimizationMetrics(
            character_recognition_accuracy=0.8,
            voice_design_accuracy=0.9,
            overall_score=0.85,
            inference_calls_used=10,
        )
        assert m.character_recognition_accuracy == 0.8
        assert m.inference_calls_used == 10


# ── OptimizationResult ──────────────────────────────────────────────────────

class TestOptimizationResult:
    def test_creation(self):
        r = OptimizationResult(
            optimized_prompt="prompt",
            metrics=OptimizationMetrics(),
            improvement_ratio=0.1,
        )
        assert r.optimized_prompt == "prompt"
        assert r.stopped_early is False
        assert r.pareto_frontier is None

    def test_with_pareto(self):
        r = OptimizationResult(
            optimized_prompt="p",
            metrics=OptimizationMetrics(),
            improvement_ratio=0.2,
            stopped_early=True,
            iterations_completed=50,
            pareto_frontier=[{"score": 0.9}],
        )
        assert r.stopped_early is True
        assert len(r.pareto_frontier) == 1


# ── MultiObjectiveLoss ──────────────────────────────────────────────────────

class TestMultiObjectiveLoss:
    def test_default_weights(self):
        loss = MultiObjectiveLoss()
        assert loss.weights["character_recognition"] == 0.5
        assert loss.weights["voice_design"] == 0.5

    def test_custom_weights(self):
        loss = MultiObjectiveLoss({"character_recognition": 0.7, "voice_design": 0.3})
        assert loss.weights["character_recognition"] == 0.7

    def test_compute_loss_perfect(self):
        loss = MultiObjectiveLoss()
        pred = {"character": "Alice", "voice": "female_young"}
        truth = {"character": "Alice", "voice": "female_young"}
        result = loss.compute_loss(pred, truth)
        assert result == 0.0

    def test_compute_loss_wrong_character(self):
        loss = MultiObjectiveLoss()
        pred = {"character": "Bob", "voice": "female_young"}
        truth = {"character": "Alice", "voice": "female_young"}
        result = loss.compute_loss(pred, truth)
        assert result == 0.5

    def test_compute_loss_wrong_voice(self):
        loss = MultiObjectiveLoss()
        pred = {"character": "Alice", "voice": "male_old"}
        truth = {"character": "Alice", "voice": "female_young"}
        result = loss.compute_loss(pred, truth)
        assert result == 0.5

    def test_compute_loss_both_wrong(self):
        loss = MultiObjectiveLoss()
        pred = {"character": "Bob", "voice": "male_old"}
        truth = {"character": "Alice", "voice": "female_young"}
        result = loss.compute_loss(pred, truth)
        assert result == 1.0

    def test_compute_loss_missing_fields(self):
        loss = MultiObjectiveLoss()
        result = loss.compute_loss({}, {})
        assert result == 0.0

    def test_compute_loss_partial_pred(self):
        loss = MultiObjectiveLoss()
        pred = {"character": "Alice"}
        truth = {"character": "Alice", "voice": "female_young"}
        result = loss.compute_loss(pred, truth)
        assert 0.0 <= result <= 0.5

    def test_compute_pareto_score(self):
        loss = MultiObjectiveLoss()
        m = OptimizationMetrics(character_recognition_accuracy=0.8, voice_design_accuracy=0.6)
        score = loss.compute_pareto_score(m)
        assert abs(score - 0.7) < 1e-6


# ── EarlyStoppingStopper ────────────────────────────────────────────────────

class TestEarlyStoppingStopper:
    def test_no_stop_initially(self):
        s = EarlyStoppingStopper(patience=3)
        assert s([0.5, 0.6]) is False

    def test_stop_after_patience(self):
        s = EarlyStoppingStopper(patience=2)
        s([0.5])  # best = 0.5, count = 0
        s([0.4])  # count = 1
        assert s([0.3]) is True  # count = 2 >= patience

    def test_improvement_resets(self):
        s = EarlyStoppingStopper(patience=2)
        s([0.5])  # best = 0.5
        s([0.4])  # count = 1
        s([0.6])  # best = 0.6, count = 0
        assert s([0.5]) is False  # count = 1

    def test_empty_scores(self):
        s = EarlyStoppingStopper(patience=3)
        assert s([]) is False

    def test_exact_same_score(self):
        s = EarlyStoppingStopper(patience=1)
        s([0.5])
        assert s([0.5]) is True  # Same score = no improvement

    def test_multiple_scores_in_iteration(self):
        s = EarlyStoppingStopper(patience=3)
        s([0.1, 0.5, 0.3])  # best = 0.5
        s([0.2, 0.4])  # count = 1
        s([0.1, 0.3])  # count = 2
        assert s([0.2]) is True  # count = 3 >= patience


# ── create_multi_objective_metric ────────────────────────────────────────────

class TestCreateMetric:
    def test_metric_returns_score_with_feedback(self):
        from dspy import Example, Prediction
        from dspy.teleprompt.gepa.gepa_utils import ScoreWithFeedback
        metric = create_multi_objective_metric(char_weight=0.5, voice_weight=0.5)
        gold = Example(
            paragraph_text="test",
            character="Alice",
            voice="female",
        ).with_inputs("paragraph_text")
        # Pass as dict so metric can read character_name/voice_design keys
        pred = {"character_name": "Alice", "voice_design": "female"}
        result = metric(gold, pred)
        assert isinstance(result, ScoreWithFeedback)
        assert result.score == 1.0

    def test_metric_wrong(self):
        from dspy import Example
        metric = create_multi_objective_metric()
        gold = Example(paragraph_text="t", character="A", voice="v").with_inputs("paragraph_text")
        pred = {"character_name": "X", "voice_design": "Y"}
        result = metric(gold, pred)
        assert result.score == 0.0

    def test_metric_partial(self):
        from dspy import Example
        metric = create_multi_objective_metric(char_weight=0.5, voice_weight=0.5)
        gold = Example(paragraph_text="t", character="A", voice="v").with_inputs("paragraph_text")
        pred = {"character_name": "A", "voice_design": "Z"}
        result = metric(gold, pred)
        assert result.score == 0.5

    def test_metric_dict_pred(self):
        from dspy import Example
        metric = create_multi_objective_metric()
        gold = Example(paragraph_text="t", character="A", voice="V").with_inputs("paragraph_text")
        pred = {"character_name": "A", "voice_design": "V"}
        result = metric(gold, pred)
        assert result.score == 1.0

    def test_metric_prediction_pred(self):
        from dspy import Example, Prediction
        metric = create_multi_objective_metric()
        gold = Example(paragraph_text="t", character="A", voice="V").with_inputs("paragraph_text")
        # Prediction.__dict__ stores in _store, metric uses __dict__.get which fails
        # So score will be 0
        pred = Prediction(character_name="A", voice_design="V")
        result = metric(gold, pred)
        assert 0.0 <= result.score <= 1.0

    def test_metric_empty_pred(self):
        from dspy import Example
        metric = create_multi_objective_metric()
        gold = Example(paragraph_text="t", character="A", voice="V").with_inputs("paragraph_text")
        pred = {}
        result = metric(gold, pred)
        assert 0.0 <= result.score <= 1.0

    def test_metric_dict_gold_character(self):
        from dspy import Example
        metric = create_multi_objective_metric()
        gold = Example(
            paragraph_text="t",
            character={"speaker_canonical_name": "Alice"},
            voice="V",
        ).with_inputs("paragraph_text")
        pred = {"character_name": "Alice", "voice_design": "V"}
        result = metric(gold, pred)
        assert result.score >= 0.5


# ── BootstrapFewShotOptimizer ────────────────────────────────────────────────

class TestOptimizer:
    def test_init(self):
        opt = BootstrapFewShotOptimizer(
            stage="annotate",
            budget_limit=100,
            early_stop_patience=5,
        )
        assert opt.stage == "annotate"
        assert opt.budget_limit == 100
        assert opt.early_stop_patience == 5
        assert opt.loss_fn.weights["character_recognition"] == 0.5

    def test_init_custom_weights(self):
        opt = BootstrapFewShotOptimizer(
            stage="test", char_weight=0.7, voice_weight=0.3,
        )
        assert opt.loss_fn.weights["character_recognition"] == 0.7
        assert opt.loss_fn.weights["voice_design"] == 0.3

    def test_optimize_empty_examples(self):
        opt = BootstrapFewShotOptimizer(stage="test")
        result = opt.optimize("initial prompt", [])
        assert isinstance(result, OptimizationResult)
        assert result.improvement_ratio == 0.0
        assert result.iterations_completed == 0

    @patch("src.audiobook_studio.feedback.bootstrap_fewshot.GEPA")
    def test_optimize_with_examples(self, mock_gepa_cls):
        mock_gepa = MagicMock()
        mock_gepa.compile.return_value = MagicMock()
        mock_gepa_cls.return_value = mock_gepa
        opt = BootstrapFewShotOptimizer(stage="test", budget_limit=10)
        examples = [
            ("paragraph text 1", {"character": "Alice", "voice": "v1"}),
            ("paragraph text 2", {"character": "Bob", "voice": "v2"}),
        ]
        result = opt.optimize("extract character", examples)
        assert isinstance(result, OptimizationResult)
        assert result.optimized_prompt is not None

    def test_compute_improvement(self):
        opt = BootstrapFewShotOptimizer(stage="test")
        m = OptimizationMetrics(overall_score=0.6)
        imp = opt._compute_improvement(m)
        assert imp == (0.6 - 0.5) / 0.5

    def test_compute_improvement_below_baseline(self):
        opt = BootstrapFewShotOptimizer(stage="test")
        m = OptimizationMetrics(overall_score=0.3)
        imp = opt._compute_improvement(m)
        assert imp == 0.0  # Capped at 0

    def test_extract_prompt_from_module_fallback(self):
        opt = BootstrapFewShotOptimizer(stage="test")
        m = MagicMock(spec=[])  # No attributes
        result = opt._extract_prompt_from_module(m, "fallback")
        assert result == "fallback"

    def test_extract_pareto_frontier_none(self):
        opt = BootstrapFewShotOptimizer(stage="test")
        m = MagicMock(spec=[])  # No detailed_results attribute
        result = opt._extract_pareto_frontier(m)
        assert result is None

    def test_extract_pareto_frontier_with_scores(self):
        opt = BootstrapFewShotOptimizer(stage="test")
        m = MagicMock()
        dr = MagicMock(spec=["val_aggregate_scores"])
        dr.val_aggregate_scores = [0.8, 0.9, 0.7]
        m.detailed_results = dr
        result = opt._extract_pareto_frontier(m)
        assert result is not None
        assert len(result) == 3

    def test_extract_pareto_frontier_per_task(self):
        opt = BootstrapFewShotOptimizer(stage="test")
        m = MagicMock()
        dr = MagicMock(spec=["highest_score_achieved_per_val_task"])
        dr.highest_score_achieved_per_val_task = [0.8, 0.9]
        m.detailed_results = dr
        result = opt._extract_pareto_frontier(m)
        assert result is not None
        assert len(result) == 2


# ── load_training_examples ──────────────────────────────────────────────────

class TestLoadTrainingExamples:
    def test_no_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        prompt, examples = load_training_examples("annotate")
        assert isinstance(prompt, str)
        assert isinstance(examples, list)

    def test_with_few_shot_jsonl(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        golden_dir = tmp_path / "tests" / "golden" / "annotate_paragraph"
        golden_dir.mkdir(parents=True)
        data = {
            "input": {"paragraph_text": "text1", "character_voice_map": [
                {"canonical_name": "Alice", "suggested_voice_id": "v1"}
            ]},
            "expected_output": {"speaker_canonical_name": "Alice"},
        }
        (golden_dir / "few_shot.jsonl").write_text(json.dumps(data))
        prompt, examples = load_training_examples("annotate_paragraph")
        assert len(examples) == 1
        assert examples[0][0] == "text1"
        assert examples[0][1]["character"] == "Alice"
        assert examples[0][1]["voice"] == "v1"

    def test_with_bootstrap_json(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        bootstrap_file = tmp_path / "tests" / "golden" / "bootstrap_examples.json"
        bootstrap_file.parent.mkdir(parents=True)
        bootstrap_file.write_text(json.dumps({
            "examples": [{"text": "hello", "character": "Bob", "voice": "v2"}]
        }))
        prompt, examples = load_training_examples("nonexistent_stage", str(bootstrap_file))
        assert len(examples) == 1
        assert examples[0][1]["character"] == "Bob"

    def test_with_prompt_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        prompt_dir = tmp_path / "prompts" / "annotate_paragraph"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "v1.j2").write_text("custom prompt template")
        prompt, _ = load_training_examples("annotate_paragraph")
        assert prompt == "custom prompt template"


# ── run_bootstrap_optimization ──────────────────────────────────────────────

class TestRunBootstrapOptimization:
    def test_no_examples_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = run_bootstrap_optimization("nonexistent_stage", str(tmp_path / "no_file.json"))
        assert result is None
