"""人声/伴奏分离 (立体声 mid/side STFT 软掩蔽) — ASR 前置预处理.

升级点 #1 (原声对照任务 2026-10-12): 带全程音乐床的有声书参考音频,
SenseVoiceSmall 直接转写词召回仅 68.5% (637/930); 经本掩蔽后 72.8%
(677/930), WER 31.9%→27.5% (实验记录 scratch/ff_system/exp_vocalsep_result.json)。
原理: 人声通常居中 (mid=(L+R)/2), 宽立体声伴奏在 side=(L-R)/2 有能量 —
用 side 谱减法软掩蔽 mid 频谱可压低音乐床。床本身很居中时收益有限
(原声实测 interlude side/mid 仅 0.15), 剩余召回缺口需 demucs 级强分离。

纯 numpy/scipy (无 torch); 单声道输入诚实原样返回 (无 side 信息可减)。
典型用法: 带床评测音频先 ``isolate_vocals_file()`` 再喂 ASR/WER。
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# 掩蔽窗参数: 16kHz 下 64ms 窗 / 32ms hop (nperseg=1024, noverlap=512)
_NPERSEG = 1024
_NOVERLAP = 512
_HPF_HZ = 80.0  # 掩蔽后高通, 去低频伴奏残留


def isolate_vocals(stereo: np.ndarray, sr: int, beta: float = 1.5,
                   time_smooth: int = 5) -> np.ndarray:
    """从立体声信号中掩蔽提取居中人声.

    Args:
        stereo: (N, 2) float 波形; 单声道 (N,) 或 (N, 1) 原样返回 (mono 下混).
        sr: 采样率.
        beta: side 谱减强度 (1.0=中性, 越大压得越狠; 实验校准 1.5).
        time_smooth: 掩蔽时间平滑窗 (帧), 抑制 musical noise.

    Returns:
        (N,) mono 人声估计 (峰值归一到 0.95)。
    """
    x = np.asarray(stereo, dtype=np.float64)
    if x.ndim == 1:
        return _peak_normalize(x)
    if x.shape[1] < 2:
        return _peak_normalize(x[:, 0])
    if x.shape[1] > 2:
        x = x[:, :2]

    mid = (x[:, 0] + x[:, 1]) / 2.0
    side = (x[:, 0] - x[:, 1]) / 2.0

    from scipy.signal import stft, istft, butter, sosfilt
    from scipy.ndimage import uniform_filter1d

    _, _, Zm = stft(mid, fs=sr, nperseg=_NPERSEG, noverlap=_NOVERLAP)
    _, _, Zs = stft(side, fs=sr, nperseg=_NPERSEG, noverlap=_NOVERLAP)
    Pm, Ps = np.abs(Zm) ** 2, np.abs(Zs) ** 2
    mask = np.clip((Pm - beta * Ps) / (Pm + Ps + 1e-10), 0.0, 1.0)
    if time_smooth and time_smooth > 1:
        mask = uniform_filter1d(mask.astype(np.float32), size=time_smooth, axis=1)
    _, voc = istft(Zm * mask, fs=sr, nperseg=_NPERSEG, noverlap=_NOVERLAP)
    voc = sosfilt(butter(2, _HPF_HZ, "hp", fs=sr, output="sos"), voc[: len(mid)])
    return _peak_normalize(voc)


def _peak_normalize(y: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    if peak < 1e-6:
        return y.astype(np.float32)
    return (y * (0.95 / peak)).astype(np.float32)


def isolate_vocals_file(src: str | Path, dst: str | Path, beta: float = 1.5,
                        sample_rate: int = 16000) -> Optional[Path]:
    """文件级人声分离 (任意音视频 → 16k mono 人声 wav).

    ffmpeg 解码保留双声道 (mid/side 需立体声), 掩蔽后写 ``dst``。
    单声道源诚实降级: 直接重采样下混写 ``dst`` (分离无从谈起, 但 ASR 可用)。
    Returns: 成功写出的 Path; 失败 None。
    """
    src_p, dst_p = Path(src), Path(dst)
    if not src_p.exists():
        logger.warning(f"[VocalIsolation] 源不存在: {src_p}")
        return None
    dst_p.parent.mkdir(parents=True, exist_ok=True)
    tmp_stereo = Path(tempfile.mkstemp(suffix=".wav")[1])
    try:
        # 保留声道信息解码到目标采样率 (不强混 mono — side 能量在此才有意义)
        r = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(src_p),
             "-ar", str(sample_rate), "-c:a", "pcm_s16le", str(tmp_stereo)],
            capture_output=True, text=True, timeout=300,
        )
        if r.returncode != 0:
            logger.warning(f"[VocalIsolation] ffmpeg 解码失败: {r.stderr[:200]}")
            return None
        import soundfile as sf

        audio, sr = sf.read(str(tmp_stereo), dtype="float32", always_2d=True)
        if audio.shape[1] == 1:
            logger.info("[VocalIsolation] 单声道源, 原样下混 (无 side 信息可减)")
            y = _peak_normalize(audio[:, 0].astype(np.float64))
        else:
            y = isolate_vocals(audio, sr, beta=beta)
        sf.write(str(dst_p), y, sr)
        logger.info(f"[VocalIsolation] {src_p.name} -> {dst_p.name} "
                    f"({len(y)/sr:.1f}s, beta={beta})")
        return dst_p
    except Exception as e:  # noqa: BLE001 — 预处理失败不阻断调用方
        logger.warning(f"[VocalIsolation] 分离失败 ({type(e).__name__}: {e})")
        return None
    finally:
        tmp_stereo.unlink(missing_ok=True)


__all__ = ["isolate_vocals", "isolate_vocals_file"]
