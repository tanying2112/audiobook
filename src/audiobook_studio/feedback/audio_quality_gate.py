"""
Batch 2.1 — 客观音频指标门禁（thin wrapper）。

包装 quality.audio_metrics.check_audio_quality，产出 GateResult 接入
promotion.evaluate_promotion 作为第 5 门（音频产出 stage 适用）。

设计原则：
- 依赖缺失/无样本 → 诚实降级（默认跳过，strict 模式 fail-closed）
- 阈值从 HarnessSettings 读（env 可覆盖）
- mock 模式下不产生垃圾指标，直接返回 None（调用方决定 skip）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from ..feedback.promotion import GateResult

logger = logging.getLogger(__name__)


# WER 回退容差：候选比基线最多差 2 个百分点（基线 WER=0 时避免 ×1.02 退化为 ≤0）
WER_REGRESSION_TOLERANCE = 0.02


@dataclass
class AudioGateThresholds:
    """音频门禁阈值（对齐 AudioQualityReport 默认）。"""
    mos_min: float = 3.5
    wer_max: float = 0.15
    speaker_cosine_min: float = 0.85


def evaluate_audio_gate(
    candidate_wavs: List[str],
    baseline_wavs: List[str],
    reference_texts: List[str],
    language: str = "zh",
    thresholds: Optional[AudioGateThresholds] = None,
    strict: bool = False,
) -> Optional[GateResult]:
    """
    评估候选音频相对基线的客观质量门禁。

    Args:
        candidate_wavs: 候选版本音频文件路径列表（必填）
        baseline_wavs: 基线版本音频文件路径列表（可选，同长度；缺省时仅测绝对阈值）
        reference_texts: 对应的参考文本列表（必填）
        language: 语言代码（zh/en/ja/ko 等），用于 WER 字符级 Levenshtein
        thresholds: 自定义阈值（None 则使用 AudioGateThresholds 默认）
        strict: True=依赖缺失/无样本时 fail-closed；False=诚实降级跳过

    Returns:
        GateResult 或 None（无样本/依赖缺失且非 strict 时）
    """
    if not candidate_wavs:
        logger.info("Audio gate: 无候选音频，跳过")
        if strict:
            return GateResult(
                name="客观音频指标",
                passed=False,
                score=0.0,
                threshold=1.0,
                details="严格模式：无候选音频样本",
            )
        return None

    # 依赖可用性探测
    try:
        from ..quality.audio_metrics import check_audio_quality, get_available_metrics
    except ImportError as e:
        logger.warning(f"Audio gate: quality.audio_metrics 导入失败: {e}")
        if strict:
            return GateResult(
                name="客观音频指标",
                passed=False,
                score=0.0,
                threshold=1.0,
                details=f"严格模式：依赖缺失 ({e})",
            )
        return None

    avail = get_available_metrics()
    missing = [k for k, v in avail.items() if not v]
    if missing:
        msg = f"音频指标依赖缺失: {missing}，诚实降级"
        logger.info(f"Audio gate: {msg}")
        if strict:
            return GateResult(
                name="客观音频指标",
                passed=False,
                score=0.0,
                threshold=1.0,
                details=f"严格模式: {msg}",
            )
        return None

    th = thresholds or AudioGateThresholds()
    n = min(len(candidate_wavs), len(reference_texts))
    # baseline 可少：对齐到 n，不足则补 None
    if len(baseline_wavs) < n:
        baseline_wavs = list(baseline_wavs) + [None] * (n - len(baseline_wavs))

    passed_all = True
    details_parts = []

    for i in range(n):
        c_wav = candidate_wavs[i]
        ref = reference_texts[i]
        b_wav = baseline_wavs[i]

        try:
            report = check_audio_quality(
                c_wav, ref, b_wav, language,
                mos_threshold=th.mos_min,
                wer_threshold=th.wer_max,
                speaker_cosine_threshold=th.speaker_cosine_min,
            )
            # 绝对阈值已在 report.overall_passed 中计算
            sample_passed = report.overall_passed
            # 若有基线，额外检查不回退（MOS/SpeakerCosine 不低于基线 98%、WER 不高于基线 102%）
            if b_wav:
                base_report = check_audio_quality(
                    b_wav, ref, c_wav, language,
                    mos_threshold=th.mos_min,
                    wer_threshold=th.wer_max,
                    speaker_cosine_threshold=th.speaker_cosine_min,
                )
                # 对比：候选不得显著弱于基线
                mos_ok = (report.mos is None or base_report.mos is None or
                          report.mos >= base_report.mos * 0.98)
                wer_ok = (report.wer is None or base_report.wer is None or
                          report.wer <= base_report.wer + WER_REGRESSION_TOLERANCE)
                spk_ok = (report.speaker_cosine is None or base_report.speaker_cosine is None or
                          report.speaker_cosine >= base_report.speaker_cosine * 0.98)
                sample_passed = sample_passed and mos_ok and wer_ok and spk_ok

            passed_all = passed_all and sample_passed

            m = f"{report.mos:.2f}" if report.mos is not None else "N/A"
            w = f"{report.wer:.3f}" if report.wer is not None else "N/A"
            s = f"{report.speaker_cosine:.3f}" if report.speaker_cosine is not None else "N/A"
            details_parts.append(f"#{i} mos={m}/{th.mos_min} wer={w}/{th.wer_max} spk={s}/{th.speaker_cosine_min} {'✅' if sample_passed else '❌'}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Audio gate 样本 {i} 评测异常: {e}")
            passed_all = False
            details_parts.append(f"#{i} error: {e}")

    score = 1.0 if passed_all else 0.0
    details = "; ".join(details_parts)

    return GateResult(
        name="客观音频指标",
        passed=passed_all,
        score=score,
        threshold=1.0,
        details=details,
    )


def evaluate_audio_gate_single(
    candidate_wav: str,
    reference_text: str,
    baseline_wav: Optional[str] = None,
    language: str = "zh",
    thresholds: Optional[AudioGateThresholds] = None,
    strict: bool = False,
) -> Optional[GateResult]:
    """单样本便捷封装。"""
    return evaluate_audio_gate(
        candidate_wavs=[candidate_wav],
        baseline_wavs=[baseline_wav] if baseline_wav else [],
        reference_texts=[reference_text],
        language=language,
        thresholds=thresholds,
        strict=strict,
    )
