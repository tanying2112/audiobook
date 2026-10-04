"""马具迭代闭环编排（M1→M4）端到端集成测试（全离线、确定性）。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from audiobook_studio.feedback.deploy import served_version
from audiobook_studio.feedback.harness import run_iteration_cycle
from audiobook_studio.feedback.offline_judge import OfflineJudge

TEST_GOLDEN = Path("data/golden/test")
PROMPTS_SRC = Path("prompts")


def _load_pairs(stage: str):
    rows = []
    f = TEST_GOLDEN / stage / f"{stage}.jsonl"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _make_prompts_root(tmp_path: Path, stage_dir: str):
    dst = tmp_path / stage_dir
    dst.mkdir(parents=True)
    # 复制真实 v1 作为基线（运行时读取 v1.j2）
    src = PROMPTS_SRC / stage_dir / "v1.j2"
    if src.exists():
        shutil.copyfile(src, dst / "v1.j2")
    return dst


def test_run_iteration_cycle_perfect_candidate_gets_promoted(tmp_path: Path):
    stage = "judge"
    _make_prompts_root(tmp_path, "quality_judge")
    rows = _load_pairs(stage)
    exp_by_seg = {r["input"]["segment_id"]: r["expected_output"] for r in rows}

    def perfect_run(inp):
        return exp_by_seg[inp["segment_id"]]

    def bad_run(inp):
        e = dict(exp_by_seg[inp["segment_id"]])
        e["needs_regeneration"] = not bool(e.get("needs_regeneration", False))
        e["overall_score"] = 0.1
        e["issues"] = ["wrong_speaker"]
        return e

    rep = run_iteration_cycle(
        stage,
        perfect_run,
        baseline_fn=bad_run,
        prompts_root=tmp_path,
        judge=OfflineJudge(),
        auto_deploy=True,
    )
    assert rep.compiled is True
    assert rep.eval_case_count == len(rows)
    assert rep.eval_mean_score == 1.0
    assert rep.eval_baseline_mean < 1.0
    assert rep.effect_size is not None and rep.effect_size >= 0.25
    # 门禁通过且自动部署 → served 版本应为候选版本
    assert rep.passed is True
    assert rep.deployed is True
    assert served_version("judge", tmp_path) == rep.candidate_version
    # 候选文件已落盘
    assert (tmp_path / "quality_judge" / f"v{rep.candidate_version}.j2").exists()


def test_run_iteration_cycle_bad_candidate_not_deployed(tmp_path: Path):
    stage = "judge"
    _make_prompts_root(tmp_path, "quality_judge")
    rows = _load_pairs(stage)
    exp_by_seg = {r["input"]["segment_id"]: r["expected_output"] for r in rows}

    # 候选与基线都返回「退化」输出 → 金数据集通过率 < 0.95 → 拒绝部署
    def bad_run(inp):
        e = dict(exp_by_seg[inp["segment_id"]])
        e["needs_regeneration"] = True
        e["overall_score"] = 0.1
        return e

    rep = run_iteration_cycle(
        stage,
        bad_run,
        baseline_fn=bad_run,
        prompts_root=tmp_path,
        judge=OfflineJudge(),
        auto_deploy=True,
    )
    assert rep.passed is False
    assert rep.deployed is False
    assert served_version("judge", tmp_path) == 0  # 未部署
    assert "金数据集通过率" in "".join(rep.failed_criteria)
