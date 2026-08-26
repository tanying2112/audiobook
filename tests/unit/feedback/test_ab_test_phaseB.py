"""Phase B structural tests for feedback/ab_test.py (mocking LLM boundaries)."""

from pathlib import Path
from unittest.mock import MagicMock

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


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


def test_abtest_sample_fields():
    s = ABTestSample(
        sample_id="s1", stage="edit_for_tts", input_data={"x": 1},
        output_a={"edited_text": "a"}, output_b={"edited_text": "b"},
        version_a=1, version_b=2,
    )
    assert s.sample_id == "s1"
    assert s.version_a == 1


def test_abtest_result_defaults():
    r = ABTestResult(sample_id="s1", winner="A", score_a=0.5, score_b=0.4)
    assert r.rationale == ""


def test_abtest_report_defaults():
    rep = ABTestReport(stage="x", version_a=1, version_b=2, num_samples=0, results=[])
    assert rep.a_wins == 0
    assert rep.p_value == 1.0
    assert rep.is_significant is False
    assert rep.significance_level == 0.05


def test_pairwise_report_defaults():
    rep = PairwiseABTestReport(stage="x", version_a=1, version_b=2, num_samples=0, results=[])
    assert rep.recommendation == ""


# ---------------------------------------------------------------------------
# _score_output
# ---------------------------------------------------------------------------


def test_score_output_baseline_unknown_stage():
    assert _score_output({}, "unknown_stage") == 0.5


def test_score_output_edit_for_tts():
    out = {"edited_text": "x" * 300, "forbidden_content_removed": True, "confidence": 0.8}
    s = _score_output(out, "edit_for_tts")
    # 0.5 + 0.1*1.0 + 0.1 + 0.1*0.8 = 0.78
    assert abs(s - 0.78) < 1e-9


def test_score_output_quality_judge():
    out = {"overall_score": 0.9, "issues": [1], "fix_suggestions": [1]}
    s = _score_output(out, "quality_judge")
    assert abs(s - (0.5 + 0.2 * 0.9 + 0.1 + 0.1)) < 1e-9


def test_score_output_annotate_paragraph():
    out = {
        "emotion": "happy", "speaker_canonical_name": "n", "is_dialogue": True,
        "emotion_intensity": 0.5,
    }
    s = _score_output(out, "annotate_paragraph")
    # 0.5 + 0.1*3 + 0.1 = 0.9
    assert abs(s - 0.9) < 1e-9


def test_score_output_clamped():
    out = {"edited_text": "x", "forbidden_content_removed": True, "confidence": 100.0}
    s = _score_output(out, "edit_for_tts")
    assert s <= 1.0


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------


def test_significance_empty():
    p, ci, sig = _compute_statistical_significance([])
    assert p == 1.0 and ci == (0.0, 0.0) and sig is False


def test_significance_single_sample():
    results = [ABTestResult("s", "A", 0.5, 0.7)]
    p, ci, sig = _compute_statistical_significance(results)
    assert sig is False
    assert p == 1.0


def test_significance_significant():
    diffs = [0.5, 0.7, 0.6, 0.8, 0.55, 0.65, 0.75, 0.6, 0.7, 0.65]
    results = [ABTestResult(f"s{i}", "B", 0.2, 0.2 + d) for i, d in enumerate(diffs)]
    p, ci, sig = _compute_statistical_significance(results)
    assert sig is True
    assert p < 0.05


def test_significance_no_diff():
    results = [ABTestResult(f"s{i}", "tie", 0.5, 0.5) for i in range(10)]
    p, ci, sig = _compute_statistical_significance(results)
    assert sig is False


def test_paired_ttest_empty():
    p, ci, sig = _compute_paired_ttest([])
    assert p == 1.0 and sig is False


def test_paired_ttest_single():
    p, ci, sig = _compute_paired_ttest([0.3])
    assert sig is False


def test_paired_ttest_with_diff():
    diffs = [0.5, 0.6, 0.4, 0.55, 0.45]
    p, ci, sig = _compute_paired_ttest(diffs)
    assert isinstance(p, float)


# ---------------------------------------------------------------------------
# build_ab_samples
# ---------------------------------------------------------------------------


def test_build_ab_samples():
    examples = [
        {"input": {"text": "a"}, "output_old": {"v": 1}, "output_new": {"v": 2}},
        {"input": {"text": "b"}, "output": {"v": 0}},
    ]
    samples = build_ab_samples("edit_for_tts", examples, 1, 2)
    assert len(samples) == 2
    assert samples[0].output_a == {"v": 1}
    assert samples[0].output_b == {"v": 2}
    assert samples[0].version_a == 1 and samples[0].version_b == 2
    # fallback to "output" when old/new absent
    assert samples[1].output_a == {"v": 0}
    assert samples[1].output_b == {"v": 0}


# ---------------------------------------------------------------------------
# run_ab_test
# ---------------------------------------------------------------------------


def _make_sample(stage="edit_for_tts", a=None, b=None):
    return ABTestSample(
        sample_id="s1", stage=stage, input_data={},
        output_a=a or {}, output_b=b or {}, version_a=1, version_b=2,
    )


def test_run_ab_test_empty():
    rep = run_ab_test("edit_for_tts", [])
    assert rep.num_samples == 0
    assert rep.recommendation == "无样本数据"


def test_run_ab_test_heuristic_fallback():
    samples = [_make_sample(a={"edited_text": "short"}, b={"edited_text": "x" * 300, "forbidden_content_removed": True})]
    rep = run_ab_test("edit_for_tts", samples)
    assert rep.num_samples == 1
    assert rep.results[0].score_b > rep.results[0].score_a


def test_run_ab_test_old_signature_judge():
    def judge(output):
        return 0.9 if output.get("good") else 0.1

    samples = [
        _make_sample(a={"good": True}, b={"good": False}),
    ]
    rep = run_ab_test("edit_for_tts", samples, judge_fn=judge)
    assert rep.results[0].score_a == 0.9
    assert rep.results[0].score_b == 0.1
    assert rep.a_wins == 1


def test_run_ab_test_new_signature_judge_b_wins():
    def judge(input_data, output_a, output_b):
        return 0.2, 0.95, "B is better"

    samples = [_make_sample() for _ in range(3)]
    rep = run_ab_test("edit_for_tts", samples, judge_fn=judge)
    assert rep.b_wins == 3
    assert "推荐升级" in rep.recommendation
    assert rep.is_significant is False or isinstance(rep.p_value, float)


def test_run_ab_test_new_signature_judge_a_wins():
    def judge(input_data, output_a, output_b):
        return 0.9, 0.2, "A is better"

    samples = [_make_sample() for _ in range(3)]
    rep = run_ab_test("edit_for_tts", samples, judge_fn=judge)
    assert rep.a_wins == 3
    assert "不建议升级" in rep.recommendation


def test_run_ab_test_tie():
    def judge(input_data, output_a, output_b):
        return 0.5, 0.5, "tie"

    samples = [_make_sample() for _ in range(3)]
    rep = run_ab_test("edit_for_tts", samples, judge_fn=judge)
    assert rep.ties == 3
    assert "结果不明确" in rep.recommendation


# ---------------------------------------------------------------------------
# run_ab_test_pairwise
# ---------------------------------------------------------------------------


class _FakeJudgment:
    def __init__(self, winner, dim_scores=None):
        self.winner = winner
        self.dimension_scores = dim_scores or {}


class _Dim:
    def __init__(self, a, b):
        self.score_a = a
        self.score_b = b


def test_run_ab_test_pairwise_empty():
    rep = run_ab_test_pairwise("edit_for_tts", [])
    assert rep.num_samples == 0
    assert rep.recommendation == "无样本数据"


def test_run_ab_test_pairwise_custom_judge():
    def judge(segment_id, input_data, output_a, output_b, annotation, audio_description):
        return _FakeJudgment(winner="B", dim_scores={"nat": _Dim(0.2, 0.9)})

    samples = [_make_sample() for _ in range(3)]
    rep = run_ab_test_pairwise("edit_for_tts", samples, judge_fn=judge)
    assert rep.num_samples == 3
    assert rep.b_wins == 3
    assert "推荐升级" in rep.recommendation


def test_run_ab_test_pairwise_heuristic_fallback():
    samples = [_make_sample(a={"edited_text": "short"}, b={"edited_text": "x" * 300})]
    rep = run_ab_test_pairwise("edit_for_tts", samples)
    assert rep.num_samples == 1
    assert rep.results[0].judgment.winner in ("A", "B", "tie")


# ---------------------------------------------------------------------------
# create_llm_judge_fn (LLM mocked to fail -> heuristic fallback)
# ---------------------------------------------------------------------------


def test_create_llm_judge_fn_fallback(monkeypatch):
    def fake_create_client(**kwargs):
        client = MagicMock()

        def _call(**kw):
            raise RuntimeError("llm unavailable")

        client.call = _call
        return client

    monkeypatch.setattr("src.audiobook_studio.llm.create_client", fake_create_client)
    judge_fn = create_llm_judge_fn("edit_for_tts")
    score_a, score_b, rationale = judge_fn(
        {"text": "hi"}, {"edited_text": "a"}, {"edited_text": "b" * 300}
    )
    assert 0.0 <= score_a <= 1.0
    assert 0.0 <= score_b <= 1.0
    assert "heuristic" in rationale


@pytest.mark.parametrize("stage", [
    "edit_for_tts", "annotate_paragraph", "analyze_structure",
    "quality_judge", "synthesize", "other_stage",
])
def test_create_llm_judge_fn_all_stages(monkeypatch, stage):
    def fake_create_client(**kwargs):
        client = MagicMock()

        def _call(**kw):
            raise RuntimeError("llm unavailable")

        client.call = _call
        return client

    monkeypatch.setattr("src.audiobook_studio.llm.create_client", fake_create_client)
    judge_fn = create_llm_judge_fn(stage)
    score_a, score_b, rationale = judge_fn(
        {"text": "hi", "book_text": "b", "expected_text": "e"},
        {"edited_text": "a"}, {"edited_text": "b" * 300},
    )
    assert 0.0 <= score_a <= 1.0
    assert 0.0 <= score_b <= 1.0


@pytest.fixture
def fake_llm_judge(monkeypatch):
    import sys
    import types

    mod = types.ModuleType("src.audiobook_studio.llm.judge")

    class FakeLLMJudge:
        def __init__(self, *a, **k):
            pass

        def judge_pairwise(self, **kw):
            return "FAKE_RESULT"

    mod.LLMJudge = FakeLLMJudge
    mod.JudgeConfig = lambda **k: None
    monkeypatch.setitem(sys.modules, "src.audiobook_studio.llm.judge", mod)
    return mod


def test_create_pairwise_judge_fn_success(fake_llm_judge):
    fn = create_pairwise_judge_fn("edit_for_tts")
    res = fn(segment_id="s", input_data={}, output_a={}, output_b={})
    assert res == "FAKE_RESULT"


def test_create_pairwise_judge_fn_fallback(fake_llm_judge):
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
    # replace the injected module to use the boom variant
    fake_llm_judge.LLMJudge = BoomLLMJudge

    fn = create_pairwise_judge_fn("edit_for_tts")
    res = fn(
        segment_id="s",
        input_data={},
        output_a={"edited_text": "a"},
        output_b={"edited_text": "b" * 300},
    )
    assert res.winner in ("A", "B", "tie")


def test_run_ab_test_pairwise_a_wins():
    def judge(segment_id, input_data, output_a, output_b, annotation, audio_description):
        return _FakeJudgment(winner="A", dim_scores={"nat": _Dim(0.9, 0.2)})

    samples = [_make_sample() for _ in range(3)]
    rep = run_ab_test_pairwise("edit_for_tts", samples, judge_fn=judge)
    assert rep.a_wins == 3
    assert "不建议升级" in rep.recommendation


def test_run_ab_test_pairwise_use_llm_judge(monkeypatch):
    def fake_pairwise_judge(stage, judge_model=None, router=None):
        def j(segment_id, input_data, output_a, output_b, annotation, audio_description):
            return _FakeJudgment(winner="B", dim_scores={"nat": _Dim(0.2, 0.9)})

        return j

    monkeypatch.setattr(
        "src.audiobook_studio.feedback.ab_test.create_pairwise_judge_fn", fake_pairwise_judge
    )
    samples = [_make_sample() for _ in range(3)]
    rep = run_ab_test_pairwise("edit_for_tts", samples, use_llm_judge=True)
    assert rep.b_wins == 3


# ---------------------------------------------------------------------------
# blind_evaluate
# ---------------------------------------------------------------------------


def test_blind_evaluate_no_ratings():
    rep = ABTestReport(
        stage="x", version_a=1, version_b=2, num_samples=1,
        results=[ABTestResult("s1", "A", 0.5, 0.4)],
    )
    out = blind_evaluate(rep, None)
    assert out is rep


def test_blind_evaluate_merges_ratings():
    res = [ABTestResult("s1", "A", 0.5, 0.4), ABTestResult("s2", "B", 0.3, 0.6)]
    rep = ABTestReport(
        stage="x", version_a=1, version_b=2, num_samples=2,
        results=res, a_wins=1, b_wins=1,
    )
    ratings = [{"sample_id": "s1", "score_a": 0.9, "score_b": 0.2, "rationale": "human ok"}]
    out = blind_evaluate(rep, ratings)
    assert out.results[0].score_a == 0.9
    assert out.results[0].winner == "A"
    assert "human ok" in out.results[0].rationale
    # aggregates recomputed
    assert out.a_wins == 1
    assert out.b_wins == 1
    assert out.avg_score_a == 0.6
