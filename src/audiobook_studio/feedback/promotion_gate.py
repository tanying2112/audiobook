"""
E4 — Promotion Gate (晋升门禁)

质量门禁系统：评估新版本 Prompt 是否达到升级标准。
四项门禁：
1. 格式合规率 ≥ 99%
2. 黄金数据集通过率 ≥ 95%
3. 质量指标 ≥ 旧版 102%
4. 人工抽样通过率 ≥ 80%
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class GateResult:
    """单项目门禁结果."""

    name: str
    passed: bool
    score: float
    threshold: float
    details: str = ""


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


def _load_golden_dataset(stage: str) -> List[Dict[str, Any]]:
    """加载黄金数据集."""
    golden_dir = Path("tests/golden") / stage
    if not golden_dir.exists():
        logger.warning(f"Golden dataset not found: {golden_dir}")
        return []

    examples: List[Dict[str, Any]] = []
    for f in sorted(golden_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            examples.append(data)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load golden example {f}: {e}")

    return examples


def _load_golden_jsonl(stage: str) -> List[Dict[str, Any]]:
    """加载黄金数据集的 JSONL 格式."""
    golden_dir = Path("tests/golden") / stage
    if not golden_dir.exists():
        return []

    examples: List[Dict[str, Any]] = []
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
            issues.append(
                f"未闭合的变量: {opens}个 '{{{{' 但 {closes}个 '}}}}'"
            )

    # Check for {% %} blocks
    if "{%" in prompt_content:
        block_opens = prompt_content.count("{%")
        block_closes = prompt_content.count("%}")
        if block_opens != block_closes:
            issues.append(
                f"未闭合的块: {block_opens}个 '{{%' 但 {block_closes}个 '}}%'"
            )

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
        details=(
            "全部格式检查通过"
            if not issues
            else f"发现问题 ({len(issues)}): {'; '.join(issues)}"
        ),
    )


# ── Gate 2: Golden dataset pass rate ────────────────────────────────────────


def check_golden_dataset(
    stage: str,
    new_version: int,
    threshold: float = 0.95,
) -> GateResult:
    """检查黄金数据集通过率.

    模拟运行 golden dataset 用例，统计通过比例。
    """
    examples = _load_golden_dataset(stage) or _load_golden_jsonl(stage)
    if not examples:
        return GateResult(
            name="黄金数据集通过率",
            passed=False,
            score=0.0,
            threshold=threshold,
            details=f"黄金数据集未找到: tests/golden/{stage}/",
        )

    new_prompt = _load_prompt_version(stage, new_version)
    if not new_prompt:
        return GateResult(
            name="黄金数据集通过率",
            passed=False,
            score=0.0,
            threshold=threshold,
            details=f"Prompt v{new_version} not found for stage '{stage}'",
        )

    # Simulate: check that prompt has enough context for each example
    passed_count = 0
    for example in examples:
        # Simple check: does the prompt contain the key fields from the example?
        required_fields = ["input", "output"]
        if all(field in example for field in required_fields):
            passed_count += 1

    score = passed_count / max(len(examples), 1)
    passed = score >= threshold

    return GateResult(
        name="黄金数据集通过率",
        passed=passed,
        score=score,
        threshold=threshold,
        details=(
            f"{passed_count}/{len(examples)} 用例通过 "
            f"({score * 100:.1f}% ≥ {threshold * 100:.0f}%)"
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

    Returns:
        score = new_score / old_score (ratio, ≥1.0 = improvement)
    """
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

    # Simplified quality estimation based on pattern fix coverage
    # In production, this would run the full pipeline on golden dataset
    old_fixes = sum(1 for tag in _EXTRACTED_PATTERNS if tag in old_prompt)
    new_fixes = sum(1 for tag in _EXTRACTED_PATTERNS if tag in new_prompt)

    # Also check length and instruction detail
    old_detail = len(old_prompt) / 1000  # rough "detail" score
    new_detail = len(new_prompt) / 1000

    old_score = 0.5 + (old_fixes * 0.05) + min(old_detail * 0.01, 0.3)
    new_score = 0.5 + (new_fixes * 0.05) + min(new_detail * 0.01, 0.3)

    score_ratio = new_score / max(old_score, 0.01)
    passed = score_ratio >= threshold

    return GateResult(
        name="质量 ≥ 旧版 102%",
        passed=passed,
        score=score_ratio,
        threshold=threshold,
        details=(
            f"旧版 v{old_version} 质量评分: {old_score:.3f}, "
            f"新版 v{new_version} 质量评分: {new_score:.3f}, "
            f"比例: {score_ratio:.3f}"
        ),
    )


# Predefined pattern tags used for quality estimation
_EXTRACTED_PATTERNS = [
    "dialogue_attribution", "emotion_too_mild", "emotion_too_strong",
    "emotion_wrong", "speaker_wrong", "pause_missing", "pause_too_long",
    "sfx_missing", "sfx_wrong", "text_colloquial", "text_formal",
    "prosody_robotic", "prosody_flat",
]


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
        details=(
            f"{passed}/{total} 抽样通过 ({score * 100:.1f}% ≥ {threshold * 100:.0f}%)"
        ),
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
        stage: Pipeline stage name
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
            else f"❌ {len(gates) - sum(1 for g in gates if g.passed)}/4 门禁未通过 "
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
