"""Loudness target presets — 全仓库响度目标的单一事实源.

背景 (2026-10-09 同稿原声对照):《Football Forever》Dominoes L1 原版有声书
实测综合响度 -22.7 LUFS / 真峰值 -3.8 dBTP,与 EBU R128 广播级有声书标准
(-23 LUFS) 一致。彼时仓库三处后处理各自为政:

  - export/mastering.py   I=-16 (流媒体档)
  - export/audio_ducking  混音输出 I=-16
  - pipeline/audio_finalize 默认 I=-20

本模块提供命名响度档,供三处共享;有声书分发默认走 ``audiobook`` 档。
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

# 命名响度档:i=综合响度 LUFS,lra=响度范围 LU,tp=真峰值 dBTP
LOUDNESS_PRESETS: Dict[str, Dict[str, float]] = {
    # EBU R128 广播/有声书标准;原声实测 -22.7 LUFS / TP -3.8 (见模块 docstring)
    "audiobook": {"i": -23.0, "lra": 7.0, "tp": -3.0},
    # 播客常见档
    "podcast": {"i": -19.0, "lra": 9.0, "tp": -2.0},
    # 流媒体平台基准 (Spotify/YouTube ≈ -14~-16 LUFS,响度战上限)
    "streaming": {"i": -16.0, "lra": 11.0, "tp": -1.5},
}

LOUDNESS_PRESET_NAMES: Tuple[str, ...] = tuple(sorted(LOUDNESS_PRESETS))


def resolve_loudness(
    preset: Optional[str] = None,
    *,
    i: Optional[float] = None,
    lra: Optional[float] = None,
    tp: Optional[float] = None,
    default_preset: str = "audiobook",
) -> Tuple[float, float, float]:
    """解析响度目标为 ``(i, lra, tp)``。

    Args:
        preset: 命名档;``None`` 时用 *default_preset* 兜底。
        i/lra/tp: 显式覆写对应单项,优先级高于档值。
        default_preset: preset 与显式值均未给时的兜底档。

    Raises:
        ValueError: preset 名不在 ``LOUDNESS_PRESETS``。
    """
    name = preset or default_preset
    if name not in LOUDNESS_PRESETS:
        raise ValueError(f"unknown loudness preset {name!r}; known: {LOUDNESS_PRESET_NAMES}")
    base = LOUDNESS_PRESETS[name]
    return (
        i if i is not None else base["i"],
        lra if lra is not None else base["lra"],
        tp if tp is not None else base["tp"],
    )


import functools
import logging
import subprocess

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def ffmpeg_has_soxr() -> bool:
    """探测当前环境 ffmpeg 是否可用 soxr 重采样器。

    实测法: 跑 0.1s 静音源经 ``aresample=resampler=soxr``, 编译链接了
    libsoxr 的构建返回 0, 否则 rc!=0 (Invalid argument)。

    不能只解析 ``ffmpeg -filters`` / ``-h filter=aresample`` 的文本:
    选项枚举编译进 ffmpeg 源码, 未链接 libsoxr 的构建 (如本机 Homebrew
    ffmpeg) 也会在帮助里列出 soxr, 但运行时必失败 → 文本法误报 True。
    实测法两端都对: 本机 Homebrew ffmpeg=False, CI docker ffmpeg(带
    --enable-libsoxr)=True。结果 lru_cache 缓存, 仅探测一次。

    探针走 ``subprocess.check_output`` 而非 ``run``: 与业务 ffmpeg 调用
    (subprocess.run) 解耦 — 既有单测 patch ``subprocess.run`` 断言调用
    次数 / side_effect 序列, 探针混入会破契约 (多计一次 / 吃掉
    TimeoutExpired / 被 fake_run 误判 rc=0 → soxr 误报)。

    Returns:
        bool: True 表示可用 soxr, False 回退默认 swr。
    """
    try:
        # 直接用 Popen 绕过 subprocess.run / check_output:
        # 既有单测 patch subprocess.run 断言调用次数 / side_effect,
        # check_output 内部仍调用 run → 会被拦截; Popen 完全独立。
        proc = subprocess.Popen(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=48000:cl=mono",
                "-t",
                "0.1",
                "-af",
                "aresample=44100:resampler=soxr",
                "-f",
                "null",
                "-",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            rc = proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            logger.debug("ffmpeg soxr detection timed out")
            return False
        if rc == 0:
            logger.info("ffmpeg soxr resampler detected (runtime probe)")
            return True
        logger.info(
            "ffmpeg soxr not available (rc=%s), falling back to default swr resampler",
            rc,
        )
        return False
    except (subprocess.SubprocessError, OSError) as e:
        logger.debug("ffmpeg soxr detection failed: %s", e)
        return False


def aresample_filter(sample_rate: int = 44100) -> str:
    """返回带 soxr 探测的 aresample 滤镜字符串。

    若 ffmpeg 可用 soxr (运行时实测探测), 返回 ``aresample={sr}:resampler=soxr``;
    否则返回 ``aresample={sr}`` (默认 swr)。探测结果 lru_cache 缓存,
    探测时仅 log 一行 info (一次性), 后续调用零开销。

    Args:
        sample_rate: 目标采样率,默认 44100 (CD 质量/有声书标准)。

    Returns:
        str: ffmpeg 滤镜片段,可直接接在 filter_chain 中。
    """
    if ffmpeg_has_soxr():
        return f"aresample={sample_rate}:resampler=soxr"
    return f"aresample={sample_rate}"
