"""P0.3.4 — 创作宪法硬规则（Constitution）：给进化加防走火保险的"先于打分"判官。

对应执行手册 docs/EVOLUTION_ROADMAP.md P0.3 子任务 4，解决审计报告 §4.6 / §6.2
"LLM 自评自进化会悄悄退化"问题：LLM 可以给自己打高分，但**宪法硬规则先于打分**
裁决一次——"逐字朗读 / 可懂 / 不破音"三条不可妥协的硬关，违反即拒、不再进入
软打分（双裁判 / 效应量）环节。这是 reward-hacking 被堵在源头的第一道闸。

设计原则（红线 #1 主路径真实性）：
  - 宪法不调用 LLM 打分（否则 LLM 可绕过）；只用确定性规则 + P0.2 已落地的真实
    硬指标（DNSMOS / WER / 破音）做机械裁决。
  - 依赖缺失时宪法**降级为"无法裁决"**而非"假装通过"：`verdict.passed=False` 且
    `reason="unable_to_judge:<dep>"`，由上游决定是否阻止晋升——绝不把跳过当通过。

接点：
  - `ConstitutionAdjudicator.adjudge(candidate_output, reference_text=None,
        audio_metrics=None) -> ConstitutionVerdict` 是主入口，被 promotion_gate.py
    在双裁判**之前**调用。
  - `audio_metrics` 形如 P0.2 `_run_hard_metrics_async` 的返回 dict
    (mos/wer/voice_cosine/issues/status)，缺则只跑文本侧硬规则。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional

logger = logging.getLogger(__name__)


# ── 不可妥协硬规则（一经违反即拒，不进入软打分）─────────────────────────────────
class HardRule(str, Enum):
    """创作宪法硬规则枚举。值用于序列化与单测匹配。"""

    VERBATIM_READABLE = "verbatim_readable"  # 逐字朗读：参考文本被候选输出大体覆盖
    INTELLIGIBLE = "intelligible"  # 可懂：WER 不超阈值（P0.2 ASR 真值）
    NO_CLIPPING_DISTORTION = "no_clipping"  # 不破音：DNSMOS / 破音检测不越界


@dataclass(frozen=True)
class Constitution:
    """创作宪法（不可变阈值集合）。

    `frozen=True` + `MappingProxyType` 暴露，使"调参者"无法在运行期改阈值绕过硬关
    ——必须重新构造一个新的 Constitution 实例才能改阈值，调用点可见、可审计。
    """

    # WER 上界（超过即不"可懂"）。P0.2 真实 ASR 跑出的字错误率。
    wer_hard_cap: float = 0.35
    # DNSMOS 综合 MOS 下界（低于即"破音/失真"）。P0.2 真实 onnxruntime 跑出。
    mos_hard_floor: float = 3.0
    # 逐字朗读：候选输出对参考文本的字 n-gram 覆盖率下界。
    verbatim_coverage_floor: float = 0.80
    # 字符长度膨胀上限（2×）——防"把整段删了念个空的"这种退化。
    length_inflation_cap: float = 2.0

    def as_readonly(self) -> Mapping[str, Any]:
        """以只读视图暴露阈值，修改即 TypeError。"""
        return MappingProxyType(
            {
                "wer_hard_cap": self.wer_hard_cap,
                "mos_hard_floor": self.mos_hard_floor,
                "verbatim_coverage_floor": self.verbatim_coverage_floor,
                "length_inflation_cap": self.length_inflation_cap,
            }
        )


@dataclass(frozen=True)
class RuleViolation:
    """单条硬规则违反记录。"""

    rule: HardRule
    metric: Optional[float]
    threshold: Optional[float]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule": self.rule.value,
            "metric": self.metric,
            "threshold": self.threshold,
            "reason": self.reason,
        }


@dataclass
class ConstitutionVerdict:
    """宪法裁决结果。

    passed=True 表示候选**未违反**任何硬规则，可继续进入软打分（双裁判/效应量）。
    passed=False 表示候选被宪法硬拒，无论软打分多高都不得晋升（reward-hacking 防线）。
    unable_to_judge=True 表示依赖缺失——诚实降级，决不当通过，由上游 promotion_gate
    视为"不够格晋升"处理。
    """

    passed: bool
    unable_to_judge: bool = False
    violations: List[RuleViolation] = field(default_factory=list)
    adjudicator: str = "Constitution"
    checked_rules: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "unable_to_judge": self.unable_to_judge,
            "violations": [v.to_dict() for v in self.violations],
            "adjudicator": self.adjudicator,
            "checked_rules": list(self.checked_rules),
        }


# ── 字 n-gram 覆盖率（逐字朗读度量，确定性、免 LLM）──────────────────────────────
def _char_bigram_coverage(reference: str, candidate: str) -> float:
    """候选输出对参考文本的字 bigram 覆盖率 ∈ [0,1]。

    逐字朗读要求候选把参考文本的字几乎都念出来。这里度量：参考文本的字 bigram
    有多少出现在候选里。纯字符级、语言无关、免模型防作弊。
    """
    if not reference:
        # 无参考文本：该规则不适用，调用方应跳过 VERBATIM_READABLE
        return 1.0
    if not candidate:
        return 0.0
    ref_grams = _bigrams(reference)
    if not ref_grams:
        return 1.0
    cand_grams = _bigrams(candidate)
    cand_set = set(cand_grams)
    hit = sum(1 for g in ref_grams if g in cand_set)
    return hit / len(ref_grams)


def _bigrams(text: str) -> List[str]:
    """字 bigram（去空白）。"""
    s = "".join(text.split())
    if len(s) < 2:
        return [s] if s else []
    return [s[i : i + 2] for i in range(len(s) - 1)]


# ── 主体：宪法裁决官 ────────────────────────────────────────────────────────────
class ConstitutionAdjudicator:
    """宪法硬规则裁决官——先于打分闸门。

    用法（promotion_gate 内）：
        adjudicator = ConstitutionAdjudicator()   # Constiturtion 默认阈值
        v = adjudicator.adjudge(
            candidate_output="候选朗读文本…",
            reference_text="参考文本…",
            audio_metrics={"mos": 4.1, "wer": 0.18, "status": "all-ran"},
        )
        if not v.passed:
            # 宪法硬拒 —— 不进入双裁判软打分，reward-hacking 被堵在源头
            reject_promotion(reason=v)
    """

    def __init__(self, constitution: Optional[Constitution] = None):
        self.constitution = constitution or Constitution()

    def adjudge(
        self,
        candidate_output: str,
        reference_text: Optional[str] = None,
        audio_metrics: Optional[Mapping[str, Any]] = None,
    ) -> ConstitutionVerdict:
        """裁决候选是否违反任何硬规则。返回 ConstitutionVerdict。

        - candidate_output: 候选实际产出的文本（如 TTS 前的朗读稿 / ASR 回读文本）。
        - reference_text:   应逐字朗读的参考文本。无则跳过 VERBATIM_READABLE。
        - audio_metrics:    P0.2 真实硬指标 dict（mos/wer/voice_cosine/issues/status）。
                            缺则跳过依赖音频的硬规则（INTELLIGIBLE / NO_CLIPPING）。
        """
        audio_metrics = audio_metrics or {}
        violations: List[RuleViolation] = []
        checked: List[str] = []
        unable = False

        # ──硬规则1：逐字朗读（纯文本、必查）──────────────────────────────────
        if reference_text:
            cov = _char_bigram_coverage(reference_text, candidate_output)
            checked.append(HardRule.VERBATIM_READABLE.value)
            if cov < self.constitution.verbatim_coverage_floor:
                violations.append(
                    RuleViolation(
                        rule=HardRule.VERBATIM_READABLE,
                        metric=cov,
                        threshold=self.constitution.verbatim_coverage_floor,
                        reason=(
                            f"字 bigram 覆盖率 {cov:.2%} < {self.constitution.verbatim_coverage_floor:.0%}，"
                            f"未逐字朗读参考文本"
                        ),
                    )
                )
            # 长度膨胀：逐字朗读不应大幅增删——防"念空"或"念串"
            cap = self.constitution.length_inflation_cap
            ref_len = len("".join(reference_text.split()))
            cand_len = len("".join(candidate_output.split()))
            if ref_len > 0 and cand_len > ref_len * cap:
                violations.append(
                    RuleViolation(
                        rule=HardRule.VERBATIM_READABLE,
                        metric=cand_len / ref_len,
                        threshold=cap,
                        reason=f"候选长度膨胀 {cand_len / ref_len:.2f}× > {cap}× 参考长度",
                    )
                )

        # ──硬规则2：可懂（WER 真值，P0.2 ASR）────────────────────────────────
        wer = audio_metrics.get("wer")
        checked.append(HardRule.INTELLIGIBLE.value)
        if wer is None:
            # WER 未跑出（依赖缺失/无参考）——诚实降级，不当通过
            unable = True
            violations.append(
                RuleViolation(
                    rule=HardRule.INTELLIGIBLE,
                    metric=None,
                    threshold=self.constitution.wer_hard_cap,
                    reason="WER 未计算（ASR 依赖缺失或无参考音频），无法判定可懂——诚实降级，不得当通过",
                )
            )
        elif wer > self.constitution.wer_hard_cap:
            violations.append(
                RuleViolation(
                    rule=HardRule.INTELLIGIBLE,
                    metric=float(wer),
                    threshold=self.constitution.wer_hard_cap,
                    reason=f"WER {wer:.2%} > {self.constitution.wer_hard_cap:.0%} 硬上限，不满足可懂",
                )
            )

        # ──硬规则3：不破音（DNSMOS MOS 真值，P0.2 onnxruntime）─────────────────
        mos = audio_metrics.get("mos")
        checked.append(HardRule.NO_CLIPPING_DISTORTION.value)
        if mos is None:
            unable = True
            violations.append(
                RuleViolation(
                    rule=HardRule.NO_CLIPPING_DISTORTION,
                    metric=None,
                    threshold=self.constitution.mos_hard_floor,
                    reason="MOS 未计算（onnxruntime/DNSMOS 依赖缺失），无法判定破音——诚实降级，不得当通过",
                )
            )
        elif mos < self.constitution.mos_hard_floor:
            violations.append(
                RuleViolation(
                    rule=HardRule.NO_CLIPPING_DISTORTION,
                    metric=float(mos),
                    threshold=self.constitution.mos_hard_floor,
                    reason=f"MOS {mos:.2f} < {self.constitution.mos_hard_floor} 硬下限，破音/失真",
                )
            )

        # audio metrics 里若有 P0.2 记录的 issue（如 corrupt/clipping 启发式），也算破音
        for issue in audio_metrics.get("issues", []) or []:
            if any(k in str(issue) for k in ("clipping", "破音", "削顶", "distortion", "corrupt")):
                violations.append(
                    RuleViolation(
                        rule=HardRule.NO_CLIPPING_DISTORTION,
                        metric=None,
                        threshold=None,
                        reason=f"硬指标检出破音/损坏：{issue}",
                    )
                )
                break

        passed = len(violations) == 0 and not unable
        verdict = ConstitutionVerdict(
            passed=passed,
            unable_to_judge=unable,
            violations=violations,
            adjudicator="Constitution",
            checked_rules=checked,
        )
        if not passed:
            logger.warning(
                "Constitution REJECTED candidate: %s",
                "; ".join(v.reason for v in violations),
            )
        return verdict


# ── 模块级单例（约定默认宪法，便于在 promotion_gate 一行接入）─────────────────────
_default_adjudicator: Optional[ConstitutionAdjudicator] = None


def get_constitution_adjudicator() -> ConstitutionAdjudicator:
    """获取默认宪法裁决官单例（默认 Constitution 阈值）。"""
    global _default_adjudicator
    if _default_adjudicator is None:
        _default_adjudicator = ConstitutionAdjudicator()
    return _default_adjudicator


def reset_constitution_adjudicator() -> None:
    """重置单例（测试用：重设阈值后需重建单例）。"""
    global _default_adjudicator
    _default_adjudicator = None
