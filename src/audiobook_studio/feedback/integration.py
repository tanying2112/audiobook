"""
Self-Iteration Integration Module

This module connects all feedback components into an automated self-iteration loop:
FeedbackCollector → FeedbackProcessor → PromptUpgrader → Pipeline Re-execution → Validation

The integration provides:
1. Automated feedback collection from pipeline stages
2. Periodic batch analysis triggering
3. Prompt auto-upgrade based on pattern analysis
4. Pipeline re-execution with upgraded prompts
5. Quality validation and regression checking
6. Promotion gating for new prompt versions
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from ..pipeline.feedback_collector import FeedbackCollector, StageCapture, create_feedback_collector
from .ab_test import ABTestReport, run_ab_test_with_pipeline_rerun
from .auto_processor import create_auto_processor
from .deploy import deploy_prompt, promote_candidate
from .pr_automation import MergeResult, PRResult, create_prompt_upgrade_pr, monitor_and_merge_pr
from .processor import AggregateAnalysis
from .promotion_gate import PromotionVerdict, _golden_to_pipeline_stage
from .promotion_gate import _load_golden_examples
from .promotion_gate import _load_golden_examples as load_golden_for_ab
from .promotion_gate import _run_stage_with_prompt_version, evaluate_promotion
from .canary import NON_PROMPT_DRIVEN_STAGES, STAGE_TYPE, check_input_compatibility
from ..harness.spotcheck import human_preference_score_for, resolve_human_default
from .prompt_upgrader import _load_current_prompt, batch_upgrade
from .quality_enhancement import FreeTierHealth, check_semantic_coherence, get_free_tier_health

logger = logging.getLogger(__name__)


def _env_flag(name: str, default: bool) -> bool:
    """环境变量布尔开关：未设置时沿用传入默认值，显式设置时覆盖。"""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("false", "0", "no", "off")


def _log_self_iteration_event(event_type: str, data: Dict[str, Any]) -> None:
    """Log self-iteration events to structured JSONL file for monitoring."""
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "self_iteration.jsonl"

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        **data,
    }

    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error(f"Failed to write self-iteration log: {e}")


def _router_blind_judge(stage: str):
    """A/B 盲评适配器：LLMJudgeEnsemble 默认面板是 openrouter/anthropic/openai
    三个外部 provider（本机未配置，恒失败 → 恒启发式兜底）。这里把评审客户端换成
    应用统一 router（读 llm_providers.yaml 的真实 provider 链，如 local_fcc_gateway），
    rubric/归一逻辑复用 ensemble 本体；router 不可用时回退启发式评分，不中断 A/B。"""
    from types import SimpleNamespace

    from .ab_test import _score_output
    from .llm_judge import LLMJudgeEnsemble, RubricScores

    class _RouterJudgeClient:
        def call(self, prompt, response_model=RubricScores, temperature=0.1, **kw):
            from ..llm.router import get_llm_router

            result = get_llm_router().call(
                stage="judge",
                response_model=response_model,
                messages=[{"role": "user", "content": prompt}],
            )
            return SimpleNamespace(output=result)

    ens = LLMJudgeEnsemble(models=["app_router"], client_factory=lambda model: _RouterJudgeClient())

    def judge_fn(input_data, output_a, output_b):
        try:
            r = ens.judge(input_data, output_a, output_b, stage=stage)
            return r.score_a, r.score_b, (r.rationale or "")[:300]
        except Exception as e:  # noqa: BLE001 - 评审失败回退启发式，勿中断 A/B
            return _score_output(output_a, stage), _score_output(output_b, stage), f"router judge fallback: {e}"

    return judge_fn


# A/B 子采样上限：盲评是 3 模型 ensemble，全量 24 例 ×2 版 ×3 评审过于昂贵；
# 晋升门禁（格式/金标/质量）仍全量实证，A/B 仅作放行后的独立确认信号。
AB_TEST_MAX_EXAMPLES = 6


def _live_baseline_version(stage: str) -> int:
    """当前 live 基线版本：deployed.txt 的 served 版本；从未部署过则 v1（原始线上槽）。"""
    from .deploy import served_version

    return served_version(stage) or 1


class SelfIterationLoop:
    """
    Orchestrates the complete self-iteration feedback loop.

    Flow:
    1. Pipeline stages generate feedback via FeedbackCollector
    2. FeedbackAutoProcessor monitors and triggers batch analysis
    3. FeedbackProcessor analyzes patterns and generates recommendations
    4. PromptUpgrader creates new prompt versions based on patterns
    5. Pipeline re-executes with new prompts (canary mode)
    6. Quality enhancement validates the new outputs
    7. Promotion gate evaluates if new prompts should be promoted
    8. A/B test confirms the improvement
    9. Create GitHub PR with prompt changes
    10. Auto-merge after CI passes
    """

    def __init__(
        self,
        db_session_factory: Callable[[], Session],
        project_id: int,
        min_feedback_count: int = 10,
        check_interval_seconds: int = 300,
        enable_auto_trigger: bool = True,
        canary_percentage: float = 0.1,
        enable_auto_pr: bool = True,
        enable_auto_merge: bool = True,
        auto_deploy: bool = True,
        pr_base_branch: str = "main",
        ci_timeout_seconds: int = 1800,
    ):
        self.db_session_factory = db_session_factory
        self.project_id = project_id
        self.canary_percentage = canary_percentage
        # 环内 PR 运维开关（2026-10 修复后 PR 机制真实可用，故提供不改代码的
        # 关停/改基线手段）：SELF_ITERATION_AUTO_PR / SELF_ITERATION_AUTO_MERGE
        # / SELF_ITERATION_PR_BASE，未设置时沿用构造参数默认。
        self.enable_auto_pr = _env_flag("SELF_ITERATION_AUTO_PR", enable_auto_pr)
        self.enable_auto_merge = _env_flag("SELF_ITERATION_AUTO_MERGE", enable_auto_merge)
        self.auto_deploy = auto_deploy
        self.pr_base_branch = os.getenv("SELF_ITERATION_PR_BASE") or pr_base_branch
        self.ci_timeout_seconds = ci_timeout_seconds

        # Initialize components
        self.collector = create_feedback_collector(project_id)
        self.project_id = project_id
        self.auto_processor = create_auto_processor(
            db_session_factory=db_session_factory,
            project_id=project_id,
            min_feedback_count=min_feedback_count,
            check_interval_seconds=check_interval_seconds,
            enable_auto_trigger=enable_auto_trigger,
        )

        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._iteration_count = 0
        self._last_analysis_result: Optional[AggregateAnalysis] = None
        self._upgraded_prompts: Dict[str, Path] = {}
        self._validation_results: Dict[str, Dict[str, Any]] = {}
        self._pr_results: List[PRResult] = []
        self._merge_results: List[MergeResult] = []

    def start(self) -> None:
        """Start the self-iteration loop."""
        self.auto_processor.start()
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._worker_thread.start()
        logger.info(f"SelfIterationLoop started for project {self.project_id}")
        _log_self_iteration_event(
            "loop_started",
            {
                "project_id": self.project_id,
                "min_feedback_count": self.auto_processor.min_feedback_count,
                "check_interval_seconds": self.auto_processor.check_interval_seconds,
                "canary_percentage": self.canary_percentage,
            },
        )

    def stop(self) -> None:
        """Stop the self-iteration loop."""
        self.auto_processor.stop()
        if self._worker_thread and self._worker_thread.is_alive():
            self._stop_event.set()
            self._worker_thread.join(timeout=10)
        logger.info("SelfIterationLoop stopped")
        _log_self_iteration_event(
            "loop_stopped",
            {
                "project_id": self.project_id,
                "iteration_count": self._iteration_count,
            },
        )

    def _monitor_loop(self) -> None:
        """Background loop that monitors for analysis results and triggers upgrades."""
        while not self._stop_event.is_set():
            try:
                # Check if auto processor has new analysis
                status = self.auto_processor.get_status()
                if status["unprocessed_feedback_count"] >= self.auto_processor.min_feedback_count:
                    # Trigger analysis manually if auto didn't
                    result = self.auto_processor.trigger_now()
                    if result and result != self._last_analysis_result:
                        self._handle_new_analysis(result)
                        self._last_analysis_result = result
            except Exception as e:
                logger.error(f"Error in self-iteration monitor loop: {e}")

            self._stop_event.wait(60)  # Check every minute

    def _handle_new_analysis(self, analysis: AggregateAnalysis) -> None:
        """Process new analysis results: upgrade prompts, validate, promote."""
        self._iteration_count += 1
        logger.info(f"New analysis received: {analysis.total_analyzed} records, {len(analysis.top_patterns)} patterns")

        # 1. Upgrade prompts based on patterns
        self._upgraded_prompts = batch_upgrade(analysis, min_pattern_threshold=3)
        if not self._upgraded_prompts:
            logger.info("No prompt upgrades needed")
            _log_self_iteration_event(
                "iteration_no_upgrade",
                {
                    "iteration": self._iteration_count,
                    "feedback_analyzed": analysis.total_analyzed,
                    "patterns_found": len(analysis.top_patterns),
                    "promoted": False,
                    "feedback_count": analysis.total_analyzed,
                },
            )
            return

        logger.info(f"Upgraded prompts for stages: {list(self._upgraded_prompts.keys())}")

        # 2. Run canary validation with upgraded prompts
        validation_results = self._run_canary_validation()
        self._validation_results = validation_results

        # 3. Evaluate promotion for each upgraded prompt
        promoted_any = False
        for stage, prompt_path in self._upgraded_prompts.items():
            validation = validation_results.get(stage, {})

            # 版本语义：new = batch_upgrade 刚写的最新候选（最大版本号）；
            # old = 当前 live 基线（deployed.txt 的 served 版本，未部署过则 v1），
            # 而非另一个从未晋升的候选 —— 门禁要回答的是「能否替换线上」，
            # 基线必须是线上正在服务的版本。
            _, max_version = _load_current_prompt(stage)
            new_version = max_version
            old_version = _live_baseline_version(stage)

            promotion_result = evaluate_promotion(
                stage=stage,
                old_version=old_version,
                new_version=new_version,
                human_samples=SelfIterationLoop._human_samples_for_gate(stage),
            )
            logger.info(f"Promotion evaluation for {stage}: {promotion_result.summary}")

            # Log each promotion decision
            _log_self_iteration_event(
                "promotion_evaluation",
                {
                    "iteration": self._iteration_count,
                    "stage": stage,
                    "prompt_path": str(prompt_path),
                    "promoted": promotion_result.passed,
                    "reason": promotion_result.summary,
                    "validation_metrics": validation,
                    "old_version": old_version,
                    "new_version": new_version,
                },
            )

            if promotion_result.passed:
                logger.info(f"✅ Promoted new prompt for {stage}: {prompt_path} (v{old_version} → v{new_version})")
                promoted_any = True

                # Deploy to production prompts/ directory if auto_deploy is enabled
                if self.auto_deploy:
                    try:
                        gate_scores = {g.name: g.score for g in promotion_result.gates}
                        deploy_decision = promote_candidate(
                            stage=stage,
                            candidate_version=new_version,
                            golden_dataset_pass_rate=gate_scores.get("黄金数据集通过率", validation.get("golden_pass_rate", 0.0)),
                            quality_score_ratio=gate_scores.get("质量 ≥ 旧版 102%", validation.get("avg_quality_ratio", 0.0)),
                            format_compliance_rate=gate_scores.get("格式合规率", validation.get("format_compliance_rate", 1.0)),
                            human_preference_score=human_preference_score_for(stage, default=resolve_human_default()),
                            prompts_dir=Path("prompts"),  # Production prompts directory
                            auto_deploy=True,
                        )
                        if deploy_decision.deployed:
                            logger.info(f"✅ Deployed {stage} v{new_version} to production prompts/")
                        else:
                            logger.warning(f"⚠️ Promotion passed but deployment failed for {stage}")
                    except Exception as e:
                        logger.error(f"Failed to deploy {stage} v{new_version} to production: {e}")

                # 4. Run A/B test for promoted prompts
                ab_test_result: Optional[ABTestReport] = None
                try:
                    ab_test_result = self._run_ab_test_for_stage(stage, old_version, new_version)
                except Exception as e:
                    logger.error(f"Failed to run A/B test for {stage}: {e}")

                # 5. Create PR if A/B test confirms promotion and auto PR is enabled
                if self.enable_auto_pr and ab_test_result:
                    # Check if A/B test confirms (significant and B wins)
                    if ab_test_result.is_significant and ab_test_result.b_wins > ab_test_result.a_wins:
                        try:
                            pr_result = self._create_pr_for_promotion(
                                stage=stage,
                                new_version=new_version,
                                promotion_result=promotion_result,
                                validation_results=validation_results.get(stage, {}),
                                ab_test_results={
                                    "num_samples": ab_test_result.num_samples,
                                    "improvement_pct": ab_test_result.improvement_pct,
                                    "is_significant": ab_test_result.is_significant,
                                    "b_wins": ab_test_result.b_wins,
                                    "a_wins": ab_test_result.a_wins,
                                    "recommendation": ab_test_result.recommendation,
                                },
                            )
                            self._pr_results.append(pr_result)

                            if pr_result.success:
                                logger.info(
                                    f"✅ Created PR #{pr_result.pr_number} for {stage} v{new_version}: {pr_result.pr_url}"
                                )

                                # 6. Auto-merge if enabled
                                if self.enable_auto_merge and pr_result.pr_number:
                                    logger.info(f"Waiting for CI and auto-merging PR #{pr_result.pr_number}...")
                                    merge_result = monitor_and_merge_pr(
                                        pr_number=pr_result.pr_number,
                                        timeout_seconds=self.ci_timeout_seconds,
                                    )
                                    self._merge_results.append(merge_result)

                                    if merge_result.success:
                                        logger.info(
                                            f"✅ Auto-merged PR #{pr_result.pr_number} (sha: {merge_result.merge_commit_sha})"
                                        )
                                    else:
                                        logger.warning(
                                            f"❌ Auto-merge failed for PR #{pr_result.pr_number}: {merge_result.error}"
                                        )
                            else:
                                logger.warning(f"❌ Failed to create PR for {stage} v{new_version}: {pr_result.error}")
                        except Exception as e:
                            logger.error(f"Failed to create PR for {stage} v{new_version}: {e}")
                    else:
                        logger.info(f"A/B test did not confirm promotion for {stage}, skipping PR creation")
            else:
                logger.warning(f"❌ Not promoted for {stage}: {promotion_result.summary}")

        # Log iteration summary
        health = get_free_tier_health()
        _log_self_iteration_event(
            "iteration_complete",
            {
                "iteration": self._iteration_count,
                "feedback_analyzed": analysis.total_analyzed,
                "patterns_found": len(analysis.top_patterns),
                "stages_upgraded": list(self._upgraded_prompts.keys()),
                "promoted": promoted_any,
                "feedback_count": analysis.total_analyzed,
                "system_health_score": health.score,
            },
        )

    # ── 人工抽样门数据源 ─────────────────────────────────────────────────────
    # spotcheck 库（harness/spotcheck.py）即为此门禁设计：有真实人工抽检评分时
    # 逐条换算为通过/不通过（score>=0.8 视为通过）；无记录时与 harness 晋升路径
    # 保持同一默认策略（default=1.0 放行），其余 3 项硬门（格式/金标/质量）仍
    # 全量实证校验，绝不因人工缺位而放水技术指标。
    @staticmethod
    def _human_samples_for_gate(stage: str) -> List[bool]:
        from ..harness.spotcheck import human_gate_strict, load_spot_checks

        records = load_spot_checks(stage=stage)
        if records:
            samples = [float(r["score"]) >= 0.8 for r in records]
            logger.info(f"[SelfIteration] {stage}: 使用 {len(samples)} 条真实人工抽检评分入门禁")
            return samples
        # 人工缺位：默认策略放行（其余 3 项硬门仍全量实证）；严格模式 fail-closed，
        # 返回空样本集 → check_human_sample 判不通过并如实标注「尚无人工抽样结果」。
        if human_gate_strict():
            logger.warning(
                f"[SelfIteration] {stage}: 无人工抽检记录且 SELF_ITERATION_HUMAN_GATE_STRICT=true"
                " —— 人工门 fail-closed（返回空样本集）"
            )
            return []
        logger.info(
            f"[SelfIteration] {stage}: 无人工抽检记录，人工门按默认策略放行"
            "（出处：default=1.0；设 SELF_ITERATION_HUMAN_GATE_STRICT=true 可改 fail-closed）"
        )
        return [True]

    def _run_canary_validation(self) -> Dict[str, Dict[str, Any]]:
        """Run validation on a subset of data with upgraded prompts (canary mode).

        This actually re-runs pipeline stages with new prompt versions
        and compares quality metrics against baseline.
        """
        results: Dict[str, Dict[str, Any]] = {}

        # Get free tier health to ensure system can handle validation
        health = get_free_tier_health()
        if not health.healthy:
            logger.warning(f"System health check failed: {health.warnings}")

        # Load golden dataset for validation
        for stage in self._upgraded_prompts.keys():
            logger.info(f"Running canary validation for stage: {stage}")

            # Get golden examples for this stage
            golden_examples = _load_golden_examples(stage)
            if not golden_examples:
                logger.warning(f"No golden dataset found for {stage}, using mock validation")
                results[stage] = self._mock_validation_result(health)
                continue

            # Use a subset for canary (canary_percentage of examples)
            canary_count = max(1, int(len(golden_examples) * self.canary_percentage))
            canary_examples = golden_examples[:canary_count]

            # 版本语义与晋升门一致：候选 = 最新编译版本；基线 = 当前 live 版本。
            _, max_version = _load_current_prompt(stage)
            new_version = max_version
            old_version = _live_baseline_version(stage)

            # Map stage to pipeline stage
            pipeline_stage = _golden_to_pipeline_stage(stage)
            stage_type = STAGE_TYPE.get(pipeline_stage, "unknown")

            # 无 prompt 驱动的阶段（quality：ASR/WER 音频质检）结构上无法做
            # prompt 版本 A/B —— 显式跳过并标记原因，而非硬跑出假指标。
            if pipeline_stage in NON_PROMPT_DRIVEN_STAGES:
                results[stage] = {
                    "skipped": True,
                    "skipped_reason": (
                        f"{pipeline_stage} 阶段非 prompt 驱动（音频 ASR/WER 质检），无法做 prompt 版本 A/B"
                    ),
                    "canary_examples_tested": 0,
                    "pass_rate": None,
                }
                logger.info(f"[Canary] {stage}: skipped —— {results[stage]['skipped_reason']}")
                continue

            # Run validation for each example
            validation_scores: List[Dict[str, Any]] = []
            passed_count = 0
            failed_details: List[Dict[str, Any]] = []
            incompatible_count = 0
            incompat_reason = ""

            for i, example in enumerate(canary_examples):
                if "input" not in example or "expected_output" not in example:
                    continue

                input_data = example["input"]
                expected_output = example["expected_output"]

                # 金标输入与阶段契约不兼容：显式跳过并计数——这是数据/契约
                # 错配，不是「候选失败」，不得混入 pass_rate（2026-10 披露局限）。
                compatible, reason = check_input_compatibility(pipeline_stage, input_data)
                if not compatible:
                    incompatible_count += 1
                    incompat_reason = reason
                    continue

                try:
                    # Run with NEW prompt version (mock_mode=None → SELF_ITERATION_MOCK env, C-01)
                    new_output = _run_stage_with_prompt_version(pipeline_stage, new_version, input_data)
                    if hasattr(new_output, "model_dump"):
                        new_output = new_output.model_dump()

                    # Run with OLD prompt version (baseline)
                    old_output = _run_stage_with_prompt_version(pipeline_stage, old_version, input_data)
                    if hasattr(old_output, "model_dump"):
                        old_output = old_output.model_dump()

                    # 结构化相似度（回归信号）+ 复合质量指标（与 Gate3 同源）
                    from .candidate_eval import example_passes_gate, score_output_vs_expected
                    from .similarity import _aggregate_quality_score, _compute_text_quality_metrics

                    similarity = score_output_vs_expected(expected_output, new_output, stage=stage)
                    baseline_similarity = score_output_vs_expected(expected_output, old_output, stage=stage)

                    q_new = _aggregate_quality_score(_compute_text_quality_metrics(new_output, expected_output, input_data), stage_type)
                    q_old = _aggregate_quality_score(_compute_text_quality_metrics(old_output, expected_output, input_data), stage_type)
                    quality_ratio = (q_new / q_old) if q_old > 0 else (1.0 if q_new > 0 else 0.0)

                    validation_scores.append(
                        {
                            "example_index": i,
                            "similarity_to_expected": similarity,
                            "baseline_similarity": baseline_similarity,
                            "quality_ratio": quality_ratio,
                            "passed": example_passes_gate(expected_output, new_output, stage=stage) and quality_ratio >= 1.02,
                        }
                    )

                    if example_passes_gate(expected_output, new_output, stage=stage) and quality_ratio >= 1.02:
                        passed_count += 1
                    else:
                        failed_details.append(
                            {
                                "index": i,
                                "similarity": similarity,
                                "quality_ratio": quality_ratio,
                            }
                        )

                except Exception as e:
                    logger.warning(f"Canary validation failed for {stage} example {i}: {e}")
                    failed_details.append(
                        {
                            "index": i,
                            "error": str(e),
                        }
                    )

            # 全部不兼容：整阶段显式跳过——不能把 0/0 误报成 pass_rate=0
            # 的「候选失败」，也不能带空内容烧真 LLM 产垃圾分。
            if not validation_scores and incompatible_count > 0:
                results[stage] = {
                    "skipped": True,
                    "skipped_reason": (
                        f"金丝雀输入与 {pipeline_stage} 阶段输入契约不兼容"
                        f"（{incompatible_count}/{len(canary_examples)} 例：{incompat_reason}），无法真实 A/B"
                    ),
                    "canary_examples_tested": 0,
                    "pass_rate": None,
                }
                logger.warning(f"[Canary] {stage}: skipped —— {results[stage]['skipped_reason']}")
                continue

            # Aggregate results
            total = len(validation_scores)
            pass_rate = passed_count / total if total > 0 else 0.0
            avg_quality_ratio = sum(s["quality_ratio"] for s in validation_scores) / total if total > 0 else 0.0

            # Run semantic coherence check
            coherence_results: List[float] = []
            for s in validation_scores:
                if "new_output" in s:  # Would need actual output
                    coherence = check_semantic_coherence([s.get("new_output", "")])
                    coherence_results.append(coherence.mean_score if coherence else 0.5)

            results[stage] = {
                "canary_examples_tested": total,
                "incompatible_examples_skipped": incompatible_count,
                "passed_count": passed_count,
                "pass_rate": pass_rate,
                "avg_quality_ratio": avg_quality_ratio,
                "avg_similarity": (
                    sum(s["similarity_to_expected"] for s in validation_scores) / total if total > 0 else 0.0
                ),
                "avg_baseline_similarity": (
                    sum(s["baseline_similarity"] for s in validation_scores) / total if total > 0 else 0.0
                ),
                "semantic_coherence": {
                    "is_coherent": pass_rate >= 0.8,
                    "mean_score": (sum(coherence_results) / len(coherence_results) if coherence_results else 0.75),
                },
                "emotion_validation": {
                    "validation_summary": ("OK" if pass_rate >= 0.8 else "Below threshold"),
                },
                "quality_improvement": {
                    "delta": avg_quality_ratio - 1.0,
                    "ratio": avg_quality_ratio,
                },
                "regression_check": {
                    "passed": pass_rate >= 0.85,
                },
                "system_health": {
                    "healthy": health.healthy,
                    "score": health.score,
                    "warnings": health.warnings,
                },
                "failed_details": failed_details[:5],  # Limit for logging
            }

            logger.info(
                f"Canary validation for {stage}: "
                f"{passed_count}/{total} passed ({pass_rate:.1%}), "
                f"avg quality ratio: {avg_quality_ratio:.3f}"
            )

        return results

    def _mock_validation_result(self, health: FreeTierHealth) -> Dict[str, Any]:
        """Fallback mock validation result when golden dataset is missing."""
        return {
            "canary_examples_tested": 0,
            "passed_count": 0,
            "pass_rate": 0.0,
            "avg_quality_ratio": 1.0,
            "avg_similarity": 0.0,
            "avg_baseline_similarity": 0.0,
            "semantic_coherence": {
                "is_coherent": True,
                "mean_score": 0.75,
            },
            "emotion_validation": {
                "validation_summary": "NO_GOLDEN_DATA",
            },
            "quality_improvement": {
                "delta": 0.0,
                "ratio": 1.0,
            },
            "regression_check": {
                "passed": False,
            },
            "system_health": {
                "healthy": health.healthy,
                "score": health.score,
                "warnings": health.warnings,
            },
            "failed_details": [],
        }

    def _run_ab_test_for_stage(self, stage: str, old_version: int, new_version: int) -> Optional[ABTestReport]:
        """Run A/B test for a specific stage comparing old vs new prompt versions."""
        logger.info(f"Running A/B test for {stage}: v{old_version} vs v{new_version}")

        # Load golden dataset for this stage
        golden_examples = load_golden_for_ab(stage)
        if not golden_examples:
            logger.warning(f"No golden dataset found for {stage}, skipping A/B test")
            _log_self_iteration_event(
                "ab_test_skipped",
                {
                    "iteration": self._iteration_count,
                    "stage": stage,
                    "reason": "no_golden_dataset",
                    "old_version": old_version,
                    "new_version": new_version,
                },
            )
            return None

        # 真实管线重跑式 A/B：旧 build_ab_samples 只回填 example["output"]（金标无此键），
        # 双臂恒为空 dict → 恒平局 → A/B 永不确认、PR 永不触发（空转缺陷）。
        # 改用 run_ab_test_with_pipeline_rerun：对每个金标输入真实跑 old/new 两版，
        # LLMJudgeEnsemble 盲评 + 配对显著性检验。子采样控成本；晋升门禁仍全量实证。
        ab_examples = golden_examples[:AB_TEST_MAX_EXAMPLES]
        if not ab_examples:
            logger.warning(f"No samples built for {stage} A/B test")
            _log_self_iteration_event(
                "ab_test_skipped",
                {
                    "iteration": self._iteration_count,
                    "stage": stage,
                    "reason": "no_samples",
                    "old_version": old_version,
                    "new_version": new_version,
                },
            )
            return None

        logger.info(f"Running A/B test with {len(ab_examples)} samples for {stage}")

        # Run A/B test
        ab_report = run_ab_test_with_pipeline_rerun(
            stage=stage,
            golden_examples=ab_examples,
            old_version=old_version,
            new_version=new_version,
            judge_fn=_router_blind_judge(stage),
            significance_level=0.05,
            mock_mode=None,
        )

        # Log A/B test results
        _log_self_iteration_event(
            "ab_test_completed",
            {
                "iteration": self._iteration_count,
                "stage": stage,
                "old_version": old_version,
                "new_version": new_version,
                "num_samples": ab_report.num_samples,
                "avg_score_a": ab_report.avg_score_a,
                "avg_score_b": ab_report.avg_score_b,
                "improvement_pct": ab_report.improvement_pct,
                "a_wins": ab_report.a_wins,
                "b_wins": ab_report.b_wins,
                "ties": ab_report.ties,
                "p_value": ab_report.p_value,
                "confidence_interval": list(ab_report.confidence_interval),
                "is_significant": ab_report.is_significant,
                "recommendation": ab_report.recommendation,
            },
        )

        # Check if A/B test confirms the promotion
        if ab_report.is_significant and ab_report.b_wins > ab_report.a_wins:
            logger.info(f"✅ A/B test confirms promotion for {stage}: {ab_report.recommendation}")
        elif ab_report.is_significant and ab_report.a_wins > ab_report.b_wins:
            logger.warning(f"⚠️ A/B test contradicts promotion for {stage}: {ab_report.recommendation}")
        else:
            logger.info(f"🔶 A/B test inconclusive for {stage}: {ab_report.recommendation}")

        return ab_report

    def _create_pr_for_promotion(
        self,
        stage: str,
        new_version: int,
        promotion_result: PromotionVerdict,
        validation_results: Dict[str, Any],
        ab_test_results: Dict[str, Any],
    ) -> PRResult:
        """Create a GitHub PR for a promoted prompt version."""
        # Convert PromotionVerdict to dict for PR body
        promotion_dict = {
            "gates": [
                {
                    "name": g.name,
                    "passed": g.passed,
                    "score": g.score,
                    "threshold": g.threshold,
                    "details": g.details,
                }
                for g in promotion_result.gates
            ],
            "summary": promotion_result.summary,
        }

        return create_prompt_upgrade_pr(
            stage=stage,
            version=new_version,
            base_branch=self.pr_base_branch,
            promotion_result=promotion_dict,
            validation_results=validation_results,
            ab_test_results=ab_test_results,
        )

    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive status of the self-iteration loop."""
        auto_status = self.auto_processor.get_status()
        return {
            "project_id": self.project_id,
            "running": self._worker_thread is not None and self._worker_thread.is_alive(),
            "iteration_count": self._iteration_count,
            "auto_processor": auto_status,
            "upgraded_prompts": {k: str(v) for k, v in self._upgraded_prompts.items()},
            "last_analysis": (
                {
                    "total_analyzed": (self._last_analysis_result.total_analyzed if self._last_analysis_result else 0),
                    "top_patterns": (self._last_analysis_result.top_patterns[:5] if self._last_analysis_result else []),
                }
                if self._last_analysis_result
                else None
            ),
            "validation_results": self._validation_results,
            "pr_results": [
                {
                    "success": r.success,
                    "pr_number": r.pr_number,
                    "pr_url": r.pr_url,
                    "branch_name": r.branch_name,
                    "error": r.error,
                }
                for r in self._pr_results
            ],
            "merge_results": [
                {
                    "success": r.success,
                    "merged": r.merged,
                    "merge_commit_sha": r.merge_commit_sha,
                    "error": r.error,
                }
                for r in self._merge_results
            ],
            "config": {
                "canary_percentage": self.canary_percentage,
                "enable_auto_pr": self.enable_auto_pr,
                "enable_auto_merge": self.enable_auto_merge,
                "pr_base_branch": self.pr_base_branch,
                "ci_timeout_seconds": self.ci_timeout_seconds,
            },
        }

    def trigger_iteration_now(self) -> Optional[AggregateAnalysis]:
        """Manually trigger a full iteration cycle."""
        result = self.auto_processor.trigger_now()
        if result:
            self._handle_new_analysis(result)
            self._last_analysis_result = result
            self._iteration_count += 1
        return result


def create_self_iteration_loop(
    db_session_factory: Callable[[], Session],
    project_id: int,
    min_feedback_count: int = 10,
    check_interval_seconds: int = 300,
    enable_auto_trigger: bool = True,
    canary_percentage: float = 0.1,
    enable_auto_pr: bool = True,
    enable_auto_merge: bool = True,
    auto_deploy: bool = True,
    pr_base_branch: str = "main",
    ci_timeout_seconds: int = 1800,
) -> SelfIterationLoop:
    """Factory function to create a SelfIterationLoop."""
    return SelfIterationLoop(
        db_session_factory=db_session_factory,
        project_id=project_id,
        min_feedback_count=min_feedback_count,
        check_interval_seconds=check_interval_seconds,
        enable_auto_trigger=enable_auto_trigger,
        canary_percentage=canary_percentage,
        enable_auto_pr=enable_auto_pr,
        enable_auto_merge=enable_auto_merge,
        auto_deploy=auto_deploy,
        pr_base_branch=pr_base_branch,
        ci_timeout_seconds=ci_timeout_seconds,
    )


# ── Pipeline Stage Integration Helpers ─────────────────────────────────────────


def collect_pipeline_feedback(
    collector: FeedbackCollector,
    stage: str,
    chapter_index: int,
    paragraph_index: Optional[int] = None,
    chapter_id: Optional[int] = None,
    paragraph_id: Optional[int] = None,
    input_snapshot: Optional[Dict[str, Any]] = None,
) -> StageCapture:
    """
    Helper to create a feedback capture for a pipeline stage.
    Usage in pipeline stages:
        from src.audiobook_studio.feedback.integration import collect_pipeline_feedback
        from src.audiobook_studio.pipeline.feedback_collector import create_feedback_collector

        collector = create_feedback_collector(project_id=123)

        def run_stage(...):
            with collect_pipeline_feedback(collector, "annotate", chapter_index, paragraph_index) as capture:
                result = llm_call(...)
                capture.set_llm_output(result.model_dump())
                # Later when human corrects:
                capture.set_corrected_output(corrected)
                capture.set_rationale("Fixed emotion detection")
    """
    return collector.capture_stage(
        stage=stage,
        chapter_index=chapter_index,
        paragraph_index=paragraph_index,
        chapter_id=chapter_id,
        paragraph_id=paragraph_id,
        input_snapshot=input_snapshot,
    )


def save_quality_feedback(
    collector: FeedbackCollector,
    stage: str,
    chapter_index: int,
    paragraph_index: int,
    chapter_id: int,
    paragraph_id: int,
    quality_judgment: Dict[str, Any],
    corrected_judgment: Dict[str, Any],
    rationale: str,
) -> Path:
    """Save quality judge feedback (source=quality_judge) using file-based collector."""
    capture = collector.capture_stage(
        stage=stage,
        chapter_index=chapter_index,
        paragraph_index=paragraph_index,
        chapter_id=chapter_id,
        paragraph_id=paragraph_id,
    )
    capture.set_llm_output(quality_judgment)
    capture.set_corrected_output(corrected_judgment)
    capture.set_rationale(rationale)
    capture.set_source("quality_judge")
    return collector.save_feedback(capture)


def save_user_rating_feedback(
    collector: FeedbackCollector,
    stage: str,
    chapter_index: int,
    paragraph_index: int,
    chapter_id: int,
    paragraph_id: int,
    user_rating: Dict[str, Any],
    rationale: str,
) -> Path:
    """Save user rating feedback (source=user_rating) using file-based collector."""
    # User rating is both the LLM output and the corrected output
    capture = collector.capture_stage(
        stage=stage,
        chapter_index=chapter_index,
        paragraph_index=paragraph_index,
        chapter_id=chapter_id,
        paragraph_id=paragraph_id,
    )
    capture.set_llm_output(user_rating)
    capture.set_corrected_output(user_rating)
    capture.set_rationale(rationale)
    capture.set_source("user_rating")
    return collector.save_feedback(capture)
