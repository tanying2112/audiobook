"""马具迭代闭环编排（M1→M4）：把「编译→评判→晋升→部署/回滚」串成一轮可程序化驱动的迭代。

每一轮迭代对单个 stage 做：
  1. (M0/A2) 生产回流已沉淀到 ``data/golden/{train,val,test}``（前置条件，由 loop.py 完成）。
  2. (M3) 在 golden train 上把高质样本编译为候选 prompt（``prompt_compiler``），落盘 v{N+1}.j2。
  3. (M2) 在冻结 test 留出集上用（在线 ensemble / 离线兜底）评判器做 候选 vs 基线 实证评估
     （``candidate_eval`` + ``held_out_eval``）。
  4. (M4) 用 ``release.PromotionGate`` 的 4 项硬指标裁决；通过则部署候选到 live（v1.j2），
     不通过则 fail-closed，绝不污染线上。

整轮不触网（默认用 ``OfflineJudge`` 兜底），可离线复现；提供门禁不通过时的回滚入口。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .candidate_eval import DEFAULT_TEST_GOLDEN_ROOT, EnsembleJudge, run_candidate_on_held_out
from .deploy import promote_candidate, rollback_prompt, served_version
from .offline_judge import OfflineJudge
from .prompt_compiler import write_candidate_prompt

logger = logging.getLogger(__name__)

DEFAULT_PROMPTS_DIR = Path("prompts")


@dataclass
class IterationReport:
    """一轮迭代的结果摘要。"""

    stage: str
    candidate_version: int
    compiled: bool
    eval_case_count: int
    eval_mean_score: float
    eval_baseline_mean: Optional[float]
    effect_size: Optional[float]
    passed: bool
    deployed: bool
    failed_criteria: List[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage,
            "candidate_version": self.candidate_version,
            "compiled": self.compiled,
            "eval_case_count": self.eval_case_count,
            "eval_mean_score": self.eval_mean_score,
            "eval_baseline_mean": self.eval_baseline_mean,
            "effect_size": self.effect_size,
            "passed": self.passed,
            "deployed": self.deployed,
            "failed_criteria": list(self.failed_criteria),
            "notes": self.notes,
        }


def run_iteration_cycle(
    stage: str,
    run_fn: Callable[[Dict[str, Any]], Any],
    baseline_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
    *,
    k: int = 3,
    golden_root: Optional[Path] = None,
    prompts_root: Optional[Path] = None,
    judge: Optional[Any] = None,
    auto_deploy: bool = True,
    format_compliance_rate: float = 1.0,
    human_preference_score: float = 1.0,
    candidate_id: Optional[str] = None,
) -> IterationReport:
    """对单个 stage 跑一轮完整的马具迭代（编译→评判→晋升→部署）。

    Args:
        stage: golden stage 名（extract/analyze/annotate/edit/judge/quality/...）。
        run_fn: ``input_dict -> output``，跑候选 prompt 版本的真实 stage（注入式，离线可测）。
        baseline_fn: 同上，跑基线 prompt 版本；为 None 时 only 评估候选。
        k: M3 选取的 few-shot 示例数。
        golden_root: 留出集根目录，默认 ``data/golden/test``。
        prompts_root: prompts 根目录，默认 ``prompts``。
        judge: 评判器（默认 ``OfflineJudge``，零网络兜底）。
        auto_deploy: 门禁通过是否自动部署；False 仅裁决不部署。
    """
    root = prompts_root or DEFAULT_PROMPTS_DIR
    groot = golden_root or DEFAULT_TEST_GOLDEN_ROOT
    j = judge or OfflineJudge()

    # (M3) 编译候选并落盘 v{N+1}.j2
    cp = write_candidate_prompt(stage, k=k, prompts_root=root)
    candidate_version = cp.version
    logger.info(f"[harness] {stage}: 编译候选 v{candidate_version}（示例={len(cp.exemplars)}）")

    # (M2) 冻结 test 留出集上做 候选 vs 基线 实证评判
    eval_result = run_candidate_on_held_out(
        stage,
        run_fn,
        baseline_fn=baseline_fn,
        golden_root=groot,
        candidate_id=candidate_id or f"v{candidate_version}",
        baseline_id="baseline",
        judge=j,
    )

    golden_pass_rate = eval_result.mean_score
    baseline_mean = eval_result.baseline_mean
    # 质量比基线：有基线时取 候选/基线，避免除零；无基线则置于 1.0（无退化信号，但
    # 仍受其余 3 项门禁约束，保守处理）。
    if baseline_mean is not None and baseline_mean > 0:
        quality_ratio = eval_result.mean_score / baseline_mean
    elif baseline_mean is not None and baseline_mean == 0:
        quality_ratio = 1.0 if eval_result.mean_score > 0 else 0.0
    else:
        quality_ratio = 1.0

    # (M4) 晋升门禁 + 部署
    decision = promote_candidate(
        stage,
        candidate_version,
        golden_dataset_pass_rate=golden_pass_rate,
        quality_score_ratio=quality_ratio,
        format_compliance_rate=format_compliance_rate,
        human_preference_score=human_preference_score,
        prompts_dir=root,
        auto_deploy=auto_deploy,
    )

    return IterationReport(
        stage=stage,
        candidate_version=candidate_version,
        compiled=True,
        eval_case_count=eval_result.case_count,
        eval_mean_score=eval_result.mean_score,
        eval_baseline_mean=baseline_mean,
        effect_size=eval_result.effect_size,
        passed=decision.passed,
        deployed=decision.deployed,
        failed_criteria=list(decision.failed_criteria),
        notes=cp.selection_note,
    )


def run_iteration_cycles(
    stages: List[str],
    run_fn: Callable[[str, Dict[str, Any]], Any],
    baseline_fn: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
    *,
    k: int = 3,
    golden_root: Optional[Path] = None,
    prompts_root: Optional[Path] = None,
    judge: Optional[Any] = None,
    auto_deploy: bool = True,
) -> List[IterationReport]:
    """对多个 stage 批量跑迭代；``run_fn(stage, input_dict) -> output`` 按 stage 分发。"""
    reports: List[IterationReport] = []
    for stage in stages:
        rep = run_iteration_cycle(
            stage,
            lambda inp, _s=stage: run_fn(_s, inp),
            baseline_fn=(lambda inp, _s=stage: baseline_fn(_s, inp)) if baseline_fn else None,
            k=k,
            golden_root=golden_root,
            prompts_root=prompts_root,
            judge=judge,
            auto_deploy=auto_deploy,
        )
        reports.append(rep)
    return reports


__all__ = [
    "IterationReport",
    "run_iteration_cycle",
    "run_iteration_cycles",
    "EnsembleJudge",
    "OfflineJudge",
    "served_version",
    "rollback_prompt",
]
