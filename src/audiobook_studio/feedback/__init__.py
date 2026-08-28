"""
feedback 模块初始化

提供反馈收集、差异分析、Prompt 自动升级、门禁检查、
A/B 测试、Kill Switch 降级、质量增强等功能。
"""

from typing import Any

from .ab_test import blind_evaluate, build_ab_samples, run_ab_test
from .ab_test_manager import ABTestConfig, ABTestManager, ABTestResult
from .auto_processor import FeedbackAutoProcessor, create_auto_processor, run_feedback_analysis_cli
from .collector import (
    capture_edit_feedback,
    capture_feedback,
    capture_quality_feedback,
    list_unprocessed_feedback,
    mark_feedback_processed,
)
from .critics import (  # noqa: F401
    DEFAULT_CALIBRATION_SAMPLES,
    BaseCritic,
    CalibrationResult,
    CalibrationSample,
    CriticEnsemble,
    CriticEnsembleEvaluator,
    CriticResult,
    CriticType,
    CriticVerdict,
    ObjectiveCritic,
    SemanticCritic,
    StructuralCritic,
    SyntheticCritic,
    create_synthetic_critic,
)
from .integration import (
    SelfIterationLoop,
    collect_pipeline_feedback,
    create_self_iteration_loop,
    save_quality_feedback,
    save_user_rating_feedback,
)
from .kill_switch import DegradationLevel, KillSwitch, KillSwitchConfig, get_kill_switch
from .llm_analyzer import LLMFeedbackAnalyzer
from .processor import analyze_batch, analyze_single_feedback, get_trend_report
from .similarity import (
    _char_ngram_similarity,
    _compute_audio_quality_metrics,
    _compute_output_similarity,
    _compute_structure_quality_metrics,
    _compute_text_quality_metrics,
    _aggregate_quality_score,
)
from .canary import (
    GOLDEN_TO_PIPELINE_STAGE,
    PIPELINE_STAGE_TO_PROMPT_DIR,
    STAGE_TYPE,
    _convert_input_to_model,
    _get_required_input_fields,
    _golden_to_pipeline_stage,
    _load_golden_examples,
    _load_prompt_version,
    _pipeline_stage_to_prompt_dir,
    _run_stage_with_prompt_version,
    _resolve_mock_mode,
    _self_iteration_mock_enabled,
    SELF_ITERATION_MOCK_ENV,
)
from .promotion import (
    GateResult,
    PromotionGate,
    PromotionVerdict,
    check_format_compliance,
    check_golden_dataset,
    check_human_sample,
    check_quality_improvement,
    check_regression_suite,
    evaluate_promotion,
)
from .anti_hack import (
    AntiHackVerdict,
    DEFAULT_JUDGE_POOL,
    DualJudgeEvaluator,
    DualJudgeResult,
    JudgeVerdict,
    META_GUARD_READONLY_PATHS,
    evaluate_promotion_anti_hack,
    verify_meta_guard,
)
from .constitution import (
    Constitution,
    ConstitutionAdjudicator,
    ConstitutionVerdict,
    HardRule,
    get_constitution_adjudicator,
)
from .held_out_eval import (
    CandidateEvalResult,
    DatasetManifest,
    HeldOutCase,
    HeldOutDataset,
)
from .evolution_guard import (
    EvolutionGuard,
    PromNode,
    RollbackResult,
    get_evolution_guard,
)
from .regression_suite import (
    KnownFailure,
    RegressionSuite,
    RegressionVerdict,
    get_regression_suite,
)
from .prompt_upgrader import batch_upgrade, upgrade_prompt
from .quality_enhancement import (
    check_semantic_coherence,
    get_false_positive_tracker,
    get_free_tier_health,
    grade_difficulty,
    validate_emotions,
)
from .release import (
    CanaryConfig,
    CanaryMetrics,
    CanaryRelease,
    PromotionGateResult,
    PromotionMetrics,
    VersionStore,
)

__all__ = [
    # Collector
    "capture_feedback",
    "capture_quality_feedback",
    "capture_edit_feedback",
    "list_unprocessed_feedback",
    "mark_feedback_processed",
    # Processor
    "analyze_batch",
    "analyze_single_feedback",
    "get_trend_report",
    # Prompt Upgrader
    "batch_upgrade",
    "upgrade_prompt",
    # Promotion Gate (split modules)
    # similarity
    "_char_ngram_similarity",
    "_compute_audio_quality_metrics",
    "_compute_output_similarity",
    "_compute_structure_quality_metrics",
    "_compute_text_quality_metrics",
    "_aggregate_quality_score",
    # canary
    "GOLDEN_TO_PIPELINE_STAGE",
    "PIPELINE_STAGE_TO_PROMPT_DIR",
    "STAGE_TYPE",
    "_convert_input_to_model",
    "_get_required_input_fields",
    "_golden_to_pipeline_stage",
    "_load_golden_examples",
    "_load_prompt_version",
    "_pipeline_stage_to_prompt_dir",
    "_run_stage_with_prompt_version",
    "_resolve_mock_mode",
    "_self_iteration_mock_enabled",
    "SELF_ITERATION_MOCK_ENV",
    # promotion
    "GateResult",
    "PromotionGate",
    "PromotionVerdict",
    "check_format_compliance",
    "check_golden_dataset",
    "check_human_sample",
    "check_quality_improvement",
    "check_regression_suite",
    "evaluate_promotion",
    # anti_hack
    "AntiHackVerdict",
    "DEFAULT_JUDGE_POOL",
    "DualJudgeEvaluator",
    "DualJudgeResult",
    "JudgeVerdict",
    "META_GUARD_READONLY_PATHS",
    "evaluate_promotion_anti_hack",
    "verify_meta_guard",
    # A/B Test
    "run_ab_test",
    "build_ab_samples",
    "blind_evaluate",
    # Kill Switch
    "KillSwitch",
    "KillSwitchConfig",
    "DegradationLevel",
    "get_kill_switch",
    # Quality Enhancement
    "check_semantic_coherence",
    "validate_emotions",
    "grade_difficulty",
    "get_free_tier_health",
    "get_false_positive_tracker",
    # Auto Processor
    "FeedbackAutoProcessor",
    "create_auto_processor",
    "run_feedback_analysis_cli",
    # Self-Iteration Integration
    "SelfIterationLoop",
    "create_self_iteration_loop",
    "collect_pipeline_feedback",
    "save_quality_feedback",
    "save_user_rating_feedback",
    # A/B Test Manager
    "ABTestManager",
    "ABTestConfig",
    "ABTestResult",
    # Release Management (new)
    "PromotionGate",
    "PromotionGateResult",
    "PromotionMetrics",
    "CanaryRelease",
    "CanaryConfig",
    "CanaryMetrics",
    "VersionStore",
    # LLM Analyzer
    "LLMFeedbackAnalyzer",
    # Bootstrap Few-Shot Optimizer (DSPy GEPA)
    "BootstrapFewShotOptimizer",
    "OptimizationMetrics",
    "OptimizationResult",
    "MultiObjectiveLoss",
    "EarlyStoppingStopper",
    "run_bootstrap_optimization",
    "load_training_examples",
    "BUDGET_LIMIT",
    "DEFAULT_EARLY_STOP_PATIENCE",
    # Critics (Issue 2.1)
    "SyntheticCritic",
    "CalibrationSample",
    "CalibrationResult",
    "DEFAULT_CALIBRATION_SAMPLES",
    "create_synthetic_critic",
    "CriticType",
    "CriticVerdict",
    "CriticResult",
    "CriticEnsemble",
    "CriticEnsembleEvaluator",
    "BaseCritic",
    "SemanticCritic",
    "StructuralCritic",
    "ObjectiveCritic",
]


# Lazy-load the DSPy-backed few-shot optimiser (PEP 562) on first access.
# -----------------------------------------------------------------------
# ``feedback/bootstrap_fewshot.py`` imports dspy at module top, and dspy is NOT a
# declared dependency (absent from requirements.txt / pyproject.toml). Eagerly
# importing it here — and therefore transitively on ``import audiobook_studio``
# — previously crashed every clean-install entrypoint (web server, celery worker,
# env_checker) with ``ModuleNotFoundError: No module named 'dspy'``. The local
# dev venv hid it because dspy was hand-installed there. Keep the optimiser
# opt-in: resolve these names on demand so a bare core import never pays for
# dspy. See tests/unit/test_feedback_import_safety.py for the guard.
_BOOTSTRAP_FEW_SHOT = frozenset(
    {
        "BUDGET_LIMIT",
        "DEFAULT_EARLY_STOP_PATIENCE",
        "BootstrapFewShotOptimizer",
        "EarlyStoppingStopper",
        "MultiObjectiveLoss",
        "OptimizationMetrics",
        "OptimizationResult",
        "load_training_examples",
        "run_bootstrap_optimization",
    }
)


def __getattr__(name: str) -> Any:  # noqa: D401 — PEP 562 lazy module attribute
    if name in _BOOTSTRAP_FEW_SHOT:
        from . import bootstrap_fewshot

        # DSPy is an *optional* dependency of bootstrap_fewshot. Keep the
        # optimiser's symbols importable-but-honest: if dspy is absent, surface
        # a clear ``ModuleNotFoundError`` on access (not a deferred call-time
        # surprise). This preserves the contract asserted by
        # tests/unit/test_feedback_import_safety.py while the module itself
        # stays safe to import without dspy.
        if not bootstrap_fewshot.DSPY_AVAILABLE:
            raise ModuleNotFoundError(
                "No module named 'dspy' — the DSPy-backed few-shot optimiser "
                f"({name}) requires the optional 'dspy' dependency, which is not "
                "installed. The optimiser is experimental and not enabled in the "
                "default pipeline. See docs/AUDIT_REPORT_2026-08-14.md §4.4."
            )
        return getattr(bootstrap_fewshot, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
