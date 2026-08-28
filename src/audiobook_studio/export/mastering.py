"""
S2-5 — 母带后处理链路 (Mastering post-processing chain)

为导出的有声书音频 (M4B / MP3) 提供广播级母带后处理：

  1. 降噪 (noise reduction)
     ffmpeg 没有名为 ``noisereduce`` 的滤镜；这里使用其原生等效滤镜
     ``afftdn`` (FFT 域宽带降噪) 实现同样的底噪抑制目标 (噪声底噪降低 ≥ 10dB)。

  2. 静音段修剪 (silence removal)
     使用 ``silenceremove`` 自动去除首尾/中段静音段。

  3. 响度归一化 (loudness normalization)
     EBU R128 ``loudnorm``，目标 I=-16 LUFS / TP=-1.5 dBTP / LRA=11 LU
     (与任务验收一致)。默认采用两遍 (two-pass) 以获得精确目标响度。

验收：
  - 导出 M4B/MP3 通过 loudnorm 校验 (``input_i ≈ -16``)
  - 噪声底噪降低 ≥ 10 dB
  - 静音段自动修剪
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# 任务验收目标响度 (EBU R128)
DEFAULT_LOUDNESS_I = -16.0
DEFAULT_LOUDNESS_TP = -1.5
DEFAULT_LOUDNESS_LRA = 11.0
# 验收容差：校验时 input_i 与目标差 ≤ 此值视为通过
DEFAULT_LOUDNESS_TOLERANCE = 2.0


@dataclass
class MasteringConfig:
    """母带后处理配置。

    所有开关均可独立启用/关闭，便于按格式 (M4B/MP3) 或测试需要组合。
    """

    # 1) 降噪 (ffmpeg afftdn —— noisereduce 的原生等效)
    enable_noisereduce: bool = True
    noisereduce_nr: float = 12.0  # afftdn: 降噪量 (dB)
    noisereduce_nf: float = -30.0  # afftdn: 本底噪声基底 (dB)

    # 2) 静音段修剪
    enable_silenceremove: bool = True
    silence_start_threshold: float = -55.0  # dB，低于此值视为静音 (起始)
    silence_stop_threshold: float = -40.0  # dB，高于此值视为有声 (结束)
    silence_min_duration: float = 0.3  # s，最小静音时长才修剪

    # 3) 响度归一化 (loudnorm)
    enable_loudnorm: bool = True
    loudness_i: float = DEFAULT_LOUDNESS_I
    loudness_tp: float = DEFAULT_LOUDNESS_TP
    loudness_lra: float = DEFAULT_LOUDNESS_LRA

    # 输出规格
    sample_rate: int = 44100
    channels: int = 1
    # 输出编码：根据扩展名自动选择 (见 _codec_for_path)；此处为兜底
    codec: str = "pcm_s16le"
    bitrate: str = "128k"
    # 是否使用 loudnorm 两遍法 (更精确命中目标响度)
    two_pass_loudnorm: bool = True
    # ffmpeg 可执行文件
    ffmpeg_bin: str = "ffmpeg"


# ---------------------------------------------------------------------------
# 滤镜图构建
# ---------------------------------------------------------------------------


def build_master_filtergraph(cfg: MasteringConfig, measured: Optional[Dict[str, float]] = None) -> str:
    """构建 ffmpeg ``-af`` 滤镜图字符串。

    Args:
        cfg: 母带配置
        measured: 两遍法第一遍测得的响度参数
                  {input_i, input_tp, input_lra, input_thresh, target_offset}
                  为空则使用单遍 loudnorm。
    """
    parts: list[str] = []

    if cfg.enable_noisereduce:
        parts.append(f"afftdn=nr={cfg.noisereduce_nr}:nf={cfg.noisereduce_nf}")

    if cfg.enable_silenceremove:
        parts.append(
            "silenceremove="
            f"start_periods=1:start_threshold={cfg.silence_start_threshold}dB:"
            f"start_silence={cfg.silence_min_duration}:"
            f"stop_periods=-1:stop_threshold={cfg.silence_stop_threshold}dB:"
            f"stop_silence={cfg.silence_min_duration}"
        )

    if cfg.enable_loudnorm:
        if measured and all(
            k in measured for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
        ):
            # 两遍法：使用第一遍测得参数精确应用
            parts.append(
                "loudnorm="
                f"I={cfg.loudness_i}:TP={cfg.loudness_tp}:LRA={cfg.loudness_lra}:"
                f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
                f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
                f"offset={measured['target_offset']}:linear=true:print_format=summary"
            )
        else:
            # 单遍法 (近似)
            parts.append(f"loudnorm=I={cfg.loudness_i}:TP={cfg.loudness_tp}:LRA={cfg.loudness_lra}")

    return ",".join(parts)


# ---------------------------------------------------------------------------
# ffmpeg 辅助
# ---------------------------------------------------------------------------


def _codec_for_path(path: Path) -> tuple[str, str]:
    """根据输出扩展名选择编码与码率。"""
    suffix = path.suffix.lower()
    if suffix in (".wav",):
        return "pcm_s16le", ""
    if suffix in (".mp3",):
        return "libmp3lame", "192k"
    if suffix in (".m4a", ".aac"):
        return "aac", "128k"
    if suffix in (".ogg", ".oga"):
        return "libvorbis", "128k"
    if suffix in (".flac",):
        return "flac", ""
    return "copy", ""


def _run_ffmpeg(cmd: list[str], ffmpeg_bin: str, timeout: int = 300) -> subprocess.CompletedProcess:
    full_cmd = [ffmpeg_bin, "-y", *cmd[1:]] if cmd and cmd[0] == "ffmpeg" else cmd
    logger.info("mastering ffmpeg: %s", " ".join(full_cmd))
    return subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)


_LOUDNORM_JSON_RE = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.DOTALL)


def _parse_loudnorm_json(stderr_text: str) -> Dict[str, float]:
    """从 ffmpeg stderr 中解析 loudnorm print_format=json 的 JSON 输出。"""
    match = _LOUDNORM_JSON_RE.search(stderr_text or "")
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except (ValueError, json.JSONDecodeError):
        return {}
    result: Dict[str, float] = {}
    for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
        if key in data:
            try:
                result[key] = float(data[key])
            except (TypeError, ValueError):
                pass
    return result


# ---------------------------------------------------------------------------
# 对外 API
# ---------------------------------------------------------------------------


def measure_loudness(
    input_path: str | Path,
    ffmpeg_bin: str = "ffmpeg",
    target_i: float = DEFAULT_LOUDNESS_I,
    timeout: int = 120,
) -> Dict[str, float]:
    """测量音频的集成响度 (Integrated Loudness)。

    等价于任务验收命令::

        ffmpeg -i output.m4b -af loudnorm=I=-16:print_format=json -f null -

    返回的 ``input_i`` 即为该音频当前的集成响度 (LUFS)。
    """
    cmd = [
        ffmpeg_bin,
        "-i",
        str(input_path),
        "-af",
        f"loudnorm=I={target_i}:TP={DEFAULT_LOUDNESS_TP}:LRA={DEFAULT_LOUDNESS_LRA}:print_format=json",
        "-f",
        "null",
        "-",
    ]
    proc = _run_ffmpeg(cmd, ffmpeg_bin, timeout=timeout)
    return _parse_loudnorm_json(proc.stderr)


def master_audio(
    input_path: str | Path,
    output_path: str | Path,
    cfg: Optional[MasteringConfig] = None,
    timeout: int = 300,
) -> Dict[str, object]:
    """对单个音频文件应用完整母带后处理链路。

    处理顺序：降噪 → 静音修剪 → 响度归一化 (默认两遍)。

    Args:
        input_path: 输入音频
        output_path: 输出音频 (扩展名决定编码)
        cfg: 母带配置；为空使用默认 (全部启用，目标 -16 LUFS)

    Returns:
        包含处理结果的字典：
        {
            "input_path", "output_path",
            "filtergraph", "measured" (第一遍测量),
            "output_loudness" (处理后测量), "ffmpeg_returncode"
        }
    """
    cfg = cfg or MasteringConfig()
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        logger.error("mastering: 输入文件不存在: %s", input_path)
        return {
            "input_path": str(input_path),
            "output_path": str(output_path),
            "filtergraph": "",
            "measured": {},
            "output_loudness": {},
            "ffmpeg_returncode": None,
            "error": f"source not found: {input_path}",
        }

    if not build_master_filtergraph(cfg):
        # 全部关闭：直接拷贝
        logger.info("mastering: 所有步骤关闭，直接拷贝 %s -> %s", input_path, output_path)
        output_path.write_bytes(input_path.read_bytes())
        return {
            "input_path": str(input_path),
            "output_path": str(output_path),
            "filtergraph": "",
            "measured": {},
            "output_loudness": {},
            "ffmpeg_returncode": 0,
        }

    measured: Dict[str, float] = {}
    if cfg.enable_loudnorm and cfg.two_pass_loudnorm:
        measured = measure_loudness(input_path, cfg.ffmpeg_bin, cfg.loudness_i)

    fg = build_master_filtergraph(cfg, measured=measured or None)
    codec, bitrate = _codec_for_path(output_path)

    cmd = [
        cfg.ffmpeg_bin,
        "-i",
        str(input_path),
        "-af",
        fg,
        "-ar",
        str(cfg.sample_rate),
        "-ac",
        str(cfg.channels),
        "-c:a",
        codec,
    ]
    if bitrate:
        cmd += ["-b:a", bitrate]
    cmd.append(str(output_path))

    proc = _run_ffmpeg(cmd, cfg.ffmpeg_bin, timeout=timeout)

    output_loudness: Dict[str, float] = {}
    if proc.returncode == 0 and output_path.exists():
        output_loudness = measure_loudness(output_path, cfg.ffmpeg_bin, cfg.loudness_i)

    return {
        "input_path": str(input_path),
        "output_path": str(output_path),
        "filtergraph": fg,
        "measured": measured,
        "output_loudness": output_loudness,
        "ffmpeg_returncode": proc.returncode,
    }


def verify_mastering(
    input_path: str | Path,
    target_i: float = DEFAULT_LOUDNESS_I,
    tolerance: float = DEFAULT_LOUDNESS_TOLERANCE,
    ffmpeg_bin: str = "ffmpeg",
) -> Dict[str, object]:
    """验收校验：测量音频响度是否命中目标 (input_i ≈ target_i)。

    对应任务验收命令::

        ffmpeg -i output.m4b -af loudnorm=I=-16:print_format=json -f null -
        # 期望 output 的 input_i ≈ -16

    Returns:
        {
            "passed": bool,
            "input_i": Optional[float],
            "target_i": float,
            "delta": Optional[float],
            "within_tolerance": bool,
        }
    """
    try:
        m = measure_loudness(input_path, ffmpeg_bin, target_i)
    except (subprocess.SubprocessError, OSError, RuntimeError) as exc:
        logger.warning("verify_mastering 测量失败: %s", exc)
        return {
            "passed": False,
            "input_i": None,
            "target_i": target_i,
            "delta": None,
            "within_tolerance": False,
            "error": str(exc),
        }

    input_i = m.get("input_i")
    delta = (input_i - target_i) if input_i is not None else None
    within = delta is not None and abs(delta) <= tolerance
    return {
        "passed": within,
        "input_i": input_i,
        "target_i": target_i,
        "delta": delta,
        "within_tolerance": within,
    }
