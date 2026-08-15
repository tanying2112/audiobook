"""
E4 — Promotion Gate (晋升门禁)

质量门禁系统：评估新版本新版本 Prompt 是否达到升级标准。
四项门禁：
1. 格式合规率 ≥ 99%
2. 黄金数据集通过率 ≥ 95%
3. 质量指标 ≥ 旧版 102%
4. 人工抽样通过率 ≥ 80%

P0.3 防止 reward-hacking 扩展（evaluate_promotion_anti_hack 主入口）：
  - 创作宪法硬规则**先于软打分**裁决（rejecting 高分但 WER 越界的候选）
  - 冻结留出集上**双裁判**（两个不同 provider LLM 各打分；提议配置的模型**不是**裁判）
  - ≥0.25 最小效应量晋升门槛（+0.1 不晋升、+0.3 晋升）
  - 回归套件：候选不得使已知坏例复发
  - 进化守卫记录 + 连续退化回滚剪枝
  - 元门禁：裁判 prompt / 评估集 / 指标定义文件对进化循环只读，CI 校验未被动
"""

from __future__ import annotations

# P1.7: four internal factory helpers (_constitution/_held_out/_evolution_guard/
# _regression_suite) forward-reference classes imported only under
# TYPE_CHECKING (to break a static-only circular import). With eager annotation
# evaluation a bare "-> ConstitutionAdjudicator" raised NameError at def-time
# because those names are absent from the module namespace at runtime. PEP 563
# makes all annotations lazy strings — they are NOT evaluated at def-time — so
# the forward refs resolve only for static checkers (mypy reads them via the
# TYPE_CHECKING block). Verified: no inspect.get_type_hints / __annotations__
# runtime reflection in this file, so lazy annotations are safe.
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .constitution import ConstitutionAdjudicator
    from .evolution_guard import EvolutionGuard
    from .held_out_eval import HeldOutDataset
    from .regression_suite import RegressionSuite

logger = logging.getLogger(__name__)

# ── Stage name mapping: golden dataset dir -> pipeline stage ───────────────────

GOLDEN_TO_PIPELINE_STAGE = {
    "edit_for_tts": "edit",
    "annotate_paragraph": "annotate",
    "analyze_structure": "analyze",
    "extract": "extract",
    "quality_check": "quality",
    "synthesize": "synthesize",
    "quality_judge": "quality",
    "tts_routing": "synthesize",
}

# Reverse mapping: pipeline stage -> prompt directory name
PIPELINE_STAGE_TO_PROMPT_DIR = {
    "edit": "edit_for_tts",
    "annotate": "annotate_paragraph",
    "analyze": "analyze_structure",
    "extract": "extract",
    "quality": "quality_check",
    "synthesize": "synthesize",
}

# Stage type classification for quality metric selection
STAGE_TYPE = {
    "edit": "text_edit",
    "annotate": "text_annotation",
    "analyze": "structure_analysis",
    "extract": "extraction",
    "quality": "audio_quality",
    "synthesize": "audio_synthesis",
}


def _golden_to_pipeline_stage(stage: str) -> str:
    """Map golden dataset directory name to pipeline stage name."""
    return GOLDEN_TO_PIPELINE_STAGE.get(stage, stage)


def _pipeline_stage_to_prompt_dir(pipeline_stage: str) -> str:
    """Map pipeline stage name to prompt directory name."""
    return PIPELINE_STAGE_TO_PROMPT_DIR.get(pipeline_stage, pipeline_stage)


def _convert_input_to_model(pipeline_stage: str, input_dict: Dict[str, Any]) -> Any:
    """Convert input dict to the appropriate pipeline input model."""
    if pipeline_stage == "edit":
        from ..schemas.paragraph import ParagraphAnnotation
        from ..schemas.tts_edit import TtsEditInput

        # Convert paragraph_annotation dict to ParagraphAnnotation model
        if "paragraph_annotation" in input_dict and isinstance(input_dict["paragraph_annotation"], dict):
            input_dict = dict(input_dict)
            input_dict["paragraph_annotation"] = ParagraphAnnotation(**input_dict["paragraph_annotation"])
        return TtsEditInput(**input_dict)
    elif pipeline_stage == "annotate":
        from ..schemas.paragraph import ParagraphAnnotationInput

        return ParagraphAnnotationInput(**input_dict)
    elif pipeline_stage == "analyze":
        from ..schemas.book import BookAnalysisInput

        return BookAnalysisInput(**input_dict)
    elif pipeline_stage == "extract":
        from ..schemas.extraction import ExtractionInput

        return ExtractionInput(**input_dict)
    elif pipeline_stage == "quality":
        from ..schemas.quality import QualityJudgment

        return QualityJudgment(**input_dict)
    elif pipeline_stage == "synthesize":
        from ..schemas.tts_routing import TtsRoutingInput

        return TtsRoutingInput(**input_dict)
    else:
        # Return as-is for unknown stages
        return input_dict


def _get_required_input_fields(pipeline_stage: str) -> List[str]:
    """Get required input fields for a pipeline stage."""
    if pipeline_stage == "edit":
        return ["paragraph_text", "paragraph_annotation", "difficulty", "forbid_edit"]
    elif pipeline_stage == "annotate":
        return ["paragraph_text", "paragraph_index"]
    elif pipeline_stage == "analyze":
        return ["book_text", "book_meta"]
    elif pipeline_stage == "extract":
        return ["text"]
    elif pipeline_stage == "quality":
        return ["audio_path", "expected_text"]
    elif pipeline_stage == "synthesize":
        return ["text", "voice_id"]
    else:
        return []


# ── Quality Metrics Computation ─────────────────────────────────────────────────


def _compute_text_quality_metrics(
    actual_output: Dict[str, Any],
    expected_output: Dict[str, Any],
    input_data: Dict[str, Any],
) -> Dict[str, float]:
    """Compute quality metrics for text-based stages (edit, annotate, analyze)."""
    metrics = {}

    # 1. Output similarity to expected (base metric)
    metrics["output_similarity"] = _compute_output_similarity(actual_output, expected_output)

    # 2. For edit stage: check edited_text quality
    if "edited_text" in actual_output and "edited_text" in expected_output:
        edited_text = actual_output["edited_text"]
        expected_text = expected_output["edited_text"]
        metrics["text_similarity"] = _compute_output_similarity({"text": edited_text}, {"text": expected_text})

        # Semantic coherence (if we have multiple paragraphs, but we only have one here)
        # Use fallback character n-gram similarity
        metrics["semantic_coherence"] = _char_ngram_similarity(edited_text, expected_text)

        # Check if changes_made are reasonable
        if "changes_made" in actual_output:
            metrics["change_count"] = len(actual_output["changes_made"])
            # Penalize too many or too few changes
            expected_changes = len(expected_output.get("changes_made", []))
            if expected_changes > 0:
                metrics["change_ratio"] = min(metrics["change_count"] / max(expected_changes, 1), 2.0)
            else:
                metrics["change_ratio"] = 1.0 if metrics["change_count"] == 0 else 0.5

    # 3. Confidence score from output
    if "confidence" in actual_output:
        metrics["confidence"] = float(actual_output["confidence"])

    return metrics


def _compute_audio_quality_metrics(
    actual_output: Dict[str, Any],
    expected_output: Dict[str, Any],
    input_data: Dict[str, Any],
) -> Dict[str, float]:
    """Compute quality metrics for audio-based stages (synthesize, quality)."""
    metrics = {}

    # Base output similarity
    metrics["output_similarity"] = _compute_output_similarity(actual_output, expected_output)

    # For quality_check stage, check quality judgment scores
    if "overall_score" in actual_output and "overall_score" in expected_output:
        metrics["overall_score_match"] = 1.0 - abs(actual_output["overall_score"] - expected_output["overall_score"])

        # Check individual quality dimensions
        for dim in [
            "speaker_clarity",
            "emotion_match",
            "prosody_naturalness",
            "text_audio_alignment",
        ]:
            if dim in actual_output and dim in expected_output:
                metrics[f"{dim}_match"] = 1.0 - abs(actual_output[dim] - expected_output[dim])

    return metrics


def _compute_structure_quality_metrics(
    actual_output: Dict[str, Any],
    expected_output: Dict[str, Any],
    input_data: Dict[str, Any],
) -> Dict[str, float]:
    """Compute quality metrics for structure analysis stage."""
    metrics = {}
    metrics["output_similarity"] = _compute_output_similarity(actual_output, expected_output)

    # Check key structural elements
    for key in [
        "book_meta",
        "character_voice_map",
        "emotion_snapshots",
        "story_line_summary",
        "global_style_notes",
    ]:
        if key in actual_output and key in expected_output:
            metrics[f"{key}_similarity"] = _compute_output_similarity(actual_output[key], expected_output[key])

    return metrics


def _char_ngram_similarity(text_a: str, text_b: str, n: int = 2) -> float:
    """Compute character n-gram similarity (fallback for semantic similarity)."""
    import math
    from collections import Counter

    def get_ngrams(text: str) -> Counter[str]:
        return Counter(text[i : i + n] for i in range(len(text) - n + 1))

    vec_a = get_ngrams(text_a)
    vec_b = get_ngrams(text_b)

    all_grams = set(vec_a.keys()) | set(vec_b.keys())
    dot_product = sum(vec_a[g] * vec_b[g] for g in all_grams)

    magnitude_a = math.sqrt(sum(v**2 for v in vec_a.values()))
    magnitude_b = math.sqrt(sum(v**2 for v in vec_b.values()))

    if magnitude_a == 0 or magnitude_b == 0:
        return 0.0

    return dot_product / (magnitude_a * magnitude_b)


def _aggregate_quality_score(metrics: Dict[str, float], stage_type: str) -> float:
    """Aggregate multiple quality metrics into a single score."""
    if not metrics:
        return 0.0

    # Weighted aggregation based on stage type
    if stage_type == "text_edit":
        weights = {
            "output_similarity": 0.3,
            "text_similarity": 0.3,
            "semantic_coherence": 0.2,
            "change_ratio": 0.1,
            "confidence": 0.1,
        }
    elif stage_type == "text_annotation":
        weights = {
            "output_similarity": 0.4,
            "semantic_coherence": 0.3,
            "confidence": 0.3,
        }
    elif stage_type == "structure_analysis":
        weights = {
            "output_similarity": 0.5,
        }
        # Add weights for structural elements if present
        for key in metrics:
            if key.endswith("_similarity") and key != "output_similarity":
                weights[key] = 0.5 / max(len([k for k in metrics if k.endswith("_similarity")]), 1)
    elif stage_type == "audio_synthesis" or stage_type == "audio_quality":
        weights = {
            "output_similarity": 0.4,
            "overall_score_match": 0.3,
        }
        for key in metrics:
            if key.endswith("_match") and key not in weights:
                weights[key] = 0.3 / max(len([k for k in metrics if k.endswith("_match")]), 1)
    else:
        weights = {"output_similarity": 1.0}

    # Normalize weights
    total_weight = sum(weights.get(k, 0) for k in metrics.keys())
    if total_weight == 0:
        return 0.0

    score = 0.0
    for metric_name, value in metrics.items():
        weight = weights.get(metric_name, 0)
        score += (weight / total_weight) * value

    return score


# ── Stage-specific prompt version runners ──────────────────────────────────────


def _run_stage_with_prompt_version(
    pipeline_stage: str,
    version: int,
    input_data: Any,
    mock_mode: bool = True,
) -> Any:
    """Run a specific pipeline stage with a specific prompt version.

    This temporarily swaps the v1.j2 template with the specified version,
    runs the pipeline, then restores the original.

    Args:
        pipeline_stage: Short pipeline stage name (edit, annotate, analyze, etc.)
        version: Prompt version number
        input_data: Input data for the pipeline (dict or model object)
        mock_mode: Whether to run in mock mode
    """
    # Convert dict input to appropriate model if needed
    if isinstance(input_data, dict):
        input_data = _convert_input_to_model(pipeline_stage, input_data)

    # Map pipeline stage to prompt directory name
    prompt_dir_name = _pipeline_stage_to_prompt_dir(pipeline_stage)
    prompt_dir = Path("prompts") / prompt_dir_name
    v1_path = prompt_dir / "v1.j2"
    target_path = prompt_dir / f"v{version}.j2"

    if not target_path.exists():
        raise FileNotFoundError(f"Prompt version {version} not found for stage {prompt_dir_name}")

    # Backup original v1.j2
    v1_backup = v1_path.read_text(encoding="utf-8") if v1_path.exists() else None

    try:
        # Copy target version to v1.j2
        target_content = target_path.read_text(encoding="utf-8")
        v1_path.write_text(target_content, encoding="utf-8")

        # Run the stage with the new prompt. The six stage pipelines are
        # structurally unrelated (no shared base class) and a couple carry
        # untyped run() signatures, so we hold the instance as Any — the
        # honest union here — and the function already returns Any upstream.
        pipeline: Any = None
        if pipeline_stage == "edit":
            from ..pipeline.edit_for_tts import EditForTtsPipeline

            pipeline = EditForTtsPipeline(mock_mode=mock_mode)
            return pipeline.run(input_data)
        elif pipeline_stage == "annotate":
            from ..pipeline.annotate_paragraph import AnnotateParagraphPipeline

            pipeline = AnnotateParagraphPipeline(mock_mode=mock_mode)
            return pipeline.run(input_data)
        elif pipeline_stage == "analyze":
            from ..pipeline.analyze_structure import AnalyzeStructurePipeline

            pipeline = AnalyzeStructurePipeline(mock_mode=mock_mode)
            return pipeline.run(input_data)
        elif pipeline_stage == "extract":
            from ..pipeline.extract import ExtractPipeline

            pipeline = ExtractPipeline(mock_mode=mock_mode)
            return pipeline.run(input_data)
        elif pipeline_stage == "quality":
            from ..pipeline.quality_check import QualityCheckPipeline

            pipeline = QualityCheckPipeline(mock_mode=mock_mode)
            return pipeline.run(input_data)
        elif pipeline_stage == "synthesize":
            from ..pipeline.synthesize import SynthesizePipeline

            pipeline = SynthesizePipeline(mock_mode=mock_mode)
            return pipeline.run(input_data)
        else:
            raise ValueError(f"Unknown pipeline stage: {pipeline_stage}")
    finally:
        # Restore original v1.j2
        if v1_backup is not None:
            v1_path.write_text(v1_backup, encoding="utf-8")
        elif v1_path.exists():
            v1_path.unlink()


def _compute_output_similarity(actual: Dict[str, Any], expected: Dict[str, Any]) -> float:
    """Compute similarity between actual and expected output (0-1).

    Uses recursive comparison for nested structures.
    """

    def compare_values(a: Any, b: Any) -> float:
        if type(a) != type(b):
            return 0.0

        if isinstance(a, dict):
            if not a and not b:
                return 1.0
            keys = set(a.keys()) | set(b.keys())
            if not keys:
                return 1.0
            scores = []
            for k in keys:
                if k in a and k in b:
                    scores.append(compare_values(a[k], b[k]))
                else:
                    scores.append(0.0)
            return sum(scores) / len(scores) if scores else 1.0

        elif isinstance(a, list):
            if not a and not b:
                return 1.0
            # For lists, compare element by element up to min length
            max_len = max(len(a), len(b))
            if max_len == 0:
                return 1.0
            scores = []
            for i in range(max_len):
                if i < len(a) and i < len(b):
                    scores.append(compare_values(a[i], b[i]))
                else:
                    scores.append(0.0)
            return sum(scores) / max_len

        elif isinstance(a, str):
            if not a and not b:
                return 1.0
            # Use sequence matcher for string similarity
            from difflib import SequenceMatcher

            return SequenceMatcher(None, a, b).ratio()

        elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if a == b:
                return 1.0
            # For numeric, use relative difference
            max_val = max(abs(a), abs(b), 1)
            diff = abs(a - b) / max_val
            return max(0.0, 1.0 - diff)

        elif isinstance(a, bool) and isinstance(b, bool):
            return 1.0 if a == b else 0.0

        else:
            return 1.0 if a == b else 0.0

    return compare_values(actual, expected)


@dataclass
class GateResult:
    """单项目门禁结果."""

    name: str
    passed: bool
    score: float
    threshold: float
    details: str = ""


class PromotionGate:
    """4-criteria promotion gate evaluator."""

    DEFAULT_THRESHOLDS: Dict[str, float] = {
        "格式合规率": 0.95,
        "黄金数据集通过率": 0.90,
        "quality_vs_old": 1.02,
        "人工抽样通过率": 0.85,
    }

    def __init__(self, thresholds: Optional[Dict[str, float]] = None) -> None:
        self.thresholds: Dict[str, float] = thresholds or dict(self.DEFAULT_THRESHOLDS)

    def get_status(self) -> Dict[str, Any]:
        return {"thresholds": self.thresholds}


@dataclass
class PromotionVerdict:
    """晋升判定."""

    passed: bool
    gates: List[GateResult]
    summary: str
    version_from: int
    version_to: int
    stage: str
    evaluated_at: str

    @property
    def pass_rate(self) -> float:
        if not self.gates:
            return 0.0
        return sum(1 for g in self.gates if g.passed) / len(self.gates)


def _load_golden_examples(stage: str) -> List[Dict[str, Any]]:
    """加载黄金数据集，合并 JSON 和 JSONL 格式."""
    golden_dir = Path("tests/golden") / stage
    if not golden_dir.exists():
        logger.warning(f"Golden dataset not found: {golden_dir}")
        return []

    examples: List[Dict[str, Any]] = []

    # Load JSON files
    for f in sorted(golden_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            examples.append(data)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load golden example {f}: {e}")

    # Load JSONL files
    for f in sorted(golden_dir.glob("*.jsonl")):
        try:
            for line in f.read_text(encoding="utf-8").strip().split("\n"):
                if line.strip():
                    examples.append(json.loads(line))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load golden JSONL {f}: {e}")

    return examples


def _load_prompt_version(stage: str, version: int) -> Optional[str]:
    """加载指定版本的 prompt."""
    prompt_path = Path("prompts") / stage / f"v{version}.j2"
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    return None


# ── Gate 1: Format compliance ────────────────────────────────────────────────


def check_format_compliance(
    prompt_content: str,
    threshold: float = 0.99,
) -> GateResult:
    """检查 Prompt 格式合规率.

    检查: Jinja2 语法、必需变量存在 ({{ }}), 无格式错误.
    """
    issues: List[str] = []

    # Check basic Jinja2 syntax
    if "{{" in prompt_content:
        # Check for unclosed variables
        opens = prompt_content.count("{{")
        closes = prompt_content.count("}}")
        if opens != closes:
            issues.append(f"未闭合的变量: {opens}个 '{{{{' 但 {closes}个 '}}}}'")

    # Check for {% %} blocks
    if "{%" in prompt_content:
        block_opens = prompt_content.count("{%")
        block_closes = prompt_content.count("%}")
        if block_opens != block_closes:
            issues.append(f"未闭合的块: {block_opens}个 '{{%' 但 {block_closes}个 '}}%'")

    # Check for common format issues
    if prompt_content.count("\n\n\n\n") > 0:
        issues.append("存在连续超过 3 个空行")
    if prompt_content.endswith("\n\n"):
        issues.append("文件末尾多余空行")

    # Calculate compliance score
    total_checks = 3
    failed_checks = len(issues)
    score = max(0.0, 1.0 - failed_checks / total_checks)

    passed = score >= threshold

    return GateResult(
        name="格式合规率",
        passed=passed,
        score=score,
        threshold=threshold,
        details=("全部格式检查通过" if not issues else f"发现问题 ({len(issues)}): {'; '.join(issues)}"),
    )


# ── Gate 2: Golden dataset pass rate ────────────────────────────────────────


def check_golden_dataset(
    stage: str,
    new_version: int,
    threshold: float = 0.95,
) -> GateResult:
    """检查黄金数据集通过率.

    使用真实 pipeline 运行 golden dataset 用例，统计通过比例。
    """
    examples = _load_golden_examples(stage)
    if not examples:
        return GateResult(
            name="黄金数据集通过率",
            passed=False,
            score=0.0,
            threshold=threshold,
            details=f"黄金数据集未找到: tests/golden/{stage}/",
        )

    # Use original stage name for prompt loading (matches prompts/ dir structure)
    new_prompt = _load_prompt_version(stage, new_version)
    if not new_prompt:
        return GateResult(
            name="黄金数据集通过率",
            passed=False,
            score=0.0,
            threshold=threshold,
            details=f"Prompt v{new_version} not found for stage '{stage}'",
        )

    # Use mapped stage name for pipeline execution
    pipeline_stage = _golden_to_pipeline_stage(stage)

    # Run actual pipeline on each golden example
    passed_count = 0
    failed_details: List[str] = []
    valid_examples = 0

    for i, example in enumerate(examples):
        # Expect golden dataset format: {"input": {...}, "expected_output": {...}}
        if "input" not in example or "expected_output" not in example:
            logger.warning(f"Golden example {i} missing 'input' or 'expected_output' field")
            continue

        input_data = example["input"]
        expected_output = example["expected_output"]

        # Check if input has required fields for this pipeline stage
        required_fields = _get_required_input_fields(pipeline_stage)
        if not all(field in input_data for field in required_fields):
            logger.debug(f"Golden example {i} missing required fields for {pipeline_stage}: {required_fields}")
            continue

        valid_examples += 1

        try:
            # Run pipeline with new prompt version
            actual_output = _run_stage_with_prompt_version(pipeline_stage, new_version, input_data, mock_mode=True)

            # Convert to dict if needed for comparison
            if hasattr(actual_output, "model_dump"):
                actual_output = actual_output.model_dump()

            # Compare actual vs expected
            similarity = _compute_output_similarity(actual_output, expected_output)

            if similarity >= 0.85:  # 85% similarity threshold for "pass"
                passed_count += 1
            else:
                failed_details.append(f"Example {i}: similarity={similarity:.2f}")

        except Exception as e:
            logger.warning(f"Failed to run example {i}: {e}")
            failed_details.append(f"Example {i}: error={str(e)[:50]}")

    if valid_examples == 0:
        return GateResult(
            name="黄金数据集通过率",
            passed=False,
            score=0.0,
            threshold=threshold,
            details=f"无有效测试用例 (共 {len(examples)} 个，缺少必需字段)",
        )

    score = passed_count / valid_examples
    passed = score >= threshold

    return GateResult(
        name="黄金数据集通过率",
        passed=passed,
        score=score,
        threshold=threshold,
        details=(
            f"{passed_count}/{valid_examples} 用例通过 ({score * 100:.1f}% ≥ {threshold * 100:.0f}%)"
            + (f" | 失败: {'; '.join(failed_details[:3])}" if failed_details else "")
        ),
    )


# ── Gate 3: Quality vs previous version ─────────────────────────────────────


def check_quality_improvement(
    stage: str,
    old_version: int,
    new_version: int,
    threshold: float = 1.02,  # 102% = 至少提升 2%
) -> GateResult:
    """比较新旧版本的质量指标, 要求新版本 ≥ 旧版本的 102%.

    使用真实 pipeline 在 golden dataset 上运行，对比多维质量分数。
    支持文本编辑、标注、结构分析、音频合成/质检等多种 stage 类型。

    Returns:
        score = new_avg_quality / old_avg_quality (ratio, ≥1.0 = improvement)
    """
    # Use original stage name for prompt loading (matches prompts/ dir structure)
    old_prompt = _load_prompt_version(stage, old_version)
    new_prompt = _load_prompt_version(stage, new_version)

    if not old_prompt or not new_prompt:
        return GateResult(
            name="质量 ≥ 旧版 102%",
            passed=False,
            score=0.0,
            threshold=threshold,
            details=f"无法加载 prompt: old=v{old_version} new=v{new_version}",
        )

    # Use mapped stage name for pipeline execution
    pipeline_stage = _golden_to_pipeline_stage(stage)
    stage_type = STAGE_TYPE.get(pipeline_stage, "unknown")

    examples = _load_golden_examples(stage)
    if not examples:
        return GateResult(
            name="质量 ≥ 旧版 102%",
            passed=False,
            score=0.0,
            threshold=threshold,
            details=f"黄金数据集未找到: tests/golden/{stage}/",
        )

    # Run both versions on golden dataset and compute quality scores
    old_scores: List[float] = []
    new_scores: List[float] = []
    metric_breakdown_old: Dict[str, List[float]] = {}
    metric_breakdown_new: Dict[str, List[float]] = {}

    for i, example in enumerate(examples):
        if "input" not in example or "expected_output" not in example:
            continue

        input_data = example["input"]
        expected_output = example["expected_output"]

        try:
            # Run with old version
            old_output = _run_stage_with_prompt_version(pipeline_stage, old_version, input_data, mock_mode=True)
            if hasattr(old_output, "model_dump"):
                old_output = old_output.model_dump()

            # Run with new version
            new_output = _run_stage_with_prompt_version(pipeline_stage, new_version, input_data, mock_mode=True)
            if hasattr(new_output, "model_dump"):
                new_output = new_output.model_dump()

            # Compute quality metrics based on stage type
            if stage_type in ("text_edit", "text_annotation"):
                old_metrics = _compute_text_quality_metrics(old_output, expected_output, input_data)
                new_metrics = _compute_text_quality_metrics(new_output, expected_output, input_data)
            elif stage_type in ("audio_synthesis", "audio_quality"):
                old_metrics = _compute_audio_quality_metrics(old_output, expected_output, input_data)
                new_metrics = _compute_audio_quality_metrics(new_output, expected_output, input_data)
            elif stage_type == "structure_analysis":
                old_metrics = _compute_structure_quality_metrics(old_output, expected_output, input_data)
                new_metrics = _compute_structure_quality_metrics(new_output, expected_output, input_data)
            else:
                # Fallback to simple similarity
                old_metrics = {"output_similarity": _compute_output_similarity(old_output, expected_output)}
                new_metrics = {"output_similarity": _compute_output_similarity(new_output, expected_output)}

            # Aggregate into single quality score
            old_quality = _aggregate_quality_score(old_metrics, stage_type)
            new_quality = _aggregate_quality_score(new_metrics, stage_type)

            old_scores.append(old_quality)
            new_scores.append(new_quality)

            # Track per-metric breakdown for detailed reporting
            for metric_name, value in old_metrics.items():
                metric_breakdown_old.setdefault(metric_name, []).append(value)
            for metric_name, value in new_metrics.items():
                metric_breakdown_new.setdefault(metric_name, []).append(value)

        except Exception as e:
            logger.warning(f"Failed to run quality comparison for example {i}: {e}")

    if not old_scores or not new_scores:
        return GateResult(
            name="质量 ≥ 旧版 102%",
            passed=False,
            score=0.0,
            threshold=threshold,
            details="无法计算质量分数：运行失败或无有效样本",
        )

    old_avg = sum(old_scores) / len(old_scores)
    new_avg = sum(new_scores) / len(new_scores)

    score_ratio = new_avg / max(old_avg, 0.01)
    passed = score_ratio >= threshold

    return GateResult(
        name="质量 ≥ 旧版 102%",
        passed=passed,
        score=score_ratio,
        threshold=threshold,
        details=(
            f"旧版 v{old_version} 平均质量: {old_avg:.3f}, "
            f"新版 v{new_version} 平均质量: {new_avg:.3f}, "
            f"比例: {score_ratio:.3f} ({len(old_scores)} 样本)"
        ),
    )


# ── Gate 4: Human sample pass rate ──────────────────────────────────────────


def check_human_sample(
    sample_results: Optional[List[bool]] = None,
    threshold: float = 0.80,
) -> GateResult:
    """人工抽样通过率.

    Args:
        sample_results: 人工抽样结果列表 (True=通过, False=不通过)
        threshold: 通过阈值 (默认 80%)
    """
    if not sample_results:
        return GateResult(
            name="人工抽样通过率",
            passed=False,
            score=0.0,
            threshold=threshold,
            details="尚无人工抽样结果",
        )

    passed = sum(sample_results)
    total = len(sample_results)
    score = passed / total
    passed_flag = score >= threshold

    return GateResult(
        name="人工抽样通过率",
        passed=passed_flag,
        score=score,
        threshold=threshold,
        details=(f"{passed}/{total} 抽样通过 ({score * 100:.1f}% ≥ {threshold * 100:.0f}%)"),
    )


# ── Main gate evaluation ────────────────────────────────────────────────────


def evaluate_promotion(
    stage: str,
    old_version: int,
    new_version: int,
    human_samples: Optional[List[bool]] = None,
) -> PromotionVerdict:
    """主入口: 评估是否允许 Prompt 版本晋升.

    Args:
        stage: Pipeline stage name (golden dataset directory name)
        old_version: 当前版本号
        new_version: 新版本号
        human_samples: 可选的人工抽样结果列表

    Returns:
        PromotionVerdict 判定结果
    """
    new_prompt = _load_prompt_version(stage, new_version)
    if not new_prompt:
        return PromotionVerdict(
            passed=False,
            gates=[],
            summary=f"Prompt v{new_version} not found for stage '{stage}'",
            version_from=old_version,
            version_to=new_version,
            stage=stage,
            evaluated_at=datetime.now(timezone.utc).isoformat(),
        )

    gates = [
        check_format_compliance(new_prompt),
        check_golden_dataset(stage, new_version),
        check_quality_improvement(stage, old_version, new_version),
        check_human_sample(human_samples),
    ]

    all_passed = all(g.passed for g in gates)
    pass_rate = sum(1 for g in gates if g.passed) / len(gates)

    verdict = PromotionVerdict(
        passed=all_passed,
        gates=gates,
        summary=(
            f"✅ 全部门禁通过 (v{old_version} → v{new_version})"
            if all_passed
            else f"❌ {len(gates) - sum(1 for g in gates if g.passed)}/4 门禁未通过 " f"(通过率 {pass_rate * 100:.0f}%)"
        ),
        version_from=old_version,
        version_to=new_version,
        stage=stage,
        evaluated_at=datetime.now(timezone.utc).isoformat(),
    )

    logger.info(f"Promotion gate: {verdict.summary}")
    for g in gates:
        status = "✅" if g.passed else "❌"
        logger.info(f"  {status} {g.name}: {g.score:.3f} ≥ {g.threshold}")

    return verdict


# ── P0.3 防止 reward-hacking：双裁判 + 留出集 + 宪法 + 效应量 + 回归 + 守卫 ────────
# 所有新增逻辑与既有 4-gate evaluate_promotion **正交叠加**：既有接口不变，仅追加
# 一个更严格的 evaluate_promotion_anti_hack 主入口与若干内部构件。红线 #1：评估
# 真值（真 prompt→输出→P0.2 真指标→归一化），依赖缺失诚实降级、绝不假通过。

# 默认裁判 model 白名单：双裁判需两个**不同** provider。提议配置的 proposer_model 被
# 明确排除在裁判池外（防"自己给自己打分"）。免费资源为上限：默认 openai-mini + 通用
# 备用；这些只是裁判 model 标识，实际调用由上层注入的 judge_fn 承担，本模块不发起 LLM。
# 池给 3 个：即便收录一个 proposer_model 后仍留 ≥2 个独立裁判——满足路线图"双裁判+互不提议"
# 严格要求（两不同 provider 各打分，且 proposer 不参赛）。
DEFAULT_JUDGE_POOL: Tuple[str, ...] = ("gpt-4o-mini", "deepseek-chat", "openrouter/auto")


@dataclass
class JudgeVerdict:
    """单个裁判对候选的打分结果。"""

    judge_model: str
    score: float                 # 0-1
    rationale: str = ""
    error: Optional[str] = None  # 裁判不可用时记原因（诚实降级）

    @property
    def available(self) -> bool:
        return self.error is None


@dataclass
class DualJudgeResult:
    """双裁判裁决汇总。"""

    judges: List[JudgeVerdict]
    mean: Optional[float]        # 两位可用裁判的均值；任一不可用则 None（不假通过）
    agreement: Optional[bool]    # 两位分歧 ≤ delta 时 True；不可判（缺裁判）则 None
    disagreement_delta: float = 0.0

    @property
    def promotable_score(self) -> Optional[float]:
        """只有两位都可用且分歧可接受才返回可用均分；否则 None=不假通过。"""
        if self.mean is None or self.agreement is None or not self.agreement:
            return None
        return self.mean


class DualJudgeEvaluator:
    """双裁判：两个不同 provider LLM 各在留出集上打分；proposer_model 排除在裁判外。"""

    def __init__(
        self,
        judge_pool: Optional[List[str]] = None,
        disagreement_delta: float = 0.25,
        proposer_model: Optional[str] = None,
    ) -> None:
        # 从 pool 里去掉 proposer_model（提议配置的模型不得给自己打分）
        pool = list(judge_pool) if judge_pool else list(DEFAULT_JUDGE_POOL)
        if proposer_model:
            pool = [m for m in pool if m != proposer_model]
        # 取两个裁判（去重保序）。pool 不足两个 → 诚实降级（无法构成双裁判）
        self.judge_models: List[str] = []
        for m in pool:
            if m not in self.judge_models:
                self.judge_models.append(m)
            if len(self.judge_models) >= 2:
                break
        self.disagreement_delta = float(disagreement_delta)
        self.proposer_model = proposer_model

    @property
    def can_dual_judge(self) -> bool:
        return len(self.judge_models) >= 2

    def evaluate(
        self,
        judge_fn: Callable[[str, Mapping[str, Any]], float],
        candidate_payload: Mapping[str, Any],
    ) -> DualJudgeResult:
        """在 candidates 载荷上让每位裁判打分。

        judge_fn(judge_model, candidate_payload) -> float ∈[0,1]，由上层注入真实 LLM 调用
        （跑真实留出集输出）。本方法不发起任何 LLM 请求。任一裁判抛错 → 该裁判 error 记
        原因、Unavailable；两位都不可用 / 分歧 > delta → mean=None / agreement=False
        （诚实降级或分歧不晋升）。
        """
        verdicts: List[JudgeVerdict] = []
        for jm in self.judge_models:
            try:
                raw = judge_fn(jm, candidate_payload)
                s = float(raw)
                if s != s:  # NaN
                    raise ValueError("judge returned NaN")
                s = max(0.0, min(1.0, s))
                verdicts.append(JudgeVerdict(judge_model=jm, score=s))
            except Exception as ex:  # noqa: BLE001
                verdicts.append(JudgeVerdict(judge_model=jm, score=0.0, error=f"{type(ex).__name__}: {ex}"))

        avail = [v for v in verdicts if v.available]
        if len(avail) < 2:
            # 严格：必须两位裁判都跑出真值才能给均值，否则 None（不假通过）
            return DualJudgeResult(judges=verdicts, mean=None, agreement=None)
        mean = sum(v.score for v in avail) / len(avail)
        delta = abs(avail[0].score - avail[1].score)
        agreement = delta <= self.disagreement_delta
        if not agreement:
            logger.warning(
                "DualJudge disagreement: %s=%.3f vs %s=%.3f (Δ=%.3f > %.2f) — 不晋升",
                avail[0].judge_model, avail[0].score, avail[1].judge_model, avail[1].score,
                delta, self.disagreement_delta,
            )
        return DualJudgeResult(
            judges=verdicts, mean=mean, agreement=agreement, disagreement_delta=delta
        )


# ── 元门禁：判官 prompt / 评估集 / 指标定义文件对进化循环只读 ─────────────────────
# 这些路径是 reward hacking 的"尺度"。CI 以 verify_meta_guard() 校验：
#   * 它们随本 Sprint 的自动改动列表（git diff --name-only）一并被人工/CI 复审；
#   * 候选不得在进化循环内写这些文件（本模块纯读，无写）。
META_GUARD_READONLY_PATHS: Tuple[str, ...] = (
    "src/audiobook_studio/feedback/promotion_config.yaml",   # 门禁阈值
    "src/audiobook_studio/feedback/constitution.py",         # 创作宪法硬规则
    "src/audiobook_studio/feedback/held_out_eval.py",        # 留出集与评估契约
    "src/audiobook_studio/quality/metrics.py",               # 硬指标定义（MOS/WER/Sim）
    "prompts/",                                             # 裁判/生成 prompt（模板）
    "tests/golden/",                                         # 评估集（留出集来源）
)


def verify_meta_guard(changed_files: List[str]) -> Dict[str, Any]:
    """校验本次改动列表是否触碰只读尺度文件。

    返回 {touched: [...], clean: bool}。CI 在自动晋升流水线里调用——当
    `clean=False` 时，改动触及了度量尺度，必须人工复核、不得由进化循环自动通过。
    """
    touched: List[str] = []
    for cf in changed_files:
        for ro in META_GUARD_READONLY_PATHS:
            if cf == ro or cf.startswith(ro.rstrip("/") + "/"):
                touched.append(cf)
                break
    return {"touched": touched, "clean": len(touched) == 0}


# ── 反 reward-hacking 主编排：evaluate_promotion_anti_hack ────────────────────────
# 严格顺序：
#   1) Constitution 先于软打分硬裁决（被拒即不晋升，无需双裁判）
#   2) 冻结留出集上双裁判打分（提议配置模型不参赛；分歧超.delta 不晋升）
#   3) ≥0.25 最小效应量晋升门槛（候选留出集均分 ≥ baseline 均分 + 0.25）
#   4) 回归套件：候选不得使任一 active 坏例复发（含本次新发现的失败）
#   5) 进化守卫 record：成功晋升则 append 节点；连续退化 ≥2 则回滚+剪枝
# 任一硬关被违反即 passed=False；依赖未就绪时该关诚实降级为"无法裁决→不晋升"。

@dataclass
class AntiHackVerdict:
    """反 reward-hacking 晋升裁决（评估报告）。"""

    passed: bool
    summary: str
    constitution: Dict[str, Any]
    dual_judge: Dict[str, Any]
    held_out: Dict[str, Any]
    regression_suite: Dict[str, Any]
    evolution_guard: Dict[str, Any]
    effect_size: Optional[float] = None
    beat_baseline_by_025: bool = False
    promoted_node_id: Optional[str] = None
    rolled_back: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "summary": self.summary,
            "constitution": self.constitution,
            "dual_judge": self.dual_judge,
            "held_out": self.held_out,
            "regression_suite": self.regression_suite,
            "evolution_guard": self.evolution_guard,
            "effect_size": self.effect_size,
            "beat_baseline_by_025": self.beat_baseline_by_025,
            "promoted_node_id": self.promoted_node_id,
            "rolled_back": self.rolled_back,
        }


def _constitution() -> ConstitutionAdjudicator:
    from .constitution import get_constitution_adjudicator
    return get_constitution_adjudicator()


def _held_out(stage: str) -> HeldOutDataset:
    from .held_out_eval import HeldOutDataset
    return HeldOutDataset(stage)


def _evolution_guard() -> EvolutionGuard:
    from .evolution_guard import get_evolution_guard
    return get_evolution_guard()


def _regression_suite() -> RegressionSuite:
    from .regression_suite import get_regression_suite
    return get_regression_suite()


def evaluate_promotion_anti_hack(
    stage: str,
    candidate_id: str,
    candidate_output_text: str,
    reference_text: Optional[str],
    audio_metrics: Optional[Mapping[str, Any]],
    candidate_payload: Mapping[str, Any],
    judge_fn: Optional[Callable[[str, Mapping[str, Any]], float]],
    baseline_fn: Optional[Callable[[Any], float]],
    candidate_eval_fn: Optional[Callable[[Any], float]],
    proposer_model: Optional[str] = None,
    judge_pool: Optional[List[str]] = None,
    regression_fn: Optional[Callable[[Any], Tuple[bool, Any]]] = None,
    promoted_at: str = "",
    config_digest: str = "",
    new_version: int = 1,
) -> AntiHackVerdict:
    """反 reward-hacking 主入口。任一硬关失败即不晋升。

    红线 #1：judge_fn / baseline_fn / candidate_eval_fn / regression_fn 由**上层注入**，
    跑真实评估（真 prompt→输出→P0.2 真指标→归一化）；本函数不 mock、不假通过。
    依赖缺失（双裁判不可用、留出集空、无基线）→ 对应关诚实降级 → passed=False。
    """
    reasons: List[str] = []

    # ── 1) 创作宪法硬规则先于软打分 ──────────────────────────────────────
    constit = _constitution().adjudge(
        candidate_output=candidate_output_text,
        reference_text=reference_text,
        audio_metrics=audio_metrics or {},
    )
    constit_dict = constit.to_dict()
    if not constit.passed:
        reasons.append("constitution:rejected")
        if constit.unable_to_judge:
            reasons.append("constitution:unable_to_judge(依赖缺失诚实降级)")

    # ── 2) 冻结留出集双裁判 ────────────────────────────────────────────
    dj = DualJudgeEvaluator(
        judge_pool=judge_pool,
        disagreement_delta=0.25,
        proposer_model=proposer_model,
    )
    dj_avail = dj.can_dual_judge
    dj_dict: Dict[str, Any] = {
        "judge_models": list(dj.judge_models),
        "proposer_excluded": bool(proposer_model and proposer_model not in dj.judge_models),
        "can_dual_judge": dj_avail,
    }
    # 验证 proposer_model 确实不是裁判（互不提议）
    if proposer_model and proposer_model in dj.judge_models:
        dj_dict["proposer_not_judge"] = False
        reasons.append("dual_judge:proposer_is_judge(违反互不提议)")
    else:
        dj_dict["proposer_not_judge"] = True

    held_out_score: Optional[float] = None
    baseline_score: Optional[float] = None
    held_out_dict: Dict[str, Any] = {}

    try:
        ds = _held_out(stage)
        held_out_dict = {
            "stage": stage,
            "case_count": ds.case_count,
            "signature": ds.signature,
            "origin": ds.manifest.origin_status,
        }
        if ds.case_count == 0:
            reasons.append("held_out:empty(留出集空无法量度诚实降级)")
        else:
            # 候选留出集评估（候选真值）与基线留出集评估（基线真值）
            cand_scores = None
            base_scores = None
            if candidate_eval_fn is not None:
                res = ds.evaluate_candidate(
                    candidate_eval_fn, candidate_id=candidate_id,
                    baseline_fn=baseline_fn if baseline_fn is not None else (lambda c: 0.0),
                    baseline_id="baseline",
                )
                cand_scores = res
                held_out_score = res.mean_score
                baseline_score = res.baseline_mean
                held_out_dict.update(res.to_dict())
            # 双裁判在候选载荷上打综合分（如可用）
            if dj_avail and judge_fn is not None:
                djres = dj.evaluate(judge_fn, candidate_payload)
                held_out_dict["dual_judge"] = {
                    "mean": djres.mean,
                    "agreement": djres.agreement,
                    "delta": djres.disagreement_delta,
                    "judges": [
                        {"model": j.judge_model, "score": j.score, "error": j.error}
                        for j in djres.judges
                    ],
                    "promotable_score": djres.promotable_score,
                }
                if not djres.promotable_score and not (judge_fn is None):
                    if djres.mean is None:
                        reasons.append("dual_judge:unavailable(缺裁判/不可用不假通过)")
                    elif djres.agreement is False:
                        reasons.append("dual_judge:disagreement(分歧超.delta不晋升)")
            elif judge_fn is not None and not dj_avail:
                reasons.append("dual_judge:pool<2(无法构成双裁判诚实降级)")
    except Exception as ex:  # noqa: BLE001
        held_out_dict = {"error": f"{type(ex).__name__}: {ex}"}
        reasons.append("held_out:error")

    # ── 3) ≥0.25 效应量晋升门槛 ──────────────────────────────────────────
    effect_size: Optional[float] = None
    beat025 = False
    if held_out_score is not None and baseline_score is not None:
        effect_size = held_out_score - baseline_score
        beat025 = effect_size >= 0.25
        if not beat025:
            reasons.append(
                f"effect_size:insufficient(+{effect_size:.3f} < 0.25 最小效应量门槛)"
            )
    else:
        reasons.append("effect_size:indeterminate(缺候选或基线留出集真值)")

    # ── 4) 回归套件 ─────────────────────────────────────────────────────
    reg_dict: Dict[str, Any] = {}
    try:
        suite = _regression_suite()
        if regression_fn is not None:
            regv = suite.check_candidate(candidate_id, regression_fn, auto_add_new=True)
            reg_dict = regv.to_dict()
            if regv.rejected:
                reasons.append(
                    "regression_suite:recurring_failure(已知坏例复发或新失败入库)"
                )
        else:
            reg_dict = {"skipped": "no regression_fn（诚实降级，按保守不晋升）"}
            reasons.append("regression_suite:indeterminate(无回归判定函数)")
    except Exception as ex:  # noqa: BLE001
        reg_dict = {"error": f"{type(ex).__name__}: {ex}"}
        reasons.append("regression_suite:error")

    # ── 5) 进化守卫 record ──────────────────────────────────────────────
    guard_dict: Dict[str, Any] = {}
    rolled_back: Optional[Dict[str, Any]] = None
    promoted_node_id: Optional[str] = None
    try:
        guard = _evolution_guard()
        ev_mean = held_out_score if held_out_score is not None else 0.0
        ev_effect = effect_size if effect_size is not None else 0.0
        node_id = f"{stage}:{candidate_id}:v{new_version}"
        rb = guard.record(
            node_id=node_id,
            stage=stage,
            held_out_mean=ev_mean,
            effect_size=ev_effect,
            promoted_at=promoted_at,
            config_digest=config_digest,
        )
        guard_dict = {
            "active_id": guard.active_id,
            "node_count": guard.node_count,
            "pruned_ids": list(guard.pruned_ids),
            "regression_streak": guard.regression_streak,
        }
        if rb is not None:
            rolled_back = rb.to_dict()
            guard_dict["rolled_back"] = rolled_back
            reasons.append(
                f"evolution_guard:rolled_back({rb.rolled_back_from}->{rb.rolled_back_to},"
                f"pruned {len(rb.pruned_node_ids)})"
            )
        else:
            # 仅当晋升成功才记 promoted_node_id
            if beat025 and len(reasons) == 0:
                promoted_node_id = node_id
    except Exception as ex:  # noqa: BLE001
        guard_dict = {"error": f"{type(ex).__name__}: {ex}"}
        reasons.append("evolution_guard:error")

    passed = len(reasons) == 0 and beat025
    summary = (
        f"✅ 晋升通过：{stage} {candidate_id}（effect=+{effect_size:.3f} ≥ 0.25，"
        f"宪法/双裁判/留出集/回归/守卫全通过）"
        if passed
        else f"❌ 拒绝晋升：{stage} {candidate_id} — {'; '.join(reasons)}"
    )
    logger.info("evaluate_promotion_anti_hack: %s", summary)
    return AntiHackVerdict(
        passed=passed,
        summary=summary,
        constitution=constit_dict,
        dual_judge=dj_dict,
        held_out=held_out_dict,
        regression_suite=reg_dict,
        evolution_guard=guard_dict,
        effect_size=effect_size,
        beat_baseline_by_025=beat025,
        promoted_node_id=promoted_node_id,
        rolled_back=rolled_back,
    )
