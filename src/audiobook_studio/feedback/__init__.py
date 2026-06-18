"""
feedback 模块初始化

提供反馈收集、差异分析、Prompt 自动升级、门禁检查、
A/B 测试、Kill Switch 降级、质量增强等功能。
"""

from .collector import (
    capture_feedback,
    capture_quality_feedback,
    capture_edit_feedback,
    list_unprocessed_feedback,
    mark_feedback_processed,
)
from .processor import (
    analyze_batch,
    analyze_single_feedback,
    get_trend_report,
)
from .prompt_upgrader import (
    batch_upgrade,
    upgrade_prompt,
)
from .promotion_gate import (
    check_format_compliance,
    check_golden_dataset,
    check_human_sample,
    check_quality_improvement,
    evaluate_promotion,
)
from .ab_test import (
    run_ab_test,
    build_ab_samples,
    blind_evaluate,
)
from .kill_switch import (
    KillSwitch,
    KillSwitchConfig,
    DegradationLevel,
    get_kill_switch,
)
from .quality_enhancement import (
    check_semantic_coherence,
    validate_emotions,
    grade_difficulty,
    get_free_tier_health,
    get_false_positive_tracker,
)
from .auto_processor import (
    FeedbackAutoProcessor,
    create_auto_processor,
    run_feedback_analysis_cli,
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
]
