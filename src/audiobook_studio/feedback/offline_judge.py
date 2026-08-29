"""M5 — 离线兜底评判器：零网络、零成本的确定性质检/评分。

当硬件档为 ``offline``（或无网/配额耗尽）时，self-iteration 闭环仍须可运行。本模块提供：

* :class:`OfflineVerdict` —— 基于规则（clipping / 静音 / 幅度）的确定性质检裁决，
  不依赖任何 LLM 或云端硬指标（DNSMOS/ASR/SpeakerSim）。
* :class:`OfflineJudge` —— 与 M2 评判器同接口的 ``score(input, output, expected, stage)``，
  复用 ``candidate_eval.score_output_vs_expected`` 做候选输出 vs 期望的结构比对。

它是 LLM-Judge / 在线 ensemble 的兜底：在线不可用时自动降级，保证闭环「只进不退」不中断。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .candidate_eval import score_output_vs_expected

logger = logging.getLogger(__name__)


@dataclass
class OfflineVerdict:
    """离线确定性质检裁决。"""

    passed: bool
    issues: List[str] = field(default_factory=list)
    overall_score: float = 1.0
    needs_regeneration: bool = False
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "issues": list(self.issues),
            "overall_score": self.overall_score,
            "needs_regeneration": self.needs_regeneration,
            "rationale": self.rationale,
        }


class OfflineJudge:
    """离线确定性评判器（不触网）。"""

    # 静音阈值（毫秒）：累计静音超过该值视为问题片段
    SILENCE_MS_THRESHOLD = 500.0
    PEAK_DB_TOO_LOUD = -1.0
    RMS_DB_TOO_QUIET = -45.0

    def judge_quality(
        self,
        *,
        duration_ms: int = 0,
        rms_db: float = -20.0,
        peak_db: float = -6.0,
        has_clipping: bool = False,
        silence_regions: Optional[List[Tuple[float, float]]] = None,
        reference_text: str = "",
    ) -> OfflineVerdict:
        """基于音频特征做确定性质检裁决（无 LLM / 无云端硬指标）。"""
        issues: List[str] = []
        if has_clipping:
            issues.append("clipping")
        silence = silence_regions or []
        total_silence = sum(max(0.0, float(e) - float(s)) for s, e in silence)
        if total_silence > self.SILENCE_MS_THRESHOLD:
            issues.append("silent_segment")
        if peak_db > self.PEAK_DB_TOO_LOUD:
            issues.append("too_loud")
        if rms_db < self.RMS_DB_TOO_QUIET:
            issues.append("too_quiet")
        passed = len(issues) == 0
        overall = 1.0 if passed else max(0.0, 1.0 - 0.2 * len(issues))
        rationale = "offline rule-based: PASS" if passed else f"offline rule-based FAIL: {', '.join(issues)}"
        return OfflineVerdict(
            passed=passed,
            issues=issues,
            overall_score=overall,
            needs_regeneration=(not passed),
            rationale=rationale,
        )

    def score(self, input_data: Any, output: Any, expected: Any, stage: str) -> float:
        """与 M2 评判器同接口：候选输出 vs 期望的确定性相似度（0-1）。"""
        return score_output_vs_expected(expected, output)


def build_judge(online: Optional[Any] = None) -> Any:
    """返回离线兜底评判器；若提供可用的在线 judge 则优先使用，否则离线兜底。

    方便 self-iteration 闭环在「有网用在线、无网用离线」间无缝切换。
    """
    if online is not None:
        return online
    return OfflineJudge()
