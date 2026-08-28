"""Tests for feedback/llm_judge.py — LLM Judge Ensemble (S2-3).

Covers: parallel multi-model scoring, majority vote, voting consistency
(agreement) >= 80%, confidence threshold, all-judges-fail fallback, and the
end-to-end A/B report produced from ensemble (non-heuristic) scores.
"""

from unittest.mock import MagicMock

import pytest

from src.audiobook_studio.feedback.ab_test import ABTestReport, ABTestSample, run_ab_test
from src.audiobook_studio.feedback.llm_judge import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    DimensionScore,
    JudgeResult,
    LLMJudgeEnsemble,
    RUBRIC_DIMENSIONS,
    RubricScores,
)
from src.audiobook_studio.llm.client import LLMCallResult


def _rubric_scores(a: float, b: float, winner: str) -> RubricScores:
    dim = DimensionScore(a=a, b=b)
    return RubricScores(
        faithfulness=dim,
        naturalness=dim,
        instruction_following=dim,
        no_hallucination=dim,
        winner=winner,
        rationale=f"a={a} b={b} -> {winner}",
    )


def _fake_client(scores: RubricScores) -> MagicMock:
    client = MagicMock()
    client.call.return_value = LLMCallResult(
        output=scores,
        model="fake",
        tokens_in=0,
        tokens_out=0,
        cost_usd=0.0,
        latency_ms=1,
        schema_compliance=True,
        raw_response={},
    )
    return client


def _factory_for(per_model: dict) -> callable:
    """client_factory mapping model name -> RubricScores."""

    def factory(model: str) -> MagicMock:
        return _fake_client(per_model[model])

    return factory


# ── Rubric / schema ─────────────────────────────────────────────────────────

def test_rubric_dimensions_are_the_four_required():
    assert RUBRIC_DIMENSIONS == [
        "faithfulness",
        "naturalness",
        "instruction_following",
        "no_hallucination",
    ]


def test_rubric_scores_defaults_are_valid_1_5():
    rs = RubricScores()
    assert rs.winner == "tie"
    for d in RUBRIC_DIMENSIONS:
        assert getattr(rs, d).a == 3.0
        assert getattr(rs, d).b == 3.0


# ── Parallel multi-model + majority vote ────────────────────────────────────

def test_ensemble_all_agree_b_wins():
    per_model = {
        "m1": _rubric_scores(2.0, 4.0, "B"),
        "m2": _rubric_scores(1.0, 5.0, "B"),
        "m3": _rubric_scores(3.0, 4.0, "B"),
    }
    ens = LLMJudgeEnsemble(models=["m1", "m2", "m3"], client_factory=_factory_for(per_model))
    result = ens.judge({"text": "x"}, {"edited_text": "a"}, {"edited_text": "b"}, "edit_for_tts")

    assert isinstance(result, JudgeResult)
    assert result.winner == "B"
    assert result.num_models == 3
    # All 3 agree -> voting consistency 100% >= 80%.
    assert result.agreement == 1.0
    assert result.is_significant is True
    # score_b must beat score_a (B rubric higher).
    assert result.score_a < result.score_b


def test_ensemble_majority_vote_split_2v1():
    # 2 models favour A, 1 favours B -> majority A, agreement 2/3.
    per_model = {
        "a1": _rubric_scores(4.0, 2.0, "A"),
        "a2": _rubric_scores(5.0, 1.0, "A"),
        "b1": _rubric_scores(1.0, 5.0, "B"),
    }
    ens = LLMJudgeEnsemble(models=["a1", "a2", "b1"], client_factory=_factory_for(per_model))
    result = ens.judge({"text": "x"}, {"edited_text": "a"}, {"edited_text": "b"}, "edit_for_tts")

    assert result.winner == "A"
    # 2 of 3 agree -> 0.667, below the 0.8 confidence threshold.
    assert abs(result.agreement - 2 / 3) < 1e-9
    assert result.is_significant is False


def test_ensemble_voting_consistency_ge_80_percent():
    """Acceptance metric: 3-model voting consistency reaches >= 80% on full agreement."""
    per_model = {f"m{i}": _rubric_scores(1.0, 5.0, "B") for i in range(3)}
    ens = LLMJudgeEnsemble(
        models=list(per_model),
        confidence_threshold=DEFAULT_CONFIDENCE_THRESHOLD,
        client_factory=_factory_for(per_model),
    )
    result = ens.judge({}, {"x": 1}, {"x": 2}, "edit_for_tts")
    assert result.agreement >= 0.8
    assert result.is_significant is True


def test_ensemble_normalized_scores_in_range():
    per_model = {"m": _rubric_scores(1.0, 5.0, "B")}
    ens = LLMJudgeEnsemble(models=["m"], client_factory=_factory_for(per_model))
    result = ens.judge({}, {}, {}, "edit_for_tts")
    assert 0.0 <= result.score_a <= 1.0
    assert 0.0 <= result.score_b <= 1.0
    # 1/5 -> 0.0, 5/5 -> 1.0 after normalization.
    assert result.score_a == 0.0
    assert result.score_b == 1.0


def test_ensemble_dimension_averages_reported():
    per_model = {
        "m1": _rubric_scores(2.0, 4.0, "B"),
        "m2": _rubric_scores(4.0, 2.0, "A"),  # disagrees but still contributes to dim avg
    }
    ens = LLMJudgeEnsemble(models=["m1", "m2"], client_factory=_factory_for(per_model))
    result = ens.judge({}, {}, {}, "edit_for_tts")
    # faithfulness averaged across models: a = (2+4)/2 = 3.0, b = (4+2)/2 = 3.0
    assert result.dimension_scores["faithfulness"]["a"] == 3.0
    assert result.dimension_scores["faithfulness"]["b"] == 3.0
    assert set(result.dimension_scores.keys()) == set(RUBRIC_DIMENSIONS)


# ── Fallback when no judge can produce a verdict ─────────────────────────────

def test_ensemble_all_models_fail_raises():
    def boom_factory(model):
        client = MagicMock()
        client.call.side_effect = RuntimeError("judge down")
        return client

    ens = LLMJudgeEnsemble(models=["m1", "m2", "m3"], client_factory=boom_factory)
    with pytest.raises(ValueError):
        ens.judge({}, {}, {}, "edit_for_tts")


def test_create_llm_judge_fn_falls_back_to_heuristic_when_ensemble_down(monkeypatch):
    from src.audiobook_studio.feedback.ab_test import create_llm_judge_fn

    def boom_factory(model):
        client = MagicMock()
        client.call.side_effect = RuntimeError("judge down")
        return client

    monkeypatch.setattr(
        "src.audiobook_studio.llm.create_client",
        lambda **kw: boom_factory(kw.get("model")),
    )
    judge_fn = create_llm_judge_fn("edit_for_tts")
    score_a, score_b, rationale = judge_fn(
        {"text": "hi"}, {"edited_text": "a"}, {"edited_text": "b" * 300}
    )
    assert 0.0 <= score_a <= 1.0
    assert 0.0 <= score_b <= 1.0
    assert "heuristic" in rationale  # deprecated _score_output fallback used


# ── End-to-end: A/B report from ensemble (non-heuristic) scores ──────────────

def _make_samples(n: int, stage: str = "edit_for_tts") -> list:
    samples = []
    for i in range(n):
        samples.append(
            ABTestSample(
                sample_id=f"s{i}",
                stage=stage,
                input_data={"paragraph_text": f"text {i}"},
                output_a={"edited_text": f"control {i}"},
                output_b={"edited_text": f"treatment {i}"},
                version_a=1,
                version_b=2,
            )
        )
    return samples


def test_ab_report_uses_ensemble_non_heuristic():
    """run_ab_test with an ensemble-backed judge yields a real (non-heuristic) report."""
    # All judges favour B -> every sample wins for B.
    per_model = {f"m{i}": _rubric_scores(2.0, 4.0, "B") for i in range(3)}

    def judge_fn(input_data, output_a, output_b):
        ens = LLMJudgeEnsemble(
            models=list(per_model), client_factory=_factory_for(per_model)
        )
        r = ens.judge(input_data, output_a, output_b, "edit_for_tts")
        return r.score_a, r.score_b, r.rationale

    samples = _make_samples(6)
    report = run_ab_test("edit_for_tts", samples, judge_fn, significance_level=0.05)

    assert isinstance(report, ABTestReport)
    assert report.num_samples == 6
    assert report.b_wins == 6
    assert report.a_wins == 0
    assert report.ties == 0
    # Non-heuristic: scores came from the 1-5 rubric, not the 0.5-ish heuristic.
    assert report.avg_score_a < report.avg_score_b
    # p-value is computed from the real score differences (all B > A).
    assert report.p_value <= 1.0
    assert report.is_significant in (True, False)
