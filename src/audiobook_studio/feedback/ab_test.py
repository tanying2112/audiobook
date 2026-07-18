"""
E5 — A/B 测试框架

对比 v1 vs v2 Prompt 版本的输出质量，支持盲评。
包含统计显著性检验、自动化触发、CLI 工具等。
"""

import json
import logging
import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..schemas import ParagraphAnnotation, QualityJudgment
from ..schemas.judge import PairwiseJudgment

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════
# LLM Judge for Blind Evaluation
# ════════════════════════════════════════════════════════════════════════════


def create_llm_judge_fn(stage: str, judge_model: str = None):
    """
    Create an LLM-as-a-Judge function for blind evaluation of A/B test samples.

    The judge evaluates outputs without knowing which version (A or B) produced them,
    providing unbiased quality assessment.

    Args:
        stage: Pipeline stage name (edit_for_tts, annotate_paragraph, etc.)
        judge_model: LLM model to use as judge (None = use default from config)

    Returns:
        Function that takes (output_a, output_b, input_data) and returns (score_a, score_b, rationale)
    """
    from ..llm import LLMClientConfig, create_client
    from ..schemas import QualityJudgment

    if judge_model is None:
        judge_model = "openrouter/auto"

    client = create_client(
        model=judge_model,
        temperature=0.1,
        max_tokens=2000,
    )

    # Stage-specific judge prompts
    JUDGE_PROMPTS = {
        "edit_for_tts": """你是专业的 TTS 文本编辑质量评估专家。请盲评两个版本的编辑输出，不知道哪个是旧版本哪个是新版本。

输入段落: {input_text}
参考标注: {reference_annotation}

版本 A 输出:
{output_a}

版本 B 输出:
{output_b}

评估标准:
1. 文本自然度 (口语化程度、流畅性)
2. 编辑准确性 (是否正确处理数字、标点、禁用词)
3. 情感标记保留 (是否保留了原标注的情感强度)
4. 停顿标记合理性
5. 整体 TTS 友好度

请输出 JSON 格式:
{{
  "score_a": 0.0-1.0,
  "score_b": 0.0-1.0,
  "winner": "A" | "B" | "tie",
  "rationale": "详细评分理由，包括具体优缺点对比"
}}""",
        "annotate_paragraph": """你是专业的段落标注质量评估专家。请盲评两个版本的标注输出。

输入段落: {input_text}

版本 A 标注:
{output_a}

版本 B 标注:
{output_b}

评估标准:
1. 说话人识别准确性
2. 情感标注准确性 (类别 + 强度)
3. 语速、音调标注合理性
4. 停顿标注合理性
5. 音效标注完整性
6. 整体标注一致性

请输出 JSON 格式:
{{
  "score_a": 0.0-1.0,
  "score_b": 0.0-1.0,
  "winner": "A" | "B" | "tie",
  "rationale": "详细评分理由"
}}""",
        "analyze_structure": """你是专业的书籍结构分析专家。请盲评两个版本的结构分析输出。

输入书籍内容摘要: {input_text}

版本 A 分析:
{output_a}

版本 B 分析:
{output_b}

评估标准:
1. 书籍元信息提取准确性 (标题、作者、体裁、难度等)
2. 角色声线映射完整性
3. 情感快照覆盖度
4. 故事主线摘要质量
5. 全局文风备注准确性

请输出 JSON 格式:
{{
  "score_a": 0.0-1.0,
  "score_b": 0.0-1.0,
  "winner": "A" | "B" | "tie",
  "rationale": "详细评分理由"
}}""",
        "quality_judge": """你是专业的音频质量评估专家。请盲评两个版本的质量判定输出。

音频参考文本: {input_text}

版本 A 质量判定:
{output_a}

版本 B 质量判定:
{output_b}

评估标准:
1. 整体质量评分准确性
2. 问题识别完整性
3. 修复建议实用性
4. 是否正确识别需重生成

请输出 JSON 格式:
{{
  "score_a": 0.0-1.0,
  "score_b": 0.0-1.0,
  "winner": "A" | "B" | "tie",
  "rationale": "详细评分理由"
}}""",
        "synthesize": """你是专业的 TTS 合成质量评估专家。请盲评两个版本的合成输出。

输入文本: {input_text}

版本 A 合成结果:
{output_a}

版本 B 合成结果:
{output_b}

评估标准:
1. 引擎选择合理性
2. 声音 ID 选择准确性
3. 韵律覆盖参数合理性
4. 成本/时长估算准确性

请输出 JSON 格式:
{{
  "score_a": 0.0-1.0,
  "score_b": 0.0-1.0,
  "winner": "A" | "B" | "tie",
  "rationale": "详细评分理由"
}}""",
    }

    default_prompt = """你是专业的 AI 输出质量评估专家。请盲评两个版本的输出。

输入: {input_text}

版本 A 输出:
{output_a}

版本 B 输出:
{output_b}

评估标准: 输出质量、准确性、完整性、实用性

请输出 JSON 格式:
{{
  "score_a": 0.0-1.0,
  "score_b": 0.0-1.0,
  "winner": "A" | "B" | "tie",
  "rationale": "详细评分理由"
}}"""

    prompt_template = JUDGE_PROMPTS.get(stage, default_prompt)

    def judge_fn(
        input_data: Dict[str, Any], output_a: Dict[str, Any], output_b: Dict[str, Any]
    ) -> Tuple[float, float, str]:
        """
        Evaluate two outputs blindly using LLM judge.

        Returns:
            (score_a, score_b, rationale)
        """
        # Prepare input text for prompt
        if stage == "edit_for_tts":
            input_text = input_data.get("paragraph_text", "")
            reference_annotation = str(input_data.get("paragraph_annotation", {}))
            prompt = prompt_template.format(
                input_text=input_text[:2000],
                reference_annotation=reference_annotation[:1000],
                output_a=json.dumps(output_a, ensure_ascii=False, indent=2)[:3000],
                output_b=json.dumps(output_b, ensure_ascii=False, indent=2)[:3000],
            )
        elif stage == "annotate_paragraph":
            input_text = input_data.get("paragraph_text", "")
            prompt = prompt_template.format(
                input_text=input_text[:2000],
                output_a=json.dumps(output_a, ensure_ascii=False, indent=2)[:3000],
                output_b=json.dumps(output_b, ensure_ascii=False, indent=2)[:3000],
            )
        elif stage == "analyze_structure":
            input_text = input_data.get("book_text", input_data.get("text", ""))
            prompt = prompt_template.format(
                input_text=input_text[:2000],
                output_a=json.dumps(output_a, ensure_ascii=False, indent=2)[:3000],
                output_b=json.dumps(output_b, ensure_ascii=False, indent=2)[:3000],
            )
        elif stage == "quality_judge":
            input_text = input_data.get("expected_text", input_data.get("text", ""))
            prompt = prompt_template.format(
                input_text=input_text[:2000],
                output_a=json.dumps(output_a, ensure_ascii=False, indent=2)[:3000],
                output_b=json.dumps(output_b, ensure_ascii=False, indent=2)[:3000],
            )
        elif stage == "synthesize":
            input_text = input_data.get("text", "")
            prompt = prompt_template.format(
                input_text=input_text[:2000],
                output_a=json.dumps(output_a, ensure_ascii=False, indent=2)[:3000],
                output_b=json.dumps(output_b, ensure_ascii=False, indent=2)[:3000],
            )
        else:
            input_text = str(input_data)[:2000]
            prompt = default_prompt.format(
                input_text=input_text,
                output_a=json.dumps(output_a, ensure_ascii=False, indent=2)[:3000],
                output_b=json.dumps(output_b, ensure_ascii=False, indent=2)[:3000],
            )

        # Use a simple schema for the judge response
        from pydantic import BaseModel

        class JudgeOutput(BaseModel):
            score_a: float
            score_b: float
            winner: str
            rationale: str

        try:
            result = client.call(
                prompt=prompt,
                response_model=JudgeOutput,
                temperature=0.1,
            )
            output = result.output

            # Clamp scores to valid range
            score_a = max(0.0, min(1.0, output.score_a))
            score_b = max(0.0, min(1.0, output.score_b))

            # Validate winner
            winner = output.winner if output.winner in ("A", "B", "tie") else "tie"

            return score_a, score_b, output.rationale

        except Exception as e:
            logger.warning(f"LLM Judge evaluation failed: {e}, falling back to heuristic scoring")
            # Fallback to heuristic scoring
            score_a = _score_output(output_a, stage)
            score_b = _score_output(output_b, stage)
            return score_a, score_b, f"LLM Judge failed, used heuristic: {str(e)[:100]}"

    return judge_fn


# ════════════════════════════════════════════════════════════════════════════
# Pairwise LLM Judge (New - uses LLMJudge.judge_pairwise)
# ════════════════════════════════════════════════════════════════════════════


def create_pairwise_judge_fn(
    stage: str,
    judge_model: Optional[str] = None,
    router=None,
):
    """
    Create an LLM-as-a-Judge function for pairwise A/B comparison.

    Uses the LLMJudge.judge_pairwise method for structured pairwise judgment
    with per-dimension scores and statistical significance.

    Args:
        stage: Pipeline stage name
        judge_model: LLM model to use as judge
        router: Optional LLMRouter instance

    Returns:
        Function that takes (sample_id, input_data, output_a, output_b, annotation, audio_description)
        and returns PairwiseJudgment
    """
    from ..llm.judge import LLMJudge, JudgeConfig

    if judge_model is None:
        judge_model = "openrouter/auto"

    config = JudgeConfig(model=judge_model)
    judge = LLMJudge(config=config, router=router)

    def judge_fn(
        segment_id: str,
        input_data: Dict[str, Any],
        output_a: Dict[str, Any],
        output_b: Dict[str, Any],
        annotation: Optional[Dict[str, Any]] = None,
        audio_description: Optional[str] = None,
    ) -> PairwiseJudgment:
        """Evaluate two outputs pairwise using LLM judge."""
        reference_text = input_data.get("paragraph_text", input_data.get("text", ""))

        try:
            result = judge.judge_pairwise(
                segment_id=segment_id,
                stage=stage,
                output_a=output_a,
                output_b=output_b,
                reference_text=reference_text,
                annotation=annotation,
                audio_description=audio_description,
            )
            return result
        except Exception as e:
            logger.warning(f"Pairwise judge failed: {e}, falling back to heuristic")
            # Fallback to simple heuristic winner
            score_a = _score_output(output_a, stage)
            score_b = _score_output(output_b, stage)

            from ..schemas.judge import PairwiseJudgment

            return PairwiseJudgment(
                segment_id=segment_id,
                winner="A" if score_a > score_b else "B" if score_b > score_a else "tie",
                confidence=0.5,
                dimension_scores={},
                reasoning={},
                overall_reasoning=f"Fallback heuristic: {str(e)[:100]}",
                judge_model=judge_model,
            )

    return judge_fn


# ════════════════════════════════════════════════════════════════════════════
# Heuristic Scoring (Fallback)
# ════════════════════════════════════════════════════════════════════════════


@dataclass
class ABTestSample:
    """单个 A/B 测试样本."""

    sample_id: str
    stage: str
    input_data: Dict[str, Any]
    output_a: Dict[str, Any]  # v1 (control)
    output_b: Dict[str, Any]  # v2 (treatment)
    version_a: int
    version_b: int


@dataclass
class ABTestResult:
    """A/B 测试比较结果."""

    sample_id: str
    winner: str  # "A" | "B" | "tie"
    score_a: float
    score_b: float
    rationale: str = ""


@dataclass
class ABTestReport:
    """A/B 测试报告."""

    stage: str
    version_a: int
    version_b: int
    num_samples: int
    results: List[ABTestResult]
    a_wins: int = 0
    b_wins: int = 0
    ties: int = 0
    avg_score_a: float = 0.0
    avg_score_b: float = 0.0
    improvement_pct: float = 0.0
    recommendation: str = ""
    generated_at: str = ""
    # Statistical significance fields
    p_value: float = 1.0
    confidence_interval: Tuple[float, float] = (0.0, 0.0)
    is_significant: bool = False
    significance_level: float = 0.05


def _score_output(output: Dict[str, Any], stage: str) -> float:
    """对单个输出进行评分 (0-1).

    基于输出质量启发式评分。
    实际使用时可以用 LLM-as-a-Judge 进行盲评。
    """
    score = 0.5  # baseline

    if stage == "edit_for_tts":
        # Check edited_text exists and has content
        text = output.get("edited_text", "")
        if text:
            score += 0.1 * min(len(text) / 200, 1.0)

        # Check forbidden_content_removed is correct
        if output.get("forbidden_content_removed") is not None:
            score += 0.1

        # Confidence score
        confidence = output.get("confidence", 0.0)
        if isinstance(confidence, (int, float)):
            score += 0.1 * confidence

    elif stage == "quality_judge":
        # Quality judgment scoring
        overall = output.get("overall_score", 0.0)
        if isinstance(overall, (int, float)):
            score += 0.2 * overall

        # Has valid issues
        issues = output.get("issues", [])
        if issues:
            score += 0.1

        # Has fix suggestions
        fixes = output.get("fix_suggestions", [])
        if fixes:
            score += 0.1

    elif stage == "annotate_paragraph":
        # Check required fields
        for field in ["emotion", "speaker_canonical_name", "is_dialogue"]:
            if output.get(field) is not None:
                score += 0.1

        emotion_intensity = output.get("emotion_intensity", 0.0)
        if isinstance(emotion_intensity, (int, float)) and 0 < emotion_intensity <= 1:
            score += 0.1

    return min(score, 1.0)


def _compute_statistical_significance(
    results: List[ABTestResult],
    significance_level: float = 0.05,
) -> Tuple[float, Tuple[float, float], bool]:
    """
    Compute statistical significance using paired t-test for A/B test results.

    Returns:
        (p_value, confidence_interval, is_significant)
    """
    if not results:
        return 1.0, (0.0, 0.0), False

    n = len(results)
    # Compute differences (B - A) for each paired sample
    differences = [r.score_b - r.score_a for r in results]

    mean_diff = sum(differences) / n

    # Compute standard deviation of differences
    if n > 1:
        variance = sum((d - mean_diff) ** 2 for d in differences) / (n - 1)
        std_diff = math.sqrt(variance)
    else:
        std_diff = 0.0

    # Standard error
    if n > 1 and std_diff > 0:
        se = std_diff / math.sqrt(n)

        # t-statistic
        t_stat = mean_diff / se

        # Two-tailed p-value using t-distribution approximation
        # For small samples, use t-distribution; for large, normal approx
        df = n - 1
        if df >= 30:
            # Normal approximation
            p_value = 2 * (1 - 0.5 * (1 + math.erf(abs(t_stat) / math.sqrt(2))))
        else:
            # t-distribution approximation using incomplete beta function
            # Simplified: use normal approximation with small sample warning
            p_value = 2 * (1 - 0.5 * (1 + math.erf(abs(t_stat) / math.sqrt(2))))

        # Confidence interval for mean difference
        # t_critical for 95% CI with df degrees of freedom
        if df >= 30:
            t_critical = 1.96
        elif df >= 10:
            t_critical = 2.228
        else:
            t_critical = 2.776  # df=4

        ci_lower = mean_diff - t_critical * se
        ci_upper = mean_diff + t_critical * se
        confidence_interval = (ci_lower, ci_upper)

        is_significant = p_value < significance_level
    else:
        p_value = 1.0
        confidence_interval = (0.0, 0.0)
        is_significant = False

    return p_value, confidence_interval, is_significant


def run_ab_test(
    stage: str,
    samples: List[ABTestSample],
    judge_fn=None,
    significance_level: float = 0.05,
    use_llm_judge: bool = False,
    judge_model: str = None,
) -> ABTestReport:
    """执行 A/B 测试.

    Args:
        stage: Pipeline stage name
        samples: A/B 测试样本列表
        judge_fn: 可选的自定义评分函数 (默认使用启发式评分)
                  可以是旧签名: (output) -> float
                  或新签名: (input_data, output_a, output_b) -> (score_a, score_b, rationale)
        significance_level: 显著性水平 (默认 0.05)
        use_llm_judge: 是否使用 LLM-as-a-Judge 进行盲评
        judge_model: LLM Judge 使用的模型

    Returns:
        ABTestReport 报告
    """
    if not samples:
        return ABTestReport(
            stage=stage,
            version_a=0,
            version_b=0,
            num_samples=0,
            results=[],
            recommendation="无样本数据",
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    # Create LLM Judge if requested
    if use_llm_judge and judge_fn is None:
        judge_fn = create_llm_judge_fn(stage, judge_model)

    # Determine judge function signature
    # Old signature: (output) -> float
    # New signature: (input_data, output_a, output_b) -> (score_a, score_b, rationale)
    results: List[ABTestResult] = []
    a_wins = b_wins = ties = 0
    total_a = total_b = 0.0

    for sample in samples:
        if judge_fn is not None:
            # Check if it's the new LLM Judge signature (takes 3 args)
            import inspect

            sig = inspect.signature(judge_fn)
            if len(sig.parameters) >= 3:
                # New signature: (input_data, output_a, output_b) -> (score_a, score_b, rationale)
                score_a, score_b, rationale = judge_fn(sample.input_data, sample.output_a, sample.output_b)
            else:
                # Old signature: (output) -> float
                score_a = judge_fn(sample.output_a)
                score_b = judge_fn(sample.output_b)
                rationale = ""
        else:
            # Fallback to heuristic
            score_a = _score_output(sample.output_a, stage)
            score_b = _score_output(sample.output_b, stage)
            rationale = ""

        total_a += score_a
        total_b += score_b

        if score_a > score_b:
            winner = "A"
            a_wins += 1
        elif score_b > score_a:
            winner = "B"
            b_wins += 1
        else:
            winner = "tie"
            ties += 1

        results.append(
            ABTestResult(
                sample_id=sample.sample_id,
                winner=winner,
                score_a=score_a,
                score_b=score_b,
                rationale=rationale,
            )
        )

    n = len(samples)
    avg_a = total_a / n
    avg_b = total_b / n
    improvement = ((avg_b - avg_a) / max(avg_a, 0.001)) * 100

    # Generate recommendation
    if b_wins > a_wins and improvement > 2:
        recommendation = (
            f"✅ 推荐升级: v{samples[0].version_b} 在 {b_wins}/{n} 样本中优于 "
            f"v{samples[0].version_a} (提升 {improvement:.1f}%)"
        )
    elif a_wins > b_wins:
        recommendation = (
            f"❌ 不建议升级: v{samples[0].version_a} 仍优于 " f"v{samples[0].version_b} ({a_wins}/{n} 样本)"
        )
    else:
        recommendation = (
            f"🔶 结果不明确: v{samples[0].version_a} 和 v{samples[0].version_b} " f"差异不大 (平局 {ties}/{n})"
        )

    versions = (samples[0].version_a, samples[0].version_b)

    # Compute statistical significance
    p_value, confidence_interval, is_significant = _compute_statistical_significance(results, significance_level)

    report = ABTestReport(
        stage=stage,
        version_a=versions[0],
        version_b=versions[1],
        num_samples=n,
        results=results,
        a_wins=a_wins,
        b_wins=b_wins,
        ties=ties,
        avg_score_a=avg_a,
        avg_score_b=avg_b,
        improvement_pct=improvement,
        recommendation=recommendation,
        generated_at=datetime.now(timezone.utc).isoformat(),
        p_value=p_value,
        confidence_interval=confidence_interval,
        is_significant=is_significant,
        significance_level=significance_level,
    )

    logger.info(
        f"A/B Test [{stage}] v{versions[0]} vs v{versions[1]}: "
        f"A={avg_a:.3f} B={avg_b:.3f} "
        f"improvement={improvement:+.1f}% "
        f"p={p_value:.4f} "
        f"CI=[{confidence_interval[0]:.4f}, {confidence_interval[1]:.4f}] "
        f"significant={'yes' if is_significant else 'no'} "
        f"recommendation={recommendation[:60]}"
    )

    return report


# ════════════════════════════════════════════════════════════════════════════
# Pairwise A/B Testing (New)
# ════════════════════════════════════════════════════════════════════════════


@dataclass
class PairwiseABTestResult:
    """单个 pairwise 判定结果."""

    segment_id: str
    judgment: PairwiseJudgment


@dataclass
class PairwiseABTestReport:
    """Pairwise A/B 测试报告."""

    stage: str
    version_a: int
    version_b: int
    num_samples: int
    results: List[PairwiseABTestResult]
    a_wins: int = 0
    b_wins: int = 0
    ties: int = 0
    avg_score_a: float = 0.0
    avg_score_b: float = 0.0
    improvement_pct: float = 0.0
    recommendation: str = ""
    generated_at: str = ""
    # Statistical significance (from paired t-test on dimension scores)
    p_value: float = 1.0
    confidence_interval: Tuple[float, float] = (0.0, 0.0)
    is_significant: bool = False
    significance_level: float = 0.05


def run_ab_test_pairwise(
    stage: str,
    samples: List[ABTestSample],
    judge_fn=None,
    significance_level: float = 0.05,
    use_llm_judge: bool = False,
    judge_model: str = None,
    router=None,
) -> PairwiseABTestReport:
    """执行 Pairwise A/B 测试（使用 LLMJudge.judge_pairwise）。

    Args:
        stage: Pipeline stage name
        samples: A/B 测试样本列表
        judge_fn: 可选的自定义 pairwise 评判函数
                  (segment_id, input_data, output_a, output_b, annotation, audio_description) -> PairwiseJudgment
        significance_level: 显著性水平
        use_llm_judge: 是否使用 LLM-as-a-Judge
        judge_model: LLM Judge 模型
        router: 可选的 LLMRouter 实例

    Returns:
        PairwiseABTestReport 报告
    """
    if not samples:
        return PairwiseABTestReport(
            stage=stage,
            version_a=0,
            version_b=0,
            num_samples=0,
            results=[],
            recommendation="无样本数据",
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    # Create pairwise LLM Judge if requested
    if use_llm_judge and judge_fn is None:
        judge_fn = create_pairwise_judge_fn(stage, judge_model, router)

    results: List[PairwiseABTestResult] = []
    a_wins = b_wins = ties = 0
    total_a = total_b = 0.0

    for sample in samples:
        # Get annotation and audio_description if available
        annotation = sample.input_data.get("paragraph_annotation")
        audio_description = sample.input_data.get("audio_description")
        segment_id = sample.sample_id

        if judge_fn is not None:
            judgment = judge_fn(
                segment_id=segment_id,
                input_data=sample.input_data,
                output_a=sample.output_a,
                output_b=sample.output_b,
                annotation=annotation,
                audio_description=audio_description,
            )
        else:
            # Fallback to heuristic
            score_a = _score_output(sample.output_a, stage)
            score_b = _score_output(sample.output_b, stage)

            from ..schemas.judge import PairwiseJudgment

            judgment = PairwiseJudgment(
                segment_id=segment_id,
                winner="A" if score_a > score_b else "B" if score_b > score_a else "tie",
                confidence=0.5,
                dimension_scores={},
                reasoning={},
                overall_reasoning="Heuristic fallback",
            )

        results.append(PairwiseABTestResult(segment_id=segment_id, judgment=judgment))

        # Accumulate average scores from dimension_scores
        dim_scores = judgment.dimension_scores
        if dim_scores:
            total_a += sum(s[0] for s in dim_scores.values())
            total_b += sum(s[1] for s in dim_scores.values())
        else:
            total_a += 0.5
            total_b += 0.5

        if judgment.winner == "A":
            a_wins += 1
        elif judgment.winner == "B":
            b_wins += 1
        else:
            ties += 1

    n = len(samples)
    avg_a = total_a / max(n, 1)
    avg_b = total_b / max(n, 1)
    improvement = ((avg_b - avg_a) / max(avg_a, 0.001)) * 100

    # Generate recommendation
    if b_wins > a_wins and improvement > 2:
        recommendation = (
            f"✅ 推荐升级: v{samples[0].version_b} 在 {b_wins}/{n} 样本中优于 "
            f"v{samples[0].version_a} (提升 {improvement:.1f}%)"
        )
    elif a_wins > b_wins:
        recommendation = (
            f"❌ 不建议升级: v{samples[0].version_a} 仍优于 "
            f"v{samples[0].version_b} ({a_wins}/{n} 样本)"
        )
    else:
        recommendation = (
            f"🔶 结果不明确: v{samples[0].version_a} 和 v{samples[0].version_b} "
            f"差异不大 (平局 {ties}/{n})"
        )

    versions = (samples[0].version_a, samples[0].version_b)

    # Compute statistical significance using paired t-test on overall scores
    # For pairwise, we use the difference in winner scores per sample
    differences = []
    for r in results:
        dim_scores = r.judgment.dimension_scores
        if dim_scores:
            diff = sum(s[1] - s[0] for s in dim_scores.values()) / len(dim_scores)
        else:
            diff = 0.0 if r.judgment.winner == "tie" else (1.0 if r.judgment.winner == "B" else -1.0)
        differences.append(diff)

    p_value, confidence_interval, is_significant = _compute_paired_ttest(
        differences, significance_level
    )

    report = PairwiseABTestReport(
        stage=stage,
        version_a=versions[0],
        version_b=versions[1],
        num_samples=n,
        results=results,
        a_wins=a_wins,
        b_wins=b_wins,
        ties=ties,
        avg_score_a=avg_a,
        avg_score_b=avg_b,
        improvement_pct=improvement,
        recommendation=recommendation,
        generated_at=datetime.now(timezone.utc).isoformat(),
        p_value=p_value,
        confidence_interval=confidence_interval,
        is_significant=is_significant,
        significance_level=significance_level,
    )

    logger.info(
        f"Pairwise A/B Test [{stage}] v{versions[0]} vs v{versions[1]}: "
        f"A_wins={a_wins} B_wins={b_wins} ties={ties} "
        f"avg_A={avg_a:.3f} avg_B={avg_b:.3f} "
        f"improvement={improvement:+.1f}% "
        f"p={p_value:.4f} "
        f"CI=[{confidence_interval[0]:.4f}, {confidence_interval[1]:.4f}] "
        f"significant={'yes' if is_significant else 'no'} "
        f"recommendation={recommendation[:60]}"
    )

    return report


def _compute_paired_ttest(
    differences: List[float],
    significance_level: float = 0.05,
) -> Tuple[float, Tuple[float, float], bool]:
    """
    Compute paired t-test on differences.

    Returns:
        (p_value, confidence_interval, is_significant)
    """
    if not differences:
        return 1.0, (0.0, 0.0), False

    n = len(differences)
    mean_diff = sum(differences) / n

    if n > 1:
        variance = sum((d - mean_diff) ** 2 for d in differences) / (n - 1)
        std_diff = math.sqrt(variance)
    else:
        std_diff = 0.0

    if n > 1 and std_diff > 0:
        se = std_diff / math.sqrt(n)
        t_stat = mean_diff / se

        df = n - 1
        if df >= 30:
            p_value = 2 * (1 - 0.5 * (1 + math.erf(abs(t_stat) / math.sqrt(2))))
        else:
            p_value = 2 * (1 - 0.5 * (1 + math.erf(abs(t_stat) / math.sqrt(2))))

        # Confidence interval
        if df >= 30:
            t_critical = 1.96
        elif df >= 10:
            t_critical = 2.228
        else:
            t_critical = 2.776

        ci_lower = mean_diff - t_critical * se
        ci_upper = mean_diff + t_critical * se
        confidence_interval = (ci_lower, ci_upper)
        is_significant = p_value < significance_level
    else:
        p_value = 1.0
        confidence_interval = (0.0, 0.0)
        is_significant = False

    return p_value, confidence_interval, is_significant


def build_ab_samples(
    stage: str,
    golden_examples: List[Dict[str, Any]],
    old_version: int,
    new_version: int,
) -> List[ABTestSample]:
    """从黄金数据集构建 A/B 测试样本.

    每个样本: golden example input + old version output + new version output.
    这里使用 simplified approach — 实际运行会在完整 pipeline 中执行。
    """
    samples: List[ABTestSample] = []
    for example in golden_examples:
        sample = ABTestSample(
            sample_id=str(uuid.uuid4()),
            stage=stage,
            input_data=example.get("input", {}),
            output_a=example.get("output_old", example.get("output", {})),
            output_b=example.get("output_new", example.get("output", {})),
            version_a=old_version,
            version_b=new_version,
        )
        samples.append(sample)
    return samples


def run_ab_test_with_pipeline_rerun(
    stage: str,
    golden_examples: List[Dict[str, Any]],
    old_version: int,
    new_version: int,
    judge_fn=None,
    significance_level: float = 0.05,
    mock_mode: bool = True,
) -> ABTestReport:
    """
    Run A/B test with real pipeline re-run for both versions.

    This function:
    1. Runs the pipeline with old_version prompt on golden dataset inputs
    2. Runs the pipeline with new_version prompt on golden dataset inputs
    3. Uses LLM Judge (or heuristic) to blindly evaluate outputs
    4. Returns statistical comparison report

    Args:
        stage: Pipeline stage name (golden dataset directory name)
        golden_examples: Golden dataset examples with input data
        old_version: Old prompt version number
        new_version: New prompt version number
        judge_fn: Optional custom judge function
        significance_level: Statistical significance level
        mock_mode: Whether to run pipeline in mock mode

    Returns:
        ABTestReport with statistical comparison
    """
    from ..feedback.promotion_gate import _golden_to_pipeline_stage, _run_stage_with_prompt_version

    pipeline_stage = _golden_to_pipeline_stage(stage)

    # Build samples with real pipeline outputs
    samples: List[ABTestSample] = []

    for example in golden_examples:
        if "input" not in example:
            continue

        input_data = example["input"]

        try:
            # Run with old version
            output_a = _run_stage_with_prompt_version(pipeline_stage, old_version, input_data, mock_mode=mock_mode)
            if hasattr(output_a, "model_dump"):
                output_a = output_a.model_dump()
            elif hasattr(output_a, "dict"):
                output_a = output_a.dict()

            # Run with new version
            output_b = _run_stage_with_prompt_version(pipeline_stage, new_version, input_data, mock_mode=mock_mode)
            if hasattr(output_b, "model_dump"):
                output_b = output_b.model_dump()
            elif hasattr(output_b, "dict"):
                output_b = output_b.dict()

            sample = ABTestSample(
                sample_id=str(uuid.uuid4()),
                stage=stage,
                input_data=input_data,
                output_a=output_a,
                output_b=output_b,
                version_a=old_version,
                version_b=new_version,
            )
            samples.append(sample)

        except Exception as e:
            logger.warning(f"Failed to run pipeline for A/B sample: {e}")
            continue

    if not samples:
        logger.warning("No valid A/B samples generated from pipeline re-run")
        return ABTestReport(
            stage=stage,
            version_a=old_version,
            version_b=new_version,
            num_samples=0,
            results=[],
            recommendation="Pipeline re-run failed for all samples",
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    # Use provided judge_fn or create LLM Judge
    if judge_fn is None:
        judge_fn = create_llm_judge_fn(stage)

    # Run A/B test with the judge function
    return run_ab_test(stage, samples, judge_fn, significance_level)


def blind_evaluate(
    ab_report: ABTestReport,
    human_ratings: Optional[List[Dict[str, Any]]] = None,
) -> ABTestReport:
    """在盲评结果上叠加人工评分.

    如果提供了 human_ratings，用人工评分覆盖部分机器评分。
    """
    if not human_ratings:
        return ab_report

    # Merge human ratings into existing results
    rating_map = {r.get("sample_id"): r for r in human_ratings}

    for result in ab_report.results:
        if result.sample_id in rating_map:
            hr = rating_map[result.sample_id]
            result.score_a = hr.get("score_a", result.score_a)
            result.score_b = hr.get("score_b", result.score_b)

            if result.score_a > result.score_b:
                result.winner = "A"
            elif result.score_b > result.score_a:
                result.winner = "B"
            else:
                result.winner = "tie"

            if hr.get("rationale"):
                result.rationale = hr["rationale"]

    # Recompute aggregate stats
    n = len(ab_report.results)
    ab_report.a_wins = sum(1 for r in ab_report.results if r.winner == "A")
    ab_report.b_wins = sum(1 for r in ab_report.results if r.winner == "B")
    ab_report.ties = sum(1 for r in ab_report.results if r.winner == "tie")
    ab_report.avg_score_a = sum(r.score_a for r in ab_report.results) / n
    ab_report.avg_score_b = sum(r.score_b for r in ab_report.results) / n
    ab_report.improvement_pct = (
        (ab_report.avg_score_b - ab_report.avg_score_a) / max(ab_report.avg_score_a, 0.001)
    ) * 100

    # Recompute statistical significance
    p_value, confidence_interval, is_significant = _compute_statistical_significance(
        ab_report.results, ab_report.significance_level
    )
    ab_report.p_value = p_value
    ab_report.confidence_interval = confidence_interval
    ab_report.is_significant = is_significant

    # Update recommendation with significance info
    if ab_report.b_wins > ab_report.a_wins and ab_report.improvement_pct > 2:
        significance_str = "显著" if is_significant else "不显著"
        ab_report.recommendation = (
            f"✅ 推荐升级: v{ab_report.version_b} 在 {ab_report.b_wins}/{n} 样本中优于 "
            f"v{ab_report.version_a} (提升 {ab_report.improvement_pct:.1f}%, {significance_str}, p={p_value:.4f})"
        )
    elif ab_report.a_wins > ab_report.b_wins:
        ab_report.recommendation = (
            f"❌ 不建议升级: v{ab_report.version_a} 仍优于 " f"v{ab_report.version_b} ({ab_report.a_wins}/{n} 样本)"
        )
    else:
        ab_report.recommendation = (
            f"🔶 结果不明确: v{ab_report.version_a} 和 v{ab_report.version_b} " f"差异不大 (平局 {ab_report.ties}/{n})"
        )

    logger.info(
        f"Blind evaluation updated: p={p_value:.4f} "
        f"CI=[{confidence_interval[0]:.4f}, {confidence_interval[1]:.4f}] "
        f"significant={'yes' if is_significant else 'no'}"
    )

    return ab_report
