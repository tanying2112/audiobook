"""M2 — 冻结留出集上 候选 vs 基线 实证评判。"""

from __future__ import annotations

import json
from pathlib import Path

from audiobook_studio.feedback.candidate_eval import (
    DeterministicJudge,
    EnsembleJudge,
    run_candidate_on_held_out,
    score_output_vs_expected,
)

TEST_GOLDEN = Path("data/golden/test")


def _load_judge_pairs():
    rows = []
    for line in (TEST_GOLDEN / "judge" / "judge.jsonl").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def test_score_output_vs_expected_identical_is_one():
    exp = {"needs_regeneration": False, "overall_score": 0.9, "issues": []}
    assert score_output_vs_expected(exp, dict(exp)) == 1.0


def test_score_output_vs_expected_pass_fail_mismatch_lowers():
    exp = {"needs_regeneration": False, "overall_score": 0.9, "issues": []}
    bad = {"needs_regeneration": True, "overall_score": 0.2, "issues": ["wrong_speaker"]}
    s = score_output_vs_expected(exp, bad)
    assert 0.0 <= s < 1.0
    # 通过/失败一致且数值接近的同质样本应更高
    similar = {"needs_regeneration": False, "overall_score": 0.85, "issues": []}
    assert score_output_vs_expected(exp, similar) > s


def test_deterministic_judge_offline_and_reproducible():
    j = DeterministicJudge()
    a = j.score(
        {},
        {"needs_regeneration": False, "overall_score": 0.9},
        {"needs_regeneration": False, "overall_score": 0.9},
        "judge",
    )
    b = j.score(
        {},
        {"needs_regeneration": False, "overall_score": 0.9},
        {"needs_regeneration": False, "overall_score": 0.9},
        "judge",
    )
    assert a == b == 1.0


def test_ensemble_judge_degrades_without_ensemble():
    # 未装 ensemble 时（或构造时不传 models）应离线降级，不触网、可调用。
    j = EnsembleJudge(models=None)
    score = j.score(
        {"x": 1},
        {"needs_regeneration": False, "overall_score": 0.9},
        {"needs_regeneration": False, "overall_score": 0.9},
        "judge",
    )
    assert score == 1.0


def test_run_candidate_on_held_out_prefect_candidate_beats_bad_baseline():
    rows = _load_judge_pairs()
    exp_by_seg = {r["input"]["segment_id"]: r["expected_output"] for r in rows}

    def perfect_run(inp):
        return exp_by_seg[inp["segment_id"]]

    def bad_run(inp):
        e = dict(exp_by_seg[inp["segment_id"]])
        e["needs_regeneration"] = not bool(e.get("needs_regeneration", False))
        e["overall_score"] = 0.1
        e["issues"] = ["wrong_speaker", "silent_segment"]
        return e

    res = run_candidate_on_held_out(
        "judge",
        perfect_run,
        baseline_fn=bad_run,
        golden_root=TEST_GOLDEN,
        candidate_id="v2",
        baseline_id="v1",
    )
    assert res.case_count == len(rows)
    assert res.mean_score == 1.0  # 候选完美复现期望
    assert res.baseline_mean < 1.0
    assert res.effect_size is not None
    # 冻结预留的晋升红线：候选 ≥ 基线 + 0.25
    assert res.effect_size >= 0.25
    assert res.beat_baseline_by_025 is True


def test_run_candidate_on_held_out_empty_set_honest_degrade(tmp_path: Path):
    # 指向空目录：诚实降级，不假通过
    empty = tmp_path / "judge"
    empty.mkdir(parents=True)
    res = run_candidate_on_held_out("judge", lambda inp: {}, golden_root=empty)
    assert res.case_count == 0
    assert res.effect_size is None
    assert res.beat_baseline_by_025 is False
