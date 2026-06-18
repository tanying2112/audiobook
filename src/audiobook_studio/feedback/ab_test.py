"""
E5 — A/B 测试框架

对比 v1 vs v2 Prompt 版本的输出质量，支持盲评。
"""

import json
import logging
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..schemas import ParagraphAnnotation, QualityJudgment

logger = logging.getLogger(__name__)


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


def run_ab_test(
    stage: str,
    samples: List[ABTestSample],
    judge_fn=None,
) -> ABTestReport:
    """执行 A/B 测试.

    Args:
        stage: Pipeline stage name
        samples: A/B 测试样本列表
        judge_fn: 可选的自定义评分函数 (默认使用启发式评分)

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

    scorer = judge_fn or (lambda out: _score_output(out, stage))
    results: List[ABTestResult] = []
    a_wins = b_wins = ties = 0
    total_a = total_b = 0.0

    for sample in samples:
        score_a = scorer(sample.output_a)
        score_b = scorer(sample.output_b)
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

        results.append(ABTestResult(
            sample_id=sample.sample_id,
            winner=winner,
            score_a=score_a,
            score_b=score_b,
        ))

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
            f"❌ 不建议升级: v{samples[0].version_a} 仍优于 "
            f"v{samples[0].version_b} ({a_wins}/{n} 样本)"
        )
    else:
        recommendation = (
            f"🔶 结果不明确: v{samples[0].version_a} 和 v{samples[0].version_b} "
            f"差异不大 (平局 {ties}/{n})"
        )

    versions = (samples[0].version_a, samples[0].version_b)

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
    )

    logger.info(
        f"A/B Test [{stage}] v{versions[0]} vs v{versions[1]}: "
        f"A={avg_a:.3f} B={avg_b:.3f} "
        f"improvement={improvement:+.1f}% "
        f"recommendation={recommendation[:60]}"
    )

    return report


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
        (ab_report.avg_score_b - ab_report.avg_score_a)
        / max(ab_report.avg_score_a, 0.001)
    ) * 100

    return ab_report
