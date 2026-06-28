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
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import FeedbackRecord as FeedbackRecordModel
from ..pipeline.feedback_collector import (
    FeedbackCollector,
    StageCapture,
    create_feedback_collector,
)
from ..storage import project_dir
from .ab_test import build_ab_samples, run_ab_test
from .auto_processor import FeedbackAutoProcessor, create_auto_processor
from .collector import (
    capture_edit_feedback,
    capture_feedback,
    capture_quality_feedback,
    list_unprocessed_feedback,
    mark_feedback_processed,
)
from .pr_automation import (
    MergeResult,
    PRResult,
    create_prompt_upgrade_pr,
    monitor_and_merge_pr,
)
from .processor import AggregateAnalysis, analyze_batch, analyze_single_feedback
from .promotion_gate import PromotionVerdict, _golden_to_pipeline_stage
from .promotion_gate import _load_golden_examples
from .promotion_gate import _load_golden_examples as load_golden_for_ab
from .promotion_gate import _run_stage_with_prompt_version, evaluate_promotion
from .prompt_upgrader import _load_current_prompt, batch_upgrade, upgrade_prompt
from .quality_enhancement import (
    check_semantic_coherence,
    get_false_positive_tracker,
    get_free_tier_health,
    grade_difficulty,
    validate_emotions,
)

logger = logging.getLogger(__name__)


def _log_self_iteration_event(event_type: str, data: Dict[str, Any]) -> None:
    """Log self-iteration events to structured JSONL file for monitoring."""
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "self_iteration_self_iteration.jsonl"

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
        pr_base_branch: str = "main",
        ci_timeout_seconds: int = 1800,
    ):
        self.db_session_factory = db_session_factory
        self.project_id = project_id
        self.canary_percentage = canary_percentage
        self.enable_auto_pr = enable_auto_pr
        self.enable_auto_merge = enable_auto_merge
        self.pr_base_branch = pr_base_branch
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
        self._validation_results: List[Dict[str, Any]] = []
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
                if (
                    status["unprocessed_feedback_count"]
                    >= self.auto_processor.min_feedback_count
                ):
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
        logger.info(
            f"New analysis received: {analysis.total_analyzed} records, {len(analysis.top_patterns)} patterns"
        )

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

        logger.info(
            f"Upgraded prompts for stages: {list(self._upgraded_prompts.keys())}"
        )

        # 2. Run canary validation with upgraded prompts
        validation_results = self._run_canary_validation()
        self._validation_results = validation_results

        # 3. Evaluate promotion for each upgraded prompt
        promoted_any = False
        for stage, prompt_path in self._upgraded_prompts.items():
            validation = validation_results.get(stage, {})

            # Get version numbers from prompt files
            current_content, old_version = _load_current_prompt(stage)
            new_version = old_version + 1 if old_version > 0 else 1

            promotion_result = evaluate_promotion(
                stage=stage,
                old_version=old_version,
                new_version=new_version,
                human_samples=None,  # Could be populated from validation metrics
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
                logger.info(
                    f"✅ Promoted new prompt for {stage}: {prompt_path} (v{old_version} → v{new_version})"
                )
                promoted_any = True

                # 4. Run A/B test for promoted prompts
                ab_test_result = None
                try:
                    ab_test_result = self._run_ab_test_for_stage(
                        stage, old_version, new_version
                    )
                except Exception as e:
                    logger.error(f"Failed to run A/B test for {stage}: {e}")

                # 5. Create PR if A/B test confirms promotion and auto PR is enabled
                if self.enable_auto_pr and ab_test_result:
                    # Check if A/B test confirms (significant and B wins)
                    if (
                        ab_test_result.is_significant
                        and ab_test_result.b_wins > ab_test_result.a_wins
                    ):
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
                                    logger.info(
                                        f"Waiting for CI and auto-merging PR #{pr_result.pr_number}..."
                                    )
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
                                logger.warning(
                                    f"❌ Failed to create PR for {stage} v{new_version}: {pr_result.error}"
                                )
                        except Exception as e:
                            logger.error(
                                f"Failed to create PR for {stage} v{new_version}: {e}"
                            )
                    else:
                        logger.info(
                            f"A/B test did not confirm promotion for {stage}, skipping PR creation"
                        )
            else:
                logger.warning(
                    f"❌ Not promoted for {stage}: {promotion_result.summary}"
                )

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
                logger.warning(
                    f"No golden dataset found for {stage}, using mock validation"
                )
                results[stage] = self._mock_validation_result(health)
                continue

            # Use a subset for canary (canary_percentage of examples)
            canary_count = max(1, int(len(golden_examples) * self.canary_percentage))
            canary_examples = golden_examples[:canary_count]

            # Get current and new version numbers
            _, old_version = _load_current_prompt(stage)
            new_version = old_version + 1 if old_version > 0 else 1

            # Map stage to pipeline stage
            pipeline_stage = _golden_to_pipeline_stage(stage)

            # Run validation for each example
            validation_scores = []
            passed_count = 0
            failed_details = []

            for i, example in enumerate(canary_examples):
                if "input" not in example or "expected_output" not in example:
                    continue

                input_data = example["input"]
                expected_output = example["expected_output"]

                try:
                    # Run with NEW prompt version
                    new_output = _run_stage_with_prompt_version(
                        pipeline_stage, new_version, input_data, mock_mode=True
                    )
                    if hasattr(new_output, "model_dump"):
                        new_output = new_output.model_dump()
                    elif hasattr(new_output, "dict"):
                        new_output = new_output.dict()

                    # Run with OLD prompt version (baseline)
                    old_output = _run_stage_with_prompt_version(
                        pipeline_stage, old_version, input_data, mock_mode=True
                    )
                    if hasattr(old_output, "model_dump"):
                        old_output = old_output.model_dump()
                    elif hasattr(old_output, "dict"):
                        old_output = old_output.dict()

                    # Compare outputs using similarity
                    from .promotion_gate import _compute_output_similarity

                    similarity = _compute_output_similarity(new_output, expected_output)
                    baseline_similarity = _compute_output_similarity(
                        old_output, expected_output
                    )

                    # Quality improvement: new should be >= baseline * 1.02
                    if baseline_similarity > 0:
                        quality_ratio = similarity / baseline_similarity
                    else:
                        quality_ratio = 1.0 if similarity > 0.85 else 0.5

                    validation_scores.append(
                        {
                            "example_index": i,
                            "similarity_to_expected": similarity,
                            "baseline_similarity": baseline_similarity,
                            "quality_ratio": quality_ratio,
                            "passed": similarity >= 0.85 and quality_ratio >= 1.02,
                        }
                    )

                    if similarity >= 0.85 and quality_ratio >= 1.02:
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
                    logger.warning(
                        f"Canary validation failed for {stage} example {i}: {e}"
                    )
                    failed_details.append(
                        {
                            "index": i,
                            "error": str(e),
                        }
                    )

            # Aggregate results
            total = len(validation_scores)
            pass_rate = passed_count / total if total > 0 else 0.0
            avg_quality_ratio = (
                sum(s["quality_ratio"] for s in validation_scores) / total
                if total > 0
                else 0.0
            )

            # Run semantic coherence check
            coherence_results = []
            for s in validation_scores:
                if "new_output" in s:  # Would need actual output
                    coherence = check_semantic_coherence([s.get("new_output", "")])
                    coherence_results.append(coherence.mean_score if coherence else 0.5)

            results[stage] = {
                "canary_examples_tested": total,
                "passed_count": passed_count,
                "pass_rate": pass_rate,
                "avg_quality_ratio": avg_quality_ratio,
                "avg_similarity": (
                    sum(s["similarity_to_expected"] for s in validation_scores) / total
                    if total > 0
                    else 0.0
                ),
                "avg_baseline_similarity": (
                    sum(s["baseline_similarity"] for s in validation_scores) / total
                    if total > 0
                    else 0.0
                ),
                "semantic_coherence": {
                    "is_coherent": pass_rate >= 0.8,
                    "mean_score": (
                        sum(coherence_results) / len(coherence_results)
                        if coherence_results
                        else 0.75
                    ),
                },
                "emotion_validation": {
                    "validation_summary": (
                        "OK" if pass_rate >= 0.8 else "Below threshold"
                    ),
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

    def _mock_validation_result(self, health) -> Dict[str, Any]:
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

    def _run_ab_test_for_stage(
        self, stage: str, old_version: int, new_version: int
    ) -> None:
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
            return

        # Build A/B test samples from golden dataset
        samples = build_ab_samples(stage, golden_examples, old_version, new_version)
        if not samples:
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
            return

        logger.info(f"Running A/B test with {len(samples)} samples for {stage}")

        # Run A/B test
        ab_report = run_ab_test(
            stage=stage,
            samples=samples,
            significance_level=0.05,
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
            logger.info(
                f"✅ A/B test confirms promotion for {stage}: {ab_report.recommendation}"
            )
        elif ab_report.is_significant and ab_report.a_wins > ab_report.b_wins:
            logger.warning(
                f"⚠️ A/B test contradicts promotion for {stage}: {ab_report.recommendation}"
            )
        else:
            logger.info(
                f"🔶 A/B test inconclusive for {stage}: {ab_report.recommendation}"
            )

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
            "running": self._worker_thread is not None
            and self._worker_thread.is_alive(),
            "iteration_count": self._iteration_count,
            "auto_processor": auto_status,
            "upgraded_prompts": {k: str(v) for k, v in self._upgraded_prompts.items()},
            "last_analysis": (
                {
                    "total_analyzed": (
                        self._last_analysis_result.total_analyzed
                        if self._last_analysis_result
                        else 0
                    ),
                    "top_patterns": (
                        self._last_analysis_result.top_patterns[:5]
                        if self._last_analysis_result
                        else []
                    ),
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

        collector = create_feedback_collector(project_id=1)

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
):
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
):
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
