"""
feedback 模块初始化

提供反馈收集、差异分析、Prompt 自动升级、门禁检查、
A/B 测试、Kill Switch 降级、质量增强等功能。
"""

from .ab_test import blind_evaluate, build_ab_samples, run_ab_test
from .ab_test_manager import ABTestConfig, ABTestManager, ABTestResult
from .auto_processor import FeedbackAutoProcessor, create_auto_processor, run_feedback_analysis_cli
from .bootstrap_fewshot import (
    BUDGET_LIMIT,
    DEFAULT_EARLY_STOP_PATIENCE,
    BootstrapFewShotOptimizer,
    EarlyStoppingStopper,
    MultiObjectiveLoss,
    OptimizationMetrics,
    OptimizationResult,
    load_training_examples,
    run_bootstrap_optimization,
)
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
from .promotion_gate import (
    check_format_compliance,
    check_golden_dataset,
    check_human_sample,
    check_quality_improvement,
    evaluate_promotion,
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
    PromotionGate,
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
    # Promotion Gate
    "check_format_compliance",
    "check_golden_dataset",
    "check_human_sample",
    "check_quality_improvement",
    "evaluate_promotion",
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
