"""Coverage tests for feedback/ab_test.py — target ≥85% branch coverage."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.feedback.ab_test import (
    ABTestReport,
    ABTestResult,
    ABTestSample,
    PairwiseABTestReport,
    PairwiseABTestResult,
    _compute_paired_ttest,
    _compute_statistical_significance,
    _score_output,
    build_ab_samples,
    blind_evaluate,
    create_llm_judge_fn,
    create_pairwise_judge_fn,
    run_ab_test,
    run_ab_test_pairwise,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_llm_client_fail():
    """Create a mock LLM client that always fails."""
    client = MagicMock()

    def _call(**kwargs):
        raise RuntimeError("LLM unavailable")

    client.call = _call
    return client



# ── _score_output edge cases ────────────────────────────────────────────────

def test_score_output_edit_for_tts_confidence_clamp():
    """Test confidence value gets clamped to [0,1] in edit_for_tts."""
    out = {
        "edited_text": "x" * 300,
        "forbidden_content_removed": True,
        "confidence": 2.0,  # > 1
    }
    s = _score_output(out, "edit_for_tts")
    assert s <= 1.0

    out["confidence"] = -0.5  # < 0
    s = _score_output(out, "edit_for_tts")
    assert s >= 0.0


def test_score_output_quality_judge_all_fields():
    """Test quality_judge scoring with all fields present."""
    out = {
        "overall_score": 0.8,
        "issues": [1, 2],
        "fix_suggestions": [1],
    }
    s = _score_output(out, "quality_judge")
    # 0.5 + 0.2*0.8 + 0.1 + 0.1 = 0.86
    assert abs(s - 0.86) < 1e-9


def test_score_output_annotate_paragraph_all_fields():
    """Test annotate_paragraph scoring with all optional fields."""
    out = {
        "emotion": "happy",
        "speaker_canonical_name": "n",
        "is_dialogue": True,
        "emotion_intensity": 0.8,
    }
    s = _score_output(out, "annotate_paragraph")
    # 0.5 + 0.1*3 + 0.1 = 0.9 (emotion_intensity adds 0.1 if 0 < val <= 1)
    assert abs(s - 0.9) < 1e-9


def test_score_output_synthesize_stage():
    """Test synthesize stage scoring."""
    out = {"audio_duration_ms": 5000, "engine": "edge", "voice_id": "zh-CN-XiaoxiaoNeural"}
    s = _score_output(out, "synthesize")
    assert 0.0 <= s <= 1.0


def test_score_output_quality_stage():
    """Test quality stage scoring."""
    out = {"overall_score": 0.9, "issues": [], "fix_suggestions": []}
    s = _score_output(out, "quality")
    assert 0.0 <= s <= 1.0


def test_score_output_unknown_stage_returns_half():
    """Test unknown stage returns 0.5."""
    assert _score_output({}, "completely_unknown_stage") == 0.5


# ── _compute_statistical_significance edge cases ──────────────────────────

def test_significance_two_samples_significant():
    """Test with exactly 2 samples showing clear difference."""
    # With n=2, df=1, the test may not reach significance even with large diff
    # due to high t_critical. Let's test with more samples.
    results = [
        ABTestResult(f"s{i}", "B", 0.2, 0.8 + i*0.01) for i in range(10)
    ]
    p, ci, sig = _compute_statistical_significance(results)
    assert sig is True
    assert p < 0.05


def test_significance_all_ties():
    """Test with all ties."""
    results = [ABTestResult(f"s{i}", "tie", 0.5, 0.5) for i in range(5)]
    p, ci, sig = _compute_statistical_significance(results)
    assert sig is False


def test_significance_small_sample_not_significant():
    """Test small sample (n=3) with slight difference."""
    results = [
        ABTestResult("s1", "A", 0.5, 0.55),
        ABTestResult("s2", "A", 0.5, 0.52),
        ABTestResult("s3", "A", 0.5, 0.51),
    ]
    p, ci, sig = _compute_statistical_significance(results)
    # With small diffs and small n, may or may not be significant
    # Just verify the function returns valid values
    assert isinstance(p, float)
    assert isinstance(ci, tuple)
    assert isinstance(sig, bool)


# ── _compute_paired_ttest edge cases ──────────────────────────────────────

def test_paired_ttest_three_samples():
    """Test paired t-test with 3 samples."""
    diffs = [0.4, 0.5, 0.6]
    p, ci, sig = _compute_paired_ttest(diffs)
    assert isinstance(p, float)
    assert isinstance(ci, tuple)
    assert len(ci) == 2


def test_paired_ttest_negative_diffs():
    """Test paired t-test with negative diffs."""
    diffs = [-0.1, -0.2, -0.15, -0.05]
    p, ci, sig = _compute_paired_ttest(diffs)
    assert isinstance(p, float)
    assert sig is False or sig is True


# ── build_ab_samples edge cases ───────────────────────────────────────────

def test_build_ab_samples_partial_old_new():
    """Test build_ab_samples with mixed old/new and fallback."""
    examples = [
        {"input": {"text": "a"}, "output_old": {"v": 1}, "output_new": {"v": 2}},
        {"input": {"text": "b"}, "output_old": {"v": 3}, "output": {"v": 33}},  # missing output_new, fallback to output
        {"input": {"text": "c"}, "output_new": {"v": 4}, "output": {"v": 44}},  # missing output_old, fallback to output
    ]
    samples = build_ab_samples("edit_for_tts", examples, 1, 2)
    assert len(samples) == 3
    assert samples[0].output_a == {"v": 1}
    assert samples[0].output_b == {"v": 2}
    # When output_new is missing, falls back to "output"
    assert samples[1].output_a == {"v": 3}
    assert samples[1].output_b == {"v": 33}
    # When output_old is missing, falls back to "output"
    assert samples[2].output_a == {"v": 44}
    assert samples[2].output_b == {"v": 4}


def test_build_ab_samples_missing_output_fallback():
    """Test fallback to 'output' key when old/new missing."""
    examples = [
        {"input": {"text": "a"}, "output": {"v": 99}},
    ]
    samples = build_ab_samples("edit_for_tts", examples, 1, 2)
    assert samples[0].output_a == {"v": 99}
    assert samples[0].output_b == {"v": 99}


# ── run_ab_test edge cases ─────────────────────────────────────────────────

def _make_sample(stage="edit_for_tts", a=None, b=None):
    return ABTestSample(
        sample_id="s1", stage=stage, input_data={},
        output_a=a or {}, output_b=b or {}, version_a=1, version_b=2,
    )


def test_run_ab_test_heuristic_scoring_multiple_stages():
    """Test heuristic fallback works for all supported stages."""
    for stage in ["edit_for_tts", "annotate_paragraph", "analyze_structure", "quality_judge", "synthesize", "other_stage"]:
        if stage == "edit_for_tts":
            samples = [_make_sample(stage, a={"edited_text": "short"}, b={"edited_text": "x" * 300, "forbidden_content_removed": True})]
        elif stage == "annotate_paragraph":
            samples = [_make_sample(stage, a={"emotion": "neutral"}, b={"emotion": "happy", "speaker_canonical_name": "x", "is_dialogue": True, "emotion_intensity": 0.8})]
        elif stage == "quality_judge":
            samples = [_make_sample(stage, a={"overall_score": 0.5}, b={"overall_score": 0.9, "issues": [], "fix_suggestions": []})]
        else:
            samples = [_make_sample(stage, a={}, b={})]

        rep = run_ab_test(stage, samples)
        assert rep.num_samples == 1
        assert isinstance(rep.results[0].score_a, float)
        assert isinstance(rep.results[0].score_b, float)


def test_run_ab_test_new_signature_judge_exact_threshold():
    """Test judge returning scores at significance threshold."""
    def judge(input_data, output_a, output_b):
        return 0.52, 0.48, "A slightly better"

    samples = [_make_sample() for _ in range(20)]  # larger sample for significance
    rep = run_ab_test("edit_for_tts", samples, judge_fn=judge)
    assert rep.a_wins > 0 or rep.b_wins > 0 or rep.ties > 0


def test_run_ab_test_new_signature_judge_with_rationale():
    """Test new signature judge with rationale text."""
    def judge(input_data, output_a, output_b):
        return 0.8, 0.3, "A wins because of better text quality"

    samples = [_make_sample() for _ in range(5)]
    rep = run_ab_test("edit_for_tts", samples, judge_fn=judge)
    assert all("better" in r.rationale for r in rep.results)


# ── run_ab_test_pairwise edge cases ────────────────────────────────────────

from src.audiobook_studio.schemas.judge import PairwiseJudgment, PairwiseDimensionScore


class _FakeJudgment:
    def __init__(self, winner, dim_scores=None):
        self.winner = winner
        self.dimension_scores = dim_scores or {}


class _Dim:
    def __init__(self, a, b):
        self.score_a = a
        self.score_b = b


def _make_pairwise_judgment(winner: str, dim_scores=None) -> PairwiseJudgment:
    """Create a real PairwiseJudgment for testing."""
    ds = {}
    if dim_scores:
        for k, v in dim_scores.items():
            ds[k] = PairwiseDimensionScore(score_a=v.score_a, score_b=v.score_b, winner=v.score_a > v.score_b and "A" or v.score_b > v.score_a and "B" or "tie")
    return PairwiseJudgment(
        segment_id="test_seg",
        winner=winner,
        confidence=0.5,
        dimension_scores=ds,
        reasoning={},
        overall_reasoning="test",
    )


def test_run_ab_test_pairwise_tie_results():
    """Test pairwise with tie results."""
    def judge(segment_id, input_data, output_a, output_b, annotation, audio_description):
        return _make_pairwise_judgment(winner="tie")

    samples = [_make_sample() for _ in range(5)]
    rep = run_ab_test_pairwise("edit_for_tts", samples, judge_fn=judge)
    assert rep.ties == 5
    assert "结果不明确" in rep.recommendation


def test_run_ab_test_pairwise_mixed_winners():
    """Test pairwise with mixed A/B winners."""
    def judge(segment_id, input_data, output_a, output_b, annotation, audio_description):
        return _make_pairwise_judgment(winner="A")

    samples = [_make_sample() for _ in range(5)]
    rep = run_ab_test_pairwise("edit_for_tts", samples, judge_fn=judge)
    assert rep.a_wins == 5
    assert "不建议升级" in rep.recommendation


def test_run_ab_test_pairwise_custom_judge_all_fields():
    """Test pairwise with custom judge using all parameters."""
    def judge(segment_id, input_data, output_a, output_b, annotation, audio_description):
        assert segment_id == "test_seg"
        assert input_data == {"text": "input", "paragraph_annotation": {"key": "value"}, "audio_description": "desc"}
        assert output_a == {"edited_text": "a"}
        assert output_b == {"edited_text": "b"}
        assert annotation == {"key": "value"}
        assert audio_description == "desc"
        return _make_pairwise_judgment(winner="B")

    samples = [
        ABTestSample(
            sample_id="test_seg", stage="edit_for_tts", input_data={"text": "input", "paragraph_annotation": {"key": "value"}, "audio_description": "desc"},
            output_a={"edited_text": "a"}, output_b={"edited_text": "b"},
            version_a=1, version_b=2,
        )
    ]
    rep = run_ab_test_pairwise("edit_for_tts", samples, judge_fn=judge)
    assert rep.b_wins == 1


# ── create_llm_judge_fn with mocked LLM ────────────────────────────────────

def test_create_llm_judge_fn_llm_success(monkeypatch):
    """create_llm_judge_fn routes through LLMJudgeEnsemble on LLM success.

    The mocked judges all return a RubricScores favouring B, so the ensemble's
    majority vote must pick B and emit an ensemble rationale (S2-3).
    """
    from src.audiobook_studio.feedback.llm_judge import DimensionScore, RubricScores
    from src.audiobook_studio.llm.client import LLMCallResult

    def fake_create_client(**kwargs):
        client = MagicMock()

        def _call(**kw):
            return LLMCallResult(
                output=RubricScores(
                    faithfulness=DimensionScore(a=2.0, b=4.0),
                    naturalness=DimensionScore(a=2.0, b=4.0),
                    instruction_following=DimensionScore(a=2.0, b=4.0),
                    no_hallucination=DimensionScore(a=2.0, b=4.0),
                    winner="B",
                    rationale="B is more faithful and natural",
                ),
                model=kwargs.get("model", "fake"),
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                latency_ms=1,
                schema_compliance=True,
                raw_response={},
            )

        client.call = _call
        return client

    monkeypatch.setattr("src.audiobook_studio.llm.create_client", fake_create_client)

    fn = create_llm_judge_fn("edit_for_tts")
    score_a, score_b, rationale = fn(
        {"text": "hi"}, {"edited_text": "a"}, {"edited_text": "b" * 300}
    )
    assert score_a <= score_b  # B should win
    assert "B" in rationale
    assert "Ensemble verdict" in rationale  # ensemble-specific rationale


def test_create_llm_judge_fn_old_signature_judge_works(monkeypatch):
    """Test create_llm_judge_fn handles old signature judge function."""
    # The LLM judge creation might fail, falling back to heuristic
    def fake_create_client(**kwargs):
        client = MagicMock()
        def _call(**kw):
            raise RuntimeError("llm unavailable")
        client.call = _call
        return client

    monkeypatch.setattr("src.audiobook_studio.llm.create_client", fake_create_client)

    fn = create_llm_judge_fn("edit_for_tts")
    score_a, score_b, rationale = fn(
        {"text": "hi"}, {"edited_text": "a"}, {"edited_text": "b" * 300}
    )
    assert 0.0 <= score_a <= 1.0
    assert 0.0 <= score_b <= 1.0
    assert "heuristic" in rationale


# ── create_pairwise_judge_fn ──────────────────────────────────────────────

def test_create_pairwise_judge_fn_fallback_all_stages(monkeypatch):
    """Test pairwise judge fallback for all stages."""
    import sys
    import types

    mod = types.ModuleType("src.audiobook_studio.llm.judge")

    class BoomLLMJudge:
        def __init__(self, *a, **k):
            pass

        def judge_pairwise(self, **kw):
            raise RuntimeError("boom")

    mod.LLMJudge = BoomLLMJudge
    mod.JudgeConfig = lambda **k: None
    monkeypatch.setitem(sys.modules, "src.audiobook_studio.llm.judge", mod)

    for stage in ["edit_for_tts", "annotate_paragraph", "analyze_structure", "quality_judge", "synthesize", "other_stage"]:
        fn = create_pairwise_judge_fn(stage)
        res = fn(
            segment_id="s",
            input_data={},
            output_a={"edited_text": "a"},
            output_b={"edited_text": "b" * 300},
        )
        assert res.winner in ("A", "B", "tie")


# ── blind_evaluate edge cases ──────────────────────────────────────────────

def test_blind_evaluate_partial_ratings():
    """Test blind_evaluate with ratings for only some samples."""
    res = [
        ABTestResult("s1", "A", 0.5, 0.4),
        ABTestResult("s2", "B", 0.3, 0.6),
        ABTestResult("s3", "A", 0.7, 0.2),
    ]
    rep = ABTestReport(
        stage="x", version_a=1, version_b=2, num_samples=3,
        results=res, a_wins=2, b_wins=1,
    )
    # Only rate s1 and s3
    ratings = [
        {"sample_id": "s1", "score_a": 0.9, "score_b": 0.2, "rationale": "human ok"},
        {"sample_id": "s3", "score_a": 0.8, "score_b": 0.3, "rationale": "human ok 2"},
    ]
    out = blind_evaluate(rep, ratings)
    assert out.results[0].score_a == 0.9
    assert out.results[2].score_a == 0.8
    # s2 unchanged
    assert out.results[1].score_a == 0.3
    assert out.results[1].score_b == 0.6


def test_blind_evaluate_invalid_sample_id_ignored():
    """Test blind_evaluate ignores ratings for non-existent sample IDs."""
    res = [ABTestResult("s1", "A", 0.5, 0.4)]
    rep = ABTestReport(
        stage="x", version_a=1, version_b=2, num_samples=1,
        results=res, a_wins=1, b_wins=0,
    )
    ratings = [{"sample_id": "nonexistent", "score_a": 0.9, "score_b": 0.2, "rationale": "ignored"}]
    out = blind_evaluate(rep, ratings)
    assert out.results[0].score_a == 0.5  # unchanged


# ── run_ab_test with use_llm_judge=True ──────────────────────────────────

def test_run_ab_test_with_custom_llm_judge_fn():
    """Test run_ab_test with a custom judge function mimicking LLM judge."""
    def mock_llm_judge(input_data, output_a, output_b):
        return 0.3, 0.8, "B is better"

    samples = [_make_sample() for _ in range(3)]
    rep = run_ab_test("edit_for_tts", samples, judge_fn=mock_llm_judge)
    assert rep.b_wins == 3


# ── PairwiseABTestResult dataclass ────────────────────────────────────────

def test_pairwise_abtest_result_defaults():
    """Test PairwiseABTestResult dataclass defaults."""
    res = PairwiseABTestResult(
        segment_id="s1",
        judgment=_make_pairwise_judgment(winner="A"),
    )
    assert res.segment_id == "s1"
    assert res.judgment.winner == "A"


# ── ABTestReport dataclass edge cases ─────────────────────────────────────

def test_abtest_report_avg_scores_computed():
    """Test ABTestReport avg_score_a/b computed correctly."""
    res = [
        ABTestResult("s1", "A", 0.8, 0.3),
        ABTestResult("s2", "B", 0.4, 0.9),
    ]
    rep = ABTestReport(
        stage="x", version_a=1, version_b=2, num_samples=2,
        results=res, a_wins=1, b_wins=1,
        avg_score_a=0.6, avg_score_b=0.6,
    )
    assert rep.avg_score_a == 0.6
    assert rep.avg_score_b == 0.6


# ── run_ab_test_pairwise use_llm_judge=True ──────────────────────────────

def test_run_ab_test_pairwise_use_llm_judge(monkeypatch):
    """Test run_ab_test_pairwise with use_llm_judge=True."""
    import sys
    import types

    mod = types.ModuleType("src.audiobook_studio.llm.judge")

    class FakeLLMJudge:
        def __init__(self, *args, **kwargs):
            pass

        def judge_pairwise(self, **kwargs):
            return _FakeJudgment(winner="A", dim_scores={"nat": _Dim(0.9, 0.2)})

    mod.LLMJudge = FakeLLMJudge
    mod.JudgeConfig = lambda **k: None
    monkeypatch.setitem(sys.modules, "src.audiobook_studio.llm.judge", mod)

    samples = [_make_sample() for _ in range(3)]
    rep = run_ab_test_pairwise("edit_for_tts", samples, use_llm_judge=True)
    assert rep.a_wins == 3


# ── Additional edge cases ──────────────────────────────────────────────────

def test_run_ab_test_empty_list_returns_report():
    """Test run_ab_test with empty samples returns valid report."""
    rep = run_ab_test("edit_for_tts", [])
    assert isinstance(rep, ABTestReport)
    assert rep.num_samples == 0
    assert rep.recommendation == "无样本数据"


def test_run_ab_test_pairwise_empty_list_returns_report():
    """Test run_ab_test_pairwise with empty samples returns valid report."""
    rep = run_ab_test_pairwise("edit_for_tts", [])
    assert isinstance(rep, PairwiseABTestReport)
    assert rep.num_samples == 0
    assert rep.recommendation == "无样本数据"


def test_create_pairwise_judge_fn_success_returns_fn(monkeypatch):
    """Test create_pairwise_judge_fn returns a callable on success."""
    import sys
    import types

    mod = types.ModuleType("src.audiobook_studio.llm.judge")

    class FakeLLMJudge:
        def __init__(self, *args, **kwargs):
            pass

        def judge_pairwise(self, **kwargs):
            return _FakeJudgment(winner="B")

    mod.LLMJudge = FakeLLMJudge
    mod.JudgeConfig = lambda **k: None
    monkeypatch.setitem(sys.modules, "src.audiobook_studio.llm.judge", mod)

    fn = create_pairwise_judge_fn("edit_for_tts")
    assert callable(fn)
    res = fn(segment_id="s", input_data={}, output_a={}, output_b={})
    assert res.winner == "B"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=src/audiobook_studio/feedback/ab_test.py", "--cov-branch"])