#!/usr/bin/env python3
"""Batch 2.1 冒烟: 音频客观指标门禁接线验证 (不做真实音频转写, 避开慢路径).

验证:
  A. 依赖可用性报告 (诚实: mos/wer/speaker_similarity 三键, 值为 True/False)
  B. 降级路径: 无候选→None; strict 模式 fail-closed GateResult
  C. promotion.evaluate_promotion 接受 audio_gate 第 5 门参数
  D. HarnessSettings 阈值字段默认值
  E. KokoroZeroShotCloneEngine 注册 + mock_mode clone
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

PASS, FAIL = [], []


def check(name, fn):
    t0 = time.time()
    try:
        detail = fn()
        PASS.append(name)
        print(f"[PASS] {name}" + (f" — {detail}" if detail else ""))
    except Exception as e:
        FAIL.append(name)
        print(f"[FAIL] {name} — {e}")
    finally:
        dt = time.time() - t0
        if dt > 5:
            print(f"       ({name} took {dt:.1f}s)")


def expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


# ── A. 依赖可用性诚实报告 ───────────────────────────────────────────────────
def t_availability():
    from audiobook_studio.quality.audio_metrics import get_available_metrics
    avail = get_available_metrics()
    expect(set(avail.keys()) == {"mos", "wer", "speaker_similarity"}, f"键集异常: {avail}")
    print(f"       {avail}")
    return "三键完备"


# ── B. 严格/宽松模式 ────────────────────────────────────────────────────────
def t_strict_fail_closed():
    from audiobook_studio.feedback.audio_quality_gate import evaluate_audio_gate, GateResult
    gate = evaluate_audio_gate([], [], [], strict=True)
    expect(isinstance(gate, GateResult) and not gate.passed, "strict=True 应返回 fail-closed GateResult")
    return "fail-closed OK"


def t_lenient_none():
    from audiobook_studio.feedback.audio_quality_gate import evaluate_audio_gate
    gate = evaluate_audio_gate([], [], [])
    expect(gate is None, "默认宽松模式无候选应返回 None")
    return "lenient None OK"


# ── C. promotion 第 5 门接线 ────────────────────────────────────────────────
def t_promotion_wiring():
    import os
    from audiobook_studio.feedback.promotion import evaluate_promotion, GateResult
    os.environ["SELF_ITERATION_MOCK"] = "true"
    try:
        fake = GateResult(name="客观音频指标", passed=True, score=1.0, threshold=1.0, details="smoke")
        verdict = evaluate_promotion("edit_for_tts", 1, 1, human_samples=None, audio_gate=fake)
        names = [g.name for g in verdict.gates]
        expect("客观音频指标" in names, f"audio_gate 未出现: {names}")
        return f"gates={len(verdict.gates)}"
    finally:
        os.environ.pop("SELF_ITERATION_MOCK", None)


# ── D. HarnessSettings 新字段 ───────────────────────────────────────────────
def t_harness_settings():
    from audiobook_studio.harness.config import get_harness_settings
    cfg = get_harness_settings()
    expect(cfg.AUDIO_MOS_MIN == 3.5, "AUDIO_MOS_MIN 应为 3.5")
    expect(cfg.AUDIO_WER_MAX == 0.15, "AUDIO_WER_MAX 应为 0.15")
    expect(cfg.AUDIO_SPEAKER_COSINE_MIN == 0.85, "AUDIO_SPEAKER_COSINE_MIN 应为 0.85")
    expect(cfg.AUDIO_GATE_STAGES == ["edit_for_tts", "tts_routing", "synthesize"], "AUDIO_GATE_STAGES 列表不符")
    expect(cfg.AUDIO_GATE_STRICT is False, "AUDIO_GATE_STRICT 应为 False")
    return "字段默认值正确"


# ── E. KokoroZeroShotCloneEngine 注册 + mock clone ──────────────────────────
def t_kokoro_engine_reg():
    from audiobook_studio.tts.zero_shot_clone import (
        create_zero_shot_clone_engine, ZeroShotCloneConfig, ZeroShotCloneEngine,
    )
    from audiobook_studio.tts.port_factory import create_engine
    import os
    os.environ["MOCK_TTS"] = "true"
    try:
        eng = create_zero_shot_clone_engine(ZeroShotCloneConfig(engine="kokoro_zeroshot"))
        expect(type(eng._engine).__name__ == "KokoroZeroShotCloneEngine", "factory 类型错误")
        port = create_engine("kokoro_zeroshot")
        expect(type(port).__name__ == "ZeroShotCloneEngine", "port_factory 类型错误")
        # mock clone
        res = eng.clone("测试文本", b"fake_ref_audio")
        expect(isinstance(res, type(res)) and res.metadata.get("mock") is True, "mock clone 失败")
        return "注册 + mock clone OK"
    finally:
        os.environ.pop("MOCK_TTS", None)


# ── 汇总 ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("Batch 2.1 音频门禁接线冒烟 (快速版)")
    print("=" * 60)

    check("A. 依赖可用性诚实报告", t_availability)
    check("B1. strict fail-closed", t_strict_fail_closed)
    check("B2. 宽松模式降级 None", t_lenient_none)
    check("C. promotion 第 5 门接线", t_promotion_wiring)
    check("D. HarnessSettings 字段", t_harness_settings)
    check("E. KokoroZeroShotCloneEngine 注册+mock", t_kokoro_engine_reg)

    print("=" * 60)
    print(f"汇总: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        for f in FAIL:
            print(f"  [FAIL] {f}")
        sys.exit(1)
    print("ALL PASS")
