"""Promotion gate evaluation with 4 criteria.

包含：
- GateResult, PromotionGate, PromotionVerdict
- Gate 1: Format compliance
- Gate 2: Golden dataset pass rate
- Gate 3: Quality vs previous version
- Gate 4: Human sample pass rate
- evaluate_promotion (主入口)
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

# Import promotion_gate module to allow tests to patch functions
# Functions are accessed via promotion_gate.module_function to ensure patches work
from . import promotion_gate
from .regression_suite import RegressionSuite, get_regression_suite

logger = logging.getLogger(__name__)


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


# ── Gate 1: Format compliance ────────────────────────────────────────────────


def check_format_compliance(
    prompt_content: str,
    threshold: float = 0.99,
) -> GateResult:
    """检查 Prompt 格式合规率 (Jinja2 语法、必需变量、无格式错误)."""
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
    """检查黄金数据集通过率 (真实 pipeline 运行用例，统计通过比例)."""
    examples = promotion_gate._load_golden_examples(stage)
    if not examples:
        return GateResult(
            name="黄金数据集通过率",
            passed=False,
            score=0.0,
            threshold=threshold,
            details=f"黄金数据集未找到: tests/golden/{stage}/",
        )

    # Use original stage name for prompt loading (matches prompts/ dir structure)
    new_prompt = promotion_gate._load_prompt_version(stage, new_version)
    if not new_prompt:
        return GateResult(
            name="黄金数据集通过率",
            passed=False,
            score=0.0,
            threshold=threshold,
            details=f"Prompt v{new_version} not found for stage '{stage}'",
        )

    # Use mapped stage name for pipeline execution
    pipeline_stage = promotion_gate._golden_to_pipeline_stage(stage)
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
        required_fields = promotion_gate._get_required_input_fields(pipeline_stage)
        if not all(field in input_data for field in required_fields):
            logger.debug(f"Golden example {i} missing required fields for {pipeline_stage}: {required_fields}")
            continue

        valid_examples += 1

        try:
            # Run pipeline with new prompt version
            actual_output = promotion_gate._run_stage_with_prompt_version(pipeline_stage, new_version, input_data)

            # Convert to dict if needed for comparison
            if hasattr(actual_output, "model_dump"):
                actual_output = actual_output.model_dump()

            # Compare actual vs expected
            similarity = promotion_gate._compute_output_similarity(actual_output, expected_output)

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
    """比较新旧版本质量指标, 要求新版本 ≥ 旧版 102% (ratio = new/old, ≥1.0=提升)."""
    # Use original stage name for prompt loading (matches prompts/ dir structure)
    old_prompt = promotion_gate._load_prompt_version(stage, old_version)
    new_prompt = promotion_gate._load_prompt_version(stage, new_version)

    if not old_prompt or not new_prompt:
        return GateResult(
            name="质量 ≥ 旧版 102%",
            passed=False,
            score=0.0,
            threshold=threshold,
            details=f"无法加载 prompt: old=v{old_version} new=v{new_version}",
        )

    # Use mapped stage name for pipeline execution
    pipeline_stage = promotion_gate._golden_to_pipeline_stage(stage)
    stage_type = promotion_gate.STAGE_TYPE.get(pipeline_stage, "unknown")
    examples = promotion_gate._load_golden_examples(stage)
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
            old_output = promotion_gate._run_stage_with_prompt_version(pipeline_stage, old_version, input_data)
            if hasattr(old_output, "model_dump"):
                old_output = old_output.model_dump()

            # Run with new version
            new_output = promotion_gate._run_stage_with_prompt_version(pipeline_stage, new_version, input_data)
            if hasattr(new_output, "model_dump"):
                new_output = new_output.model_dump()

            # Compute quality metrics based on stage type
            if stage_type in ("text_edit", "text_annotation"):
                old_metrics = promotion_gate._compute_text_quality_metrics(old_output, expected_output, input_data)
                new_metrics = promotion_gate._compute_text_quality_metrics(new_output, expected_output, input_data)
            elif stage_type in ("audio_synthesis", "audio_quality"):
                old_metrics = promotion_gate._compute_audio_quality_metrics(old_output, expected_output, input_data)
                new_metrics = promotion_gate._compute_audio_quality_metrics(new_output, expected_output, input_data)
            elif stage_type == "structure_analysis":
                old_metrics = promotion_gate._compute_structure_quality_metrics(old_output, expected_output, input_data)
                new_metrics = promotion_gate._compute_structure_quality_metrics(new_output, expected_output, input_data)
            else:
                # Fallback to simple similarity
                old_metrics = {"output_similarity": promotion_gate._compute_output_similarity(old_output, expected_output)}
                new_metrics = {"output_similarity": promotion_gate._compute_output_similarity(new_output, expected_output)}

            # Aggregate into single quality score
            old_quality = promotion_gate._aggregate_quality_score(old_metrics, stage_type)
            new_quality = promotion_gate._aggregate_quality_score(new_metrics, stage_type)

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


# ── Regression suite check ─────────────────────────────────────────────────


def check_regression_suite(
    stage: str,
    candidate_id: str,
    regression_fn: Optional[Callable[..., Tuple[bool, Any]]] = None,
    threshold: float = 1.0,  # Must pass completely (no regressions)
) -> GateResult:
    """检查回归套件：候选不得使已知坏例复发.

    Returns:
        score = 1.0 if no regressions, 0.0 if any regression
    """
    suite = get_regression_suite()
    
    if regression_fn is None:
        return GateResult(
            name="回归套件",
            passed=False,
            score=0.0,
            threshold=threshold,
            details="无回归判定函数，诚实降级不通过",
        )
    
    try:
        regv = suite.check_candidate(candidate_id, regression_fn, auto_add_new=True)
        if regv.rejected:
            return GateResult(
                name="回归套件",
                passed=False,
                score=0.0,
                threshold=threshold,
                details=f"回归拒绝: regressed_on={regv.regressed_on}, new_failures={regv.new_failures_added}",
            )
        return GateResult(
            name="回归套件",
            passed=True,
            score=1.0,
            threshold=threshold,
            details=f"通过: {regv.active_cases} 个活跃坏例，无复发",
        )
    except Exception as e:
        logger.warning(f"Regression suite check failed: {e}")
        return GateResult(
            name="回归套件",
            passed=False,
            score=0.0,
            threshold=threshold,
            details=f"回归套件执行错误: {str(e)[:100]}",
        )


# ── Main gate evaluation ────────────────────────────────────────────────────


def evaluate_promotion(
    stage: str,
    old_version: int,
    new_version: int,
    human_samples: Optional[List[bool]] = None,
    regression_fn: Optional[Callable[..., Tuple[bool, Any]]] = None,
    candidate_id: Optional[str] = None,
) -> PromotionVerdict:
    """主入口: 评估是否允许 Prompt 版本晋升.

    Args:
        stage: Pipeline stage name (golden dataset directory name)
        old_version: 当前版本号
        new_version: 新版本号
        human_samples: 可选的人工抽样结果列表
        regression_fn: 可选的回归判定函数
        candidate_id: 候选配置 ID（用于回归套件）

    Returns:
        PromotionVerdict 判定结果
    """
    new_prompt = promotion_gate._load_prompt_version(stage, new_version)
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
        promotion_gate.check_format_compliance(new_prompt),
        promotion_gate.check_golden_dataset(stage, new_version),
        promotion_gate.check_quality_improvement(stage, old_version, new_version),
        promotion_gate.check_human_sample(human_samples),
    ]
    
    # Add regression suite check if provided
    if regression_fn is not None and candidate_id is not None:
        gates.append(promotion_gate.check_regression_suite(stage, candidate_id, regression_fn))

    all_passed = all(g.passed for g in gates)
    pass_rate = sum(1 for g in gates if g.passed) / len(gates)

    verdict = PromotionVerdict(
        passed=all_passed,
        gates=gates,
        summary=(
            f"✅ 全部门禁通过 (v{old_version} → v{new_version})"
            if all_passed
            else f"❌ {len(gates) - sum(1 for g in gates if g.passed)}/{len(gates)} 门禁未通过 "
            f"(通过率 {pass_rate * 100:.0f}%)"
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