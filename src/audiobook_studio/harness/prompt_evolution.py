"""Prompt 进化引擎：基于 Golden 数据集的 Prompt 自动进化。

核心功能：
1. 基于 Golden train 集编译候选 Prompt (DSPy BootstrapFewShot / 启发式)
2. Prompt 版本管理 (vN.j2 版本化、Jinja2 模板)
2. 金丝雀 A/B 测试集成
3. 晋升门禁集成
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from ..feedback.offline_judge import OfflineJudge
from ..feedback.prompt_compiler import write_candidate_prompt
from ..harness.config import get_harness_settings
from ..harness.golden import (
    DEFAULT_PROMPTS_DIR,
    DEFAULT_TEST_GOLDEN_ROOT,
    GoldenDatasetManager,
    evaluate_on_harness_golden,
)
from ..harness.models import PipelineStage, PromptCompileRequest, PromptCompileResponse, PromptStatus, PromptVersion
from ..harness.storage import get_storage

logger = logging.getLogger(__name__)

DEFAULT_PROMPTS_DIR = Path("prompts/harness")
DEFAULT_GOLDEN_ROOT = DEFAULT_TEST_GOLDEN_ROOT  # 指向 harness 自有金标（平铺布局 data/golden/harness）


class PromptCompileResult(BaseModel):
    """Prompt 编译结果。"""

    version: int
    stage: str
    exemplars_count: int
    selection_note: str
    template_path: str


class PromptEvolutionEngine:
    """Prompt 自动进化引擎。

    核心流程：
    1. 从 Golden train 集选取 k-shot 示例
    2. 编译生成候选 Prompt v{N+1}.j2
    3. 在 Golden val/test 上做金丝雀 A/B 评估
    4. 通过晋升门禁则自动部署
    """

    def __init__(self, prompts_root: Optional[Path] = None, golden_root: Optional[Path] = None):
        self.prompts_root = Path(prompts_root) if prompts_root else DEFAULT_PROMPTS_DIR
        self.golden_root = DEFAULT_TEST_GOLDEN_ROOT  # data/golden/harness（harness 自有平铺金标）
        self._settings = None

    @property
    def settings(self):
        if self._settings is None:
            from ..harness.config import get_harness_settings

            self._settings = get_harness_settings()
        return self._settings

    # ──────────────────────────────────────────────────────────────────────────
    # 核心编译流程
    # ──────────────────────────────────────────────────────────────────────────

    def compile_candidate(
        self,
        stage: str,
        k: int = 3,
        exemplars_source: str = "golden_train",
        prompts_root: Optional[Path] = None,
        use_learned: bool = False,
    ) -> Dict[str, Any]:
        """编译候选 Prompt v{N+1}.j2。

        1. 从 Golden train 集选取 k-shot 示例
        2. 调用 prompt_compiler 生成 v{N+1}.j2
        3. 返回编译结果（版本号、示例数、选择说明等）

        ``use_learned=True`` 时，在规则拼接之外再用 DSPy/GEPA
        （``feedback.bootstrap_fewshot.run_bootstrap_optimization``）做学习型变异；
        若优化不可用或无训练样本，安全回退到规则拼接（默认路径不变）。
        """
        from ..feedback.prompt_compiler import write_candidate_prompt

        prompts_root = Path(prompts_root) if prompts_root else DEFAULT_PROMPTS_DIR
        cp = write_candidate_prompt(stage, k=k, prompts_root=prompts_root)

        learned = False
        if use_learned:
            try:
                from ..feedback.bootstrap_fewshot import run_bootstrap_optimization

                result = run_bootstrap_optimization(stage)
                optimized = getattr(result, "optimized_prompt", None) if result else None
                if optimized:
                    target = Path(prompts_root) / cp.prompt_dir / f"v{cp.version}.j2"
                    target.write_text(optimized, encoding="utf-8")
                    learned = True
                    logger.info(f"[PromptEvolution] {stage}: 学习型候选（DSPy/GEPA）已覆盖 v{cp.version}")
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[PromptEvolution] 学习型编译失败，回退规则拼接: {exc}")

        logger.info(f"[PromptEvolution] {stage}: 编译候选 v{cp.version}（示例={len(cp.exemplars)}）")
        return {
            "version": cp.version,
            "base_version": cp.base_version,
            "stage": stage,
            "exemplars_count": len(cp.exemplars),
            "selection_note": cp.selection_note,
            "template_path": cp.prompt_dir,
            "learned": learned,
        }

    def compile_all_stages(
        self,
        stages: Optional[List[str]] = None,
        k: int = 3,
    ) -> List[Dict[str, Any]]:
        """批量编译多个 stage 的候选 Prompt。"""
        stages = stages or ["extract", "analyze", "annotate", "edit", "judge", "route", "translate"]

        results = []
        for stage in stages:
            try:
                result = self.compile_candidate(stage=stage, k=3)
                results.append({"stage": stage, "success": True, **result})
            except Exception as e:
                logger.error(f"Failed to compile candidate for {stage}: {e}")
                results.append({"stage": stage, "success": False, "error": str(e)})

        return results

    # ──────────────────────────────────────────────────────────────────────────
    # 评估与金丝雀 A/B
    # ──────────────────────────────────────────────────────────────────────────

    def evaluate_candidate(
        self,
        stage: str,
        run_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
        baseline_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
        k: int = 3,
        golden_root: Optional[Path] = None,
        prompts_root: Optional[Path] = None,
        judge=None,
        mock_run_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
        held_out_split: str = "test",
    ) -> Dict[str, Any]:
        """在 harness 自有留出集（``data/golden/harness/{split}/{stage}.jsonl``，平铺布局）
        上评估候选 vs 基线；不借用 feedback 的 ``run_candidate_on_held_out``（嵌套布局），
        保证 harness 自洽、与 feedback 套件无数据耦合。

        Args:
            held_out_split: 用于评估的留出集 split（默认 ``test``，与 M2 冻结留出集语义一致）。
            golden_root: 预留覆盖项；当前 harness 金标固定为 ``data/golden/harness``，
                故该参数不影响读取（仅保留 API 兼容）。
        """
        from ..feedback.offline_judge import OfflineJudge

        j = judge or OfflineJudge()

        # 兼容测试/调用方使用 mock_run_fn 作为运行函数
        if run_fn is None:
            run_fn = mock_run_fn

        # 先编译候选
        compile_result = self.compile_candidate(stage, k=3, prompts_root=DEFAULT_PROMPTS_DIR)
        candidate_version = compile_result["version"]

        # 若未提供运行函数，退回元数据结果（保证返回契约字段）
        if run_fn is None:
            return {
                "stage": stage,
                "candidate_version": candidate_version,
                "eval_case_count": 0,
                "eval_mean_score": 0.0,
                "eval_baseline_mean": None,
                "effect_size": None,
                "golden_pass_rate": 0.0,
                "quality_ratio": 1.0,
            }

        # 在 harness 自有留出集上实证评估（平铺布局 data/golden/harness/{split}/{stage}.jsonl）
        try:
            result = evaluate_on_harness_golden(
                stage=stage,
                run_fn=run_fn,
                judge=j,
                baseline_fn=baseline_fn,
                split=held_out_split,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[PromptEvolution] evaluate_candidate 评估跳过（无金标/运行异常）: {exc}")
            return {
                "stage": stage,
                "candidate_version": candidate_version,
                "eval_case_count": 0,
                "eval_mean_score": 0.0,
                "eval_baseline_mean": None,
                "effect_size": None,
                "golden_pass_rate": 0.0,
                "quality_ratio": 1.0,
            }

        mean = result["mean_score"]
        base_mean = result["baseline_mean"]
        return {
            "stage": stage,
            "candidate_version": candidate_version,
            "eval_case_count": result["case_count"],
            "eval_mean_score": mean,
            "eval_baseline_mean": base_mean,
            "effect_size": result["effect_size"],
            "golden_pass_rate": mean,
            "quality_ratio": 1.0 if base_mean is None or base_mean == 0 else mean / max(base_mean, 1e-6),
        }

    def evaluate_with_canary(
        self,
        stage: str,
        run_fn: Callable[[Dict[str, Any]], Any],
        baseline_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
        traffic_percentage: float = 0.1,
        observation_days: int = 7,
    ) -> Dict[str, Any]:
        """金丝雀 A/B 测试：在真实流量上对比候选 vs 基线。

        返回金丝雀测试配置，实际部署由 CanaryABTest 管理。
        """
        # 编译候选
        compile_result = self.compile_candidate(stage)
        candidate_version = compile_result["version"]

        # 创建金丝雀测试配置
        canary_config = {
            "stage": stage,
            "candidate_version": candidate_version,
            "baseline_version": candidate_version - 1,
            "traffic_percentage": traffic_percentage,
            "observation_days": 7,
            "auto_promote": True,
        }

        return {
            "stage": stage,
            "candidate_version": candidate_version,
            "canary_config": canary_config,
            "message": f"Canary test configured for {stage} v{candidate_version}",
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 晋升/部署
    # ──────────────────────────────────────────────────────────────────────────

    def promote_candidate(
        self,
        stage: str,
        candidate_version: int,
        eval_result: Dict[str, Any],
        auto_deploy: bool = True,
    ) -> Dict[str, Any]:
        """尝试晋升候选 Prompt。

        调用 PromotionGate 进行 4 项门禁裁决。
        """
        from ..feedback.promotion_gate import promote_candidate
        from ..harness.config import get_harness_settings

        get_harness_settings()
        Path("prompts")

        decision = promote_candidate(
            stage=stage,
            candidate_version=candidate_version,
            golden_dataset_pass_rate=eval_result.get("golden_pass_rate", 0),
            quality_score_ratio=eval_result.get("quality_ratio", 1.0),
            format_compliance_rate=self._check_format_compliance(stage, candidate_version),
            human_preference_score=self._get_human_preference(stage, candidate_version),
            prompts_dir=Path("prompts"),
            auto_deploy=auto_deploy,
        )

        return {
            "passed": decision.passed,
            "deployed": decision.deployed,
            "failed_criteria": decision.failed_criteria,
            "candidate_version": candidate_version,
        }

    def rollback_prompt(self, stage: str, target_version: int) -> bool:
        """回滚到指定版本。"""
        from ..feedback.deploy import rollback_prompt

        success = rollback_prompt(stage, target_version, Path("prompts"))
        return success


# ──────────────────────────────────────────────────────────────────────────────
# 高层编排：完整迭代周期
# ──────────────────────────────────────────────────────────────────────────────


class PromptEvolutionOrchestrator:
    """Prompt 进化编排器：串联编译→评估→晋升→部署的完整流程。"""

    def __init__(self):
        self.engine = PromptEvolutionEngine()

    def run_full_cycle(
        self,
        stage: str,
        run_fn: Callable[[Dict[str, Any]], Any],
        baseline_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
        k: int = 3,
        auto_deploy: bool = True,
    ) -> Dict[str, Any]:
        """运行完整的 Prompt 进化周期：编译 → 评估 → 晋升 → 部署。"""

        # 1. 编译候选
        compile_result = self.engine.compile_candidate(stage, k=3)
        candidate_version = compile_result["version"]
        logger.info(f"[Orchestrator] {stage}: compiled candidate v{candidate_version}")

        # 2. 评估
        eval_result = self.engine.evaluate_candidate(stage, run_fn, baseline_fn=None, k=3)
        logger.info(f"[Orchestrator] {stage}: eval pass_rate={eval_result.get('golden_pass_rate', 0):.3f}")

        # 3. 晋升决策
        promote_result = self.promote_candidate(stage, candidate_version, eval_result)
        logger.info(f"[Orchestrator] {stage}: promoted={promote_result['deployed']}, passed={promote_result['passed']}")

        return {
            "stage": stage,
            "candidate_version": candidate_version,
            "eval_result": eval_result,
            "promote_result": promote_result,
        }

    def run_batch_cycle(
        self,
        stages: Optional[List[str]] = None,
        run_fns: Optional[Dict[str, Callable]] = None,
        baseline_fns: Optional[Dict[str, Callable]] = None,
    ) -> List[Dict[str, Any]]:
        """批量跑多个 stage 的完整迭代周期。"""
        stages = stages or ["extract", "analyze", "annotate", "edit", "judge", "translate"]
        run_fns = run_fns or {}
        baseline_fns = baseline_fns or {}

        results = []
        for stage in stages:
            run_fn = run_fns.get(stage, lambda inp, _s=stage: {"status": "mock", "stage": _s})
            baseline_fn = baseline_fns.get(stage)
            result = self.run_full_cycle(stage, run_fn, baseline_fn)
            results.append(result)

        return results


# ──────────────────────────────────────────────────────────────────────────────
# 便捷入口
# ──────────────────────────────────────────────────────────────────────────────


def run_prompt_evolution_cycle(
    stage: str,
    run_fn: Callable[[Dict[str, Any]], Any],
    baseline_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
    k: int = 3,
    auto_deploy: bool = True,
) -> Dict[str, Any]:
    """便捷入口：运行单个 stage 的完整 Prompt 进化周期。"""
    orchestrator = PromptEvolutionOrchestrator()
    return orchestrator.run_full_cycle(stage, run_fn, baseline_fn, auto_deploy=auto_deploy)


def compile_candidate_prompt(stage: str, k: int = 3) -> Dict[str, Any]:
    """便捷入口：仅编译候选 Prompt。"""
    from ..feedback.prompt_compiler import write_candidate_prompt

    cp = write_candidate_prompt(stage, k=k, prompts_root=DEFAULT_PROMPTS_DIR)
    return {
        "version": cp.version,
        "stage": stage,
        "exemplars_count": len(cp.exemplars),
        "selection_note": cp.selection_note,
        "template_path": cp.prompt_dir,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 导出
# ──────────────────────────────────────────────────────────────────────────────

__all__ = [
    "PromptEvolutionEngine",
    "PromptEvolutionOrchestrator",
    "run_prompt_evolution_cycle",
    "compile_candidate_prompt",
]
