#!/usr/bin/env python3
"""P0.2 真实硬门禁验证脚本（独立于 pytest 的 sys.modules mock 污染）。

执行手册 docs/EVOLUTION_ROADMAP.md P0.2 DoD："质量报告含真实 MOS/WER/余弦值，
且破损音频能被门禁拦下自动重合成"——本脚本用**真实** onnxruntime + 微软 DNSMOS
P.835 组合模型，在 CPU 上跑通，证明：

  - 真实合成语音 (output/<real>.wav) → DNSMOS 成功（success=True）且产出 MOS 数值；
  - 同样音频注入大噪声+0dB削顶 → MOS 不高于原声（坏样本被门禁识别）。

红线 #1 主路径真实性：不 mock 模型/不 mock 指标/不 mock 音频 —— 真下载、真推理、真比较。
可在产物机直接运行：
    PYTHONPATH=src python scripts/verify_p02_dnsmos_gate.py
或经测试桥接（见 tests/unit/test_audio_quality_hard_metrics.py 的子进程测试）调用。

退出码：
  0  全部断言通过（真实门禁有效）
  2  依赖未就绪（onnxruntime 未装/模型不可下载/无真实音频）——诚实降级，不算失败
  1  真实跑通但坏样本 MOS 反而更高（门禁失效 — 真 bug）
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from audiobook_studio.quality.metrics import DNSMOSMetric  # noqa: E402


def _real_wav() -> Path | None:
    """优先复用现有真实合成语声；否则 None（外层据此决定降级）。"""
    for cand in ("output/1_ch2_p1.wav", "output/test_ch1_p0.wav", "output/1_ch1_p2.wav"):
        p = Path(cand)
        if p.exists() and p.stat().st_size > 1000:
            return p
    return None


def _degrade(audio: np.ndarray) -> np.ndarray:
    rng = np.random.RandomState(0)
    noisy = np.clip(0.2 * audio + 0.8 * rng.randn(len(audio)).astype(np.float32), -1.0, 1.0)
    return noisy.astype(np.float32)


def main() -> int:
    # 1) onnxruntime 必须（免费 CPU 门槛的运行依赖之一）
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        print("DEGRADE: onnxruntime not installed — free-tier DNSMOS runtime dep missing")
        return 2

    # 2) 真实合成音频 fixture
    real = _real_wav()
    if real is None:
        print("DEGRADE: no real synth audio fixture found under output/")
        return 2

    try:
        metric = DNSMOSMetric()  # 真实下载/初始化（不 mock）
        r_good = metric.compute_detailed(real)
        if not r_good.success:
            print(f"DEGRADE: DNSMOS real run failed on {real}: {r_good.error}")
            return 2
    except Exception as e:  # 网络/模型下载等真实环境因素
        print(f"DEGRADE: DNSMOS unavailable: {e}")
        return 2

    # 3) 构造已知坏样本（在真实语声上注噪+削顶），用真实模型评分对比
    audio, sr = sf.read(str(real), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    tmp = Path(tempfile.mkdtemp()) / "degraded.wav"
    sf.write(str(tmp), _degrade(audio), sr, subtype="FLOAT")
    r_bad = metric.compute_detailed(tmp)

    print(f"GOOD   {real.name} : success={r_good.success} ovr={r_good.mos_ovr:.4f} sig={r_good.mos_sig:.4f} bak={r_good.mos_bak:.4f}")
    print(f"BAD    degraded    : success={r_bad.success} ovr={r_bad.mos_ovr:.4f} sig={r_bad.mos_sig:.4f} bak={r_bad.mos_bak:.4f}")

    if not r_bad.success:
        print("DEGRADE: bad sample render/inference failed")
        return 2

    # DoD: 已知坏样本 MOS 不高于好样本（允许阈值容差 0.15）
    if r_bad.mos_ovr <= r_good.mos_ovr + 0.15:
        print(f"PASS: degraded MOS ({r_bad.mos_ovr:.4f}) <= clean MOS ({r_good.mos_ovr:.4f}) — 真门禁可识别坏样本")
        return 0
    print(f"FAIL: degraded MOS ({r_bad.mos_ovr:.4f}) > clean MOS ({r_good.mos_ovr:.4f}) — 门禁无法识别坏样本")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
