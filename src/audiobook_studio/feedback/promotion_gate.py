"""
Backward-compatible promotion_gate module.

This module re-exports all public symbols from the split modules:
- similarity
- canary
- promotion
- anti_hack

Import order is critical: functions from canary/similarity are imported FIRST,
then classes from promotion. This allows promotion.py to import functions from
promotion_gate (which are already loaded from canary) without circular import.
"""

# anti_hack (imported last)
from .anti_hack import (
    DEFAULT_JUDGE_POOL,
    META_GUARD_READONLY_PATHS,
    AntiHackVerdict,
    DualJudgeEvaluator,
    DualJudgeResult,
    JudgeVerdict,
    _constitution,
    _evolution_guard,
    _held_out,
    _regression_suite,
    evaluate_promotion_anti_hack,
    verify_meta_guard,
)

# canary (imported second, provides _load_golden_examples, _load_prompt_version, etc.)
from .canary import (
    GOLDEN_TO_PIPELINE_STAGE,
    PIPELINE_STAGE_TO_PROMPT_DIR,
    SELF_ITERATION_MOCK_ENV,
    STAGE_TYPE,
    _convert_input_to_model,
    _get_required_input_fields,
    _golden_to_pipeline_stage,
    _load_golden_examples,
    _load_prompt_version,
    _pipeline_stage_to_prompt_dir,
    _resolve_mock_mode,
    _run_stage_with_prompt_version,
    _self_iteration_mock_enabled,
)

# promotion classes (imported third, after canary functions are available in this module)
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

# similarity (imported first, no dependencies)
from .similarity import (
    _aggregate_quality_score,
    _char_ngram_similarity,
    _compute_audio_quality_metrics,
    _compute_output_similarity,
    _compute_structure_quality_metrics,
    _compute_text_quality_metrics,
)

# Re-export all for backward compatibility
__all__ = [
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
    "_constitution",
    "_evolution_guard",
    "_held_out",
    "_regression_suite",
    "evaluate_promotion_anti_hack",
    "verify_meta_guard",
]
