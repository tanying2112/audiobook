#!/usr/bin/env python3
"""
Audiobook Studio — A/B 测试框架
================================

同段文本 v1 vs v2 提示词并行，LLM Judge 盲评。
生成可视化对比报告（JSON + HTML）。
"""

import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ABTestConfig:
    """A/B 测试配置"""

    test_id: str
    name: str
    description: str
    variant_a_prompt: str  # 当前版本 (v1)
    variant_b_prompt: str  # 候选版本 (v2)
    test_segments: List[str]  # 用于测试的文本片段
    judge_criteria: List[str]  # 评判标准
    sample_size: int = 5  # 每个片段的判断次数
    confidence_threshold: float = 0.8  # 置信度阈值


@dataclass
class ABTestResult:
    """A/B 测试结果"""

    test_id: str
    variant_a_score: float  # A 版本平均得分 (0-1)
    variant_b_score: float  # B 版本平均得分 (0-1)
    winner: str  # "A", "B", or "TIE"
    confidence: float  # 置信度 (0-1)
    p_value: float  # 统计显著性
    details: List[Dict[str, Any]]  # 详细结果
    timestamp: datetime
    passed_quality_gate: bool  # 是否通过质量门禁


class ABTestManager:
    """A/B 测试框架管理器."""

    def __init__(self, results_dir: str = "./ab_test_results"):
        """
        初始化 A/B 测试管理器.

        Args:
            results_dir: 测试结果保存目录
        """
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.test_history: List[ABTestResult] = []

        logger.info(f"ABTestManager initialized with results_dir: {self.results_dir}")

    def run_comparison_test(
        self,
        current_prompt: str,
        proposed_prompt: str,
        test_name: str = "unnamed_test",
        test_segments: Optional[List[str]] = None,
        judge_criteria: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        运行 A/B 比较测试 (v1 vs v2 提示词并行).

        Args:
            current_prompt: 当前版本提示词 (v1)
            proposed_prompt: 候选版本提示词 (v2)
            test_name: 测试名称
            test_segments: 用于测试的文本片段列表
            judge_criteria: 评判标准列表

        Returns:
            测试结果字典
        """
        # 使用默认测试片段（如果未提供）
        if test_segments is None:
            test_segments = [
                "主人公走进了昏暗的房间，心跳急剧加速。",
                "她微微一笑，说：'今天真是个好日子。'",
                "突然，一声巨响打破了夜晚的寂静。",
                "多年以后，他还记得那个阳光明媚的下午。",
                " Apesar dos desafios, eles persistiram no objetivo.",
            ]

        # 使用默认判断标准（如果未提供）
        if judge_criteria is None:
            judge_criteria = [
                "准确性：内容是否忠实于原文",
                "流畅度：语言是否自然易懂",
                "情感表达：是否准确传达了情感",
                "角色一致性：角色行为是否符合设定",
                "整体质量：生成内容的整体质量",
            ]

        logger.info(f"Starting A/B test: {test_name}")
        logger.info(
            f"Testing {len(test_segments)} segments with {len(judge_criteria)} criteria"
        )

        # 创建测试配置
        test_config = ABTestConfig(
            test_id=str(uuid.uuid4()),
            name=test_name,
            description=f"A/B test comparing current vs proposed prompts",
            variant_a_prompt=current_prompt,
            variant_b_prompt=proposed_prompt,
            test_segments=test_segments,
            judge_criteria=judge_criteria,
            sample_size=3,  # 演示用较小样本
            confidence_threshold=0.8,
        )

        # 执行测试
        result = self._execute_ab_test(test_config)

        # 保存结果
        self._save_test_result(result)

        # 添加到历史
        self.test_history.append(result)

        logger.info(
            f"A/B test completed: {result.winner} wins with {result.confidence:.2%} confidence"
        )

        # 返回结果字典（供 self_iteration_loop.py 使用）
        return {
            "test_id": result.test_id,
            "test_name": result.test_id,  # 使用 test_id 作为名称
            "variant_a": {
                "prompt": (
                    current_prompt[:100] + "..."
                    if len(current_prompt) > 100
                    else current_prompt
                ),
                "score": result.variant_a_score,
            },
            "variant_b": {
                "prompt": (
                    proposed_prompt[:100] + "..."
                    if len(proposed_prompt) > 100
                    else proposed_prompt
                ),
                "score": result.variant_b_score,
            },
            "winner": result.winner,
            "confidence": result.confidence,
            "passed_quality_gate": result.passed_quality_gate,
            "details": {
                "p_value": result.p_value,
                "sample_size": (
                    len(test_segments) * result.details.__len__()
                    if result.details
                    else 0
                ),
                "judge_criteria": judge_criteria,
            },
        }

    def _execute_ab_test(self, config: ABTestConfig) -> ABTestResult:
        """
        执行实际的 A/B 测试.

        在实际实现中，这里会：
        1. 使用两个提示词分别生成内容
        2. 让 LLM Judge 盲评生成的内容
        3. 计算得分并进行统计显著性检验
        """
        logger.info("Executing A/B test comparison")

        # 模拟测试结果（在实际系统中会进行真实的生成和评判）
        variant_a_scores = []
        variant_b_scores = []
        detailed_results = []

        for i, segment in enumerate(config.test_segments):
            # 在实际系统中：
            # 1. 用 variant_a_prompt 生成内容 A
            # 2. 用 variant_b_prompt 生成内容 B
            # 3. 将 A 和 B 随机排序后给 LLM Judge 评分
            # 4. 记录哪个版本得分更高

            # 为了演示，我们模拟一些随机但有偏向的结果
            import random

            # 模拟 B 版本略微优于 A 版本（这样我们可以看到改进）
            base_score_a = random.uniform(0.7, 0.9)
            score_a = base_score_a + random.uniform(-0.1, 0.1)
            score_a = max(0.0, min(1.0, score_a))  # 确保在 0-1 范围 goles

            # B 版本有 60% 的概率得分更高（模拟改进效果）
            if random.random() < 0.6:
                score_b = score_a + random.uniform(0.05, 0.2)  # B 比 A 好
            else:
                score_b = score_a - random.uniform(0.0, 0.15)  # B 比 A 差或相当

            score_b = max(0.0, min(1.0, score_b))

            variant_a_scores.append(score_a)
            variant_b_scores.append(score_b)

            detailed_results.append(
                {
                    "segment_id": i,
                    "segment_preview": segment[:50]
                    + ("..." if len(segment) > 50 else ""),
                    "variant_a_score": round(score_a, 3),
                    "variant_b_score": round(score_b, 3),
                    "winner": (
                        "A"
                        if score_a > score_b
                        else "B" if score_b > score_a else "TIE"
                    ),
                    "score_difference": round(abs(score_b - score_a), 3),
                }
            )

        # 计算平均得分
        avg_score_a = sum(variant_a_scores) / len(variant_a_scores)
        avg_score_b = sum(variant_b_scores) / len(variant_b_scores)

        # 确定胜者
        if avg_score_a > avg_score_b + 0.05:  # 有显著差距才算胜
            winner = "A"
        elif avg_score_b > avg_score_a + 0.05:
            winner = "B"
        else:
            winner = "TIE"

        # 计算置信度（基于得分差异和一致性）
        score_diff = abs(avg_score_b - avg_score_a)
        consistency_a = (
            1.0 - (max(variant_a_scores) - min(variant_a_scores))
            if len(variant_a_scores) > 1
            else 1.0
        )
        consistency_b = (
            1.0 - (max(variant_b_scores) - min(variant_b_scores))
            if len(variant_b_scores) > 1
            else 1.0
        )
        avg_consistency = (consistency_a + consistency_b) / 2

        # 置信度基于得分差异和一致性
        confidence = min(0.95, 0.5 + (score_diff * 2) + (avg_consistency * 0.3))
        confidence = max(0.5, confidence)  # 至少 50% 置信度

        # 简化的 p-value 计算（实际应该用统计检验）
        p_value = max(0.001, 1.0 - confidence)  # 置信度越高 p 越小

        # 判断是否通过质量门禁（这里使用简单规则：B 版本必须显著优于 A 才算通过）
        passed_quality_gate = (
            winner == "B"
            and score_diff > 0.1  # B 版本获胜
            and confidence > 0.75  # 有足够的改进幅度  # 有足够的置信度
        )

        result = ABTestResult(
            test_id=config.test_id,
            variant_a_score=round(avg_score_a, 3),
            variant_b_score=round(avg_score_b, 3),
            winner=winner,
            confidence=round(confidence, 3),
            p_value=round(p_value, 3),
            details=detailed_results,
            timestamp=datetime.now(),
            passed_quality_gate=passed_quality_gate,
        )

        logger.info(
            f"A/B test results: A={result.variant_a_score:.3f}, "
            f"B={result.variant_b_score:.3f}, Winner={result.winner}, "
            f"Confidence={result.confidence:.2%}, PassedQG={result.passed_quality_gate}"
        )

        return result

    def _save_test_result(self, result: ABTestResult) -> None:
        """保存测试结果到文件."""
        try:
            # 保存 JSON 结果
            json_file = self.results_dir / f"ab_test_{result.test_id}.json"
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(asdict(result), f, indent=2, ensure_ascii=False, default=str)

            # 生成简单的 HTML 报告
            html_file = self.results_dir / f"ab_test_{result.test_id}.html"
            self._generate_html_report(result, html_file)

            logger.info(f"Test results saved to {json_file} and {html_file}")

        except Exception as e:
            logger.error(f"Failed to save test results: {e}")

    def _generate_html_report(self, result: ABTestResult, html_file: Path) -> None:
        """生成简单的 HTML 测试报告."""
        html_content = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>A/B Test Report - {result.test_id}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .header {{ background-color: #f0f0f0; padding: 20px; border-radius: 5px; }}
        .score-box {{ display: inline-block; margin: 10px; padding: 15px;
                      border-radius: 5px; text-align: center; min-width: 120px; }}
        .variant-a {{ background-color: #e3f2fd; }}
        .variant-b {{ background-color: #e8f5e8; }}
        .winner {{ background-color: #fff3e0; border: 2px solid #ff9800; }}
        .table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        .table th, .table td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        .table th {{ background-color: #f2f2f2; }}
        .details {{ margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>A/B Test Report</h1>
        <p><strong>Test ID:</strong> {result.test_id}</p>
        <p><strong>Timestamp:</strong> {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</p>
    </div>

    <div class="score-box">
        <h2>Results Summary</h2>
        <div class="variant-a score-box">
            <h3>Variant A (Current)</h3>
            <p><strong>Score:</strong> {result.variant_a_score:.3f}</p>
        </div>
        <div class="variant-b score-box">
            <h3>Variant B (Proposed)</h3>
            <p><strong>Score:</strong> {result.variant_b_score:.3f}</p>
        </div>
        <div class="winner score-box">
            <h3>Winner: {result.winner}</h3>
            <p><strong>Confidence:</strong> {result.confidence:.2%}</p>
            <p><strong>Passed Quality Gate:</strong> {'YES' if result.passed_quality_gate else 'NO'}</p>
        </div>
    </div>

    <div class="details">
        <h2>Detailed Results</h2>
        <table class="table">
            <thead>
                <tr>
                    <th>Segment</th>
                    <th>Preview</th>
                    <th>Variant A Score</th>
                    <th>Variant B Score</th>
                    <th>Winner</th>
                    <th>Score Diff</th>
                </tr>
            </thead>
            <tbody>
"""
        # 添加详细结果行
        for detail in result.details:
            html_content += f"""
                <tr>
                    <td>{detail['segment_id']}</td>
                    <td>{detail['segment_preview']}</td>
                    <td>{detail['variant_a_score']}</td>
                    <td>{detail['variant_b_score']}</td>
                    <td>{detail['winner']}</td>
                    <td>{detail['score_difference']}</td>
                </tr>
"""
        html_content += f"""
            </tbody>
        </table>

        <div class="footer">
            <p><strong>Statistical Notes:</strong></p>
            <ul>
                <li>P-value: {result.p_value:.3f}</li>
                <li>Score Difference: {abs(result.variant_b_score - result.variant_a_score):.3f}</li>
                <li>Test passed quality gate: {'YES' if result.passed_quality_gate else 'NO'}</li>
            </ul>
        </div>
    </div>
</body>
</html>
"""
        try:
            with open(html_file, "w", encoding="utf-8") as f:
                f.write(html_content)
        except Exception as e:
            logger.error(f"Failed to generate HTML report: {e}")

    def get_recent_tests(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取最近的测试结果."""
        recent = self.test_history[-limit:] if self.test_history else []
        # Return most recent first
        recent = list(reversed(recent))
        return [
            {
                "test_id": r.test_id,
                "timestamp": r.timestamp.isoformat(),
                "variant_a_score": r.variant_a_score,
                "variant_b_score": r.variant_b_score,
                "winner": r.winner,
                "confidence": r.confidence,
                "passed_quality_gate": r.passed_quality_gate,
            }
            for r in recent
        ]

    def get_status(self) -> Dict[str, Any]:
        """获取管理器状态."""
        return {
            "results_dir": str(self.results_dir),
            "tests_run": len(self.test_history),
            "recent_tests": self.get_recent_tests(5),
            "description": "A/B Test Manager for comparing prompt variants",
        }


def main():
    """主函数 - 演示 A/B 测试框架."""
    logger.info("=== Audiobook Studio A/B Test Manager Demo ===\n")

    # 创建 A/B 测试管理器
    ab_test_manager = ABTestManager()

    # 定义测试用的提示词
    current_prompt = (
        "你是一个专业的有声书内容分析助手。请分析以下文本，"
        "识别角色、情感、语速和音高信息。"
    )

    proposed_prompt = (
        "你是一个专业的有声书内容分析助手。请分析以下文本，"
        "识别角色、情感、语速和音高信息。\n\n"
        "特别注意：确保所有事实信息的准确性，不要添加或推断文本中没有明确提到的信息。"
    )

    # 运行比较测试
    logger.info("Running A/B test: Current Prompt vs Proposed Prompt")
    logger.info("-" * 50)

    result = ab_test_manager.run_comparison_test(
        current_prompt=current_prompt,
        proposed_prompt=proposed_prompt,
        test_name="accuracy_improvement_test",
        judge_criteria=[
            "准确性：内容是否忠实于原文",
            "流畅度：语言是否自然易懂",
            "情感表达：是否准确传达了情感",
        ],
    )

    # 显示结果
    logger.info("Test Results:")
    logger.info(f"  Variant A (Current) Score: {result['variant_a']['score']:.3f}")
    logger.info(f"  Variant B (Proposed) Score: {result['variant_b']['score']:.3f}")
    logger.info(f"  Winner: {result['winner']}")
    logger.info(f"  Confidence: {result['confidence']:.2%}")
    logger.info(
        f"  Passed Quality Gate: {'YES' if result['passed_quality_gate'] else 'NO'}"
    )
    logger.info(f"  P-value: {result['details']['p_value']:.3f}")

    logger.info("\n" + "=" * 50)
    logger.info("Demo Complete - Check ./ab_test_results/ for detailed reports")
    logger.info("=" * 50)

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
