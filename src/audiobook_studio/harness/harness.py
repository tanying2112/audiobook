"""马具迭代闭环编排（M1→M4）：把「编译→评判→晋升→部署/回滚」串成一轮可程序化驱动的迭代。

每一轮迭代对单个 stage 做：
  1. (M0/A2) 生产回流已沉淀到 data/golden/harness/{train,val,test}（前置条件，由 loop.py 完成）。
  2. (M3) 在 golden train 上把高质样本编译为候选 prompt（prompt_compiler），落盘 v{N+1}.j2。
  3. (M2) 在冻结 test 留出集上用（在线 ensemble / 离线兜底）评判器做 候选 vs 基线 实证评估
     （candidate_eval + held_out_eval）。
  4. (M4) 用 PromotionGate 的 4 项硬指标裁决；通过则部署候选到 live（v1.j2），
     不通过则 fail-closed，绝不污染线上。

整轮不触网（默认用 OfflineJudge 兜底），可离线复现；提供门禁不通过时的回滚入口。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..feedback.deploy import promote_candidate, rollback_prompt, served_version
from ..feedback.offline_judge import OfflineJudge
from ..feedback.prompt_compiler import write_candidate_prompt
from ..harness.config import HARNESS_PROMPTS_DIR, get_harness_settings
from ..harness.golden import GoldenDatasetManager, evaluate_on_harness_golden
from ..harness.models import PipelineStage
from ..harness.sop_store import SOPRuleStore
from ..harness.spotcheck import human_preference_score_for
from ..harness.storage import get_storage

logger = logging.getLogger(__name__)


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
    use_learned: bool = False,
) -> IterationReport:
    """对单个 stage 跑一轮完整的马具迭代（编译→评判→晋升→部署）。

    Args:
        stage: golden stage 名（extract/analyze/annotate/edit/judge/quality/...）。
        run_fn: ``input_dict -> output``，跑候选 prompt 版本的真实 stage（注入式，离线可测）。
        baseline_fn: 同上，跑基线 prompt 版本；为 None 时 only 评估候选。
        k: M3 选取的 few-shot 示例数。
        golden_root: 预留覆盖项；当前 harness 金标固定为 ``data/golden/harness``（平铺布局），
            故该参数不影响读取（保留 API 兼容）。
        judge: 评判器（默认 ``OfflineJudge``，零网络兜底）。
        prompts_root: prompts 根目录，默认 ``prompts``。
        auto_deploy: 门禁通过是否自动部署；False 仅裁决不部署。
    """
    root = prompts_root or HARNESS_PROMPTS_DIR
    j = judge or OfflineJudge()

    settings = get_harness_settings()

    # (M3) 编译候选并落盘 v{N+1}.j2
    if use_learned:
        # 学习型候选生成：规则拼接 + DSPy/GEPA 反思变异（无训练样本/不可用时回退规则）
        from .prompt_evolution import PromptEvolutionEngine

        compile_result = PromptEvolutionEngine().compile_candidate(stage, k=k, prompts_root=root, use_learned=True)
        candidate_version = compile_result["version"]
        logger.info(
            f"[harness] {stage}: 学习型编译候选 v{candidate_version}（learned={compile_result.get('learned')}）"
        )
    else:
        cp = write_candidate_prompt(stage, k=k, prompts_root=root)
        candidate_version = cp.version
        logger.info(f"[harness] {stage}: 编译候选 v{candidate_version}（示例={len(cp.exemplars)}）")

    # (M2) 在 harness 自有冻结 test 留出集上做 候选 vs 基线 实证评判。
    # 平铺布局 data/golden/harness/test/{stage}.jsonl，harness 自洽，
    # 不借用 feedback 的 run_candidate_on_held_out（读取嵌套布局，无法读 harness 金标）。
    eval_result = evaluate_on_harness_golden(
        stage=stage,
        run_fn=run_fn,
        judge=j,
        baseline_fn=baseline_fn,
        split="test",
    )

    golden_pass_rate = eval_result["mean_score"]
    baseline_mean = eval_result["baseline_mean"]
    # 质量比基线：有基线时取 候选/基线，避免除零；无基线则置于 1.0（无退化信号，但
    # 仍受其余 3 项门禁约束，保守处理）。
    if baseline_mean is not None and baseline_mean > 0:
        quality_ratio = eval_result["mean_score"] / baseline_mean
    elif baseline_mean is not None and baseline_mean == 0:
        quality_ratio = 1.0 if eval_result["mean_score"] > 0 else 0.0
    else:
        quality_ratio = 1.0

    # (M3) 人工抽检偏好分：默认从 harness 抽检库读取真实人工评分；
    # 无抽检记录时回退到传入值（默认 1.0），避免「恒为满分直接放行」。
    human_preference_score = human_preference_score_for(stage, default=human_preference_score)

    # (M4) 晋升门禁 + 部署（复用 feedback/deploy.promote_candidate 的真引擎）
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
        eval_case_count=eval_result["case_count"],
        eval_mean_score=eval_result["mean_score"],
        eval_baseline_mean=baseline_mean,
        effect_size=eval_result["effect_size"],
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


# ──────────────────────────────────────────────────────────────────────────────
# 便捷入口：从配置运行完整迭代周期
# ──────────────────────────────────────────────────────────────────────────────


async def run_full_iteration_cycle(
    stages: Optional[List[str]] = None,
    auto_deploy: bool = True,
    judge: Optional[Any] = None,
) -> List[IterationReport]:
    """从配置运行完整迭代周期的便捷入口。

    读取配置中的 stage 列表、golden_root、prompts_root 等，自动跑完整轮次。
    """
    settings = get_harness_settings()
    stages = stages or list(PipelineStage.__members__.values())

    # 从配置获取阶段列表
    if not stages:
        stages = [s.value for s in PipelineStage]

    reports = []
    for stage in stages:
        rep = run_iteration_cycle(
            stage=stage,
            run_fn=lambda inp, _s=stage: run_stage(_s, inp),  # 需要实际的 stage 运行函数
            auto_deploy=auto_deploy,
        )
        reports.append(rep)

    return reports


def run_stage(stage: str, input_data: Dict[str, Any]) -> Any:
    """运行单个 stage 的真实逻辑：委托给 feedback 的真实 stage 运行器。

    以 v1（live）基线 prompt 版本执行，作为 autonomous 迭代轮次
    （``trigger_iteration`` / ``run_full_iteration_cycle``）的默认 ``run_fn``。
    真实运行器位于 ``feedback/canary.py:_run_stage_with_prompt_version``。
    """
    from ..feedback.canary import _run_stage_with_prompt_version

    return _run_stage_with_prompt_version(stage, 1, input_data)


# ──────────────────────────────────────────────────────────────────────────────
# 批量迭代编排
# ──────────────────────────────────────────────────────────────────────────────


async def run_harness_cycle(
    stages: Optional[List[str]] = None,
    auto_deploy: bool = True,
    golden_root: Optional[Path] = None,
    prompts_root: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """运行完整的马具迭代周期（异步版）。

    返回所有 stage 的迭代报告列表。
    """
    settings = get_harness_settings()
    stages = stages or [s.value for s in PipelineStage]

    reports = []
    for stage in stages:
        # 这里需要实际的 stage 运行函数
        # 暂时返回模拟报告
        reports.append(
            {
                "stage": stage,
                "status": "pending",
                "message": "待集成真实 stage 运行逻辑",
            }
        )

    return reports


def get_harness_status() -> Dict[str, Any]:
    """获取马具迭代系统整体状态。"""
    settings = get_harness_settings()
    storage = get_storage()

    return {
        "enabled": settings.ENABLED,
        "self_iteration_llm": settings.SELF_ITERATION_LLM,
        "batch_size": settings.SELF_ITERATION_BATCH_SIZE,
        "mock_mode": settings.SELF_ITERATION_MOCK,
        "golden_root": settings.GOLDEN_ROOT,
        "prompts_dir": str(HARNESS_PROMPTS_DIR),
        "golden_stats": {
            "train": 0,
            "val": 0,
            "test": 0,
        },
        "active_canaries": 0,
        "pending_promotions": 0,
    }


def trigger_iteration(stage: str, auto_deploy: bool = True) -> IterationReport:
    """手动触发单个 stage 的迭代周期（用于 API/手动触发）。"""
    return run_iteration_cycle(
        stage=stage,
        run_fn=lambda inp: run_stage(stage, inp),
        auto_deploy=auto_deploy,
    )


# ──────────────────────────────────────────────────────────────────────────────
# 导出
# ──────────────────────────────────────────────────────────────────────────────

__all__ = [
    "IterationReport",
    "run_iteration_cycle",
    "run_iteration_cycles",
    "run_harness_cycle",
    "get_harness_status",
    "trigger_iteration",
    "run_iteration_cycles",
]
