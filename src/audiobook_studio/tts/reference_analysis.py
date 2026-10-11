"""参考音频声学分析 → Kokoro 近似克隆参数建议 (Batch 2.2).

纯 numpy + soundfile 实现 (无 torch/librosa 依赖)：
  - F0 中位数: 自相关法逐帧基频检测 (voiced 帧统计)
  - 音节速率: 能量包络峰计数 / 时长
  - 频谱质心: FFT 帧均值 (音色明暗度)
  - 置信度: voiced 帧占比 × 时长充分性

建议映射 (gender × brightness × language):
  - blend_voice: Kokoro 双音色混合语法 "a*0.6+b*0.4" (v6 验证)
  - pitch_st: 12·log2(ref_f0 / voice_base_f0), clamp [-6, +6] (ffmpeg 带式移位)
  - speed: 音节速率比, clamp [0.7, 1.3]
"""
from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# 分析帧参数
_FRAME_MS = 40          # 帧长 (ms)
_HOP_MS = 10            # 帧移 (ms)
_F0_MIN_HZ = 70.0        # 男声下限
_F0_MAX_HZ = 400.0      # 女声上限
_MIN_DURATION_S = 1.5   # 低于此时长置信度打折


@dataclass
class ReferenceAudioProfile:
    """参考音频声学画像."""
    f0_median_hz: Optional[float] = None
    f0_mean_hz: Optional[float] = None
    syllable_rate: Optional[float] = None     # 音节/秒
    spectral_centroid_hz: Optional[float] = None
    duration_s: float = 0.0
    voiced_ratio: float = 0.0                 # 有声帧占比
    sample_rate: int = 0
    confidence: float = 0.0                    # 0-1 分析置信度
    gender_guess: str = "unknown"              # male/female/unknown
    brightness: str = "neutral"                # dark/neutral/bright
    warnings: list = field(default_factory=list)


@dataclass
class KokoroCloneSuggestion:
    """Kokoro 近似克隆参数建议."""
    blend_voice: str = ""        # e.g. "am_onyx*0.6+am_fenrir*0.4" 或单音色 "am_adam"
    pitch_st: float = 0.0        # 合成后 ffmpeg 带式移位半音数
    speed: float = 1.0           # Kokoro speed 参数
    confidence: float = 0.0
    gender_guess: str = "unknown"
    brightness: str = "neutral"
    profile: Optional[ReferenceAudioProfile] = None


# ── 解码 ─────────────────────────────────────────────────────────────────────

def _decode_audio(source) -> Tuple[np.ndarray, int]:
    """解码音频 (路径/bytes) 为 (mono float32 [-1,1], sample_rate).

    soundfile 优先; 不支持的容器 (mp3/m4a) 走 ffmpeg 转 wav 再读。
    """
    import soundfile as sf

    tmp_path: Optional[Path] = None
    path: Path
    if isinstance(source, (bytes, bytearray)):
        tmp_path = Path(tempfile.mkstemp(suffix=".bin")[1])
        tmp_path.write_bytes(source)
        path = tmp_path
    else:
        path = Path(source)

    try:
        try:
            audio, sr = sf.read(str(path), dtype="float32", always_2d=True)
            return audio.mean(axis=1), sr
        except Exception:
            # 非 wav 容器 → ffmpeg 转 16k mono wav 再读
            wav_tmp = Path(tempfile.mkstemp(suffix=".wav")[1])
            import subprocess
            result = subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-i", str(path),
                 "-ac", "1", "-ar", "16000", str(wav_tmp)],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                raise ValueError(f"ffmpeg 解码失败: {result.stderr[:200]}")
            audio, sr = sf.read(str(wav_tmp), dtype="float32", always_2d=True)
            wav_tmp.unlink(missing_ok=True)
            return audio.mean(axis=1), sr
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


# ── 声学特征提取 ─────────────────────────────────────────────────────────────

def _autocorr_f0(frame: np.ndarray, sr: int) -> Optional[float]:
    """单帧自相关基频检测."""
    frame = frame - frame.mean()
    rms = float(np.sqrt(np.mean(frame ** 2)))
    if rms < 0.02:
        return None  # 静音/弱信号帧

    corr = np.correlate(frame, frame, mode="full")
    corr = corr[len(corr) // 2:]

    lag_min = int(sr / _F0_MAX_HZ)
    lag_max = int(sr / _F0_MIN_HZ)
    if lag_max >= len(corr):
        return None

    search = corr[lag_min:lag_max]
    peak_idx = int(np.argmax(search)) + lag_min
    if corr[peak_idx] <= 0 or corr[0] <= 0:
        return None

    # 归一化自相关峰值 (清晰度): 过低视为噪声
    clarity = corr[peak_idx] / corr[0]
    if clarity < 0.45:
        return None

    # 抛物线插值精化
    if lag_min < peak_idx < lag_max:
        y0, y1, y2 = corr[peak_idx - 1], corr[peak_idx], corr[peak_idx + 1]
        denom = y0 - 2 * y1 + y2
        if abs(denom) > 1e-12:
            delta = (y0 - y2) / (2 * denom)
            peak_idx_f = peak_idx + float(np.clip(delta, -0.5, 0.5))
        else:
            peak_idx_f = float(peak_idx)
    else:
        peak_idx_f = float(peak_idx)

    return sr / peak_idx_f if peak_idx_f > 0 else None


def _spectral_centroid(audio: np.ndarray, sr: int, n_frames: int = 8) -> Optional[float]:
    """等距抽帧 FFT 频谱质心均值."""
    frame_len = 2048
    if len(audio) < frame_len:
        return None
    idxs = np.linspace(0, len(audio) - frame_len, max(n_frames, 1), dtype=int)
    centroids = []
    for i in idxs:
        seg = audio[i:i + frame_len]
        if float(np.sqrt(np.mean(seg ** 2))) < 0.01:
            continue
        spec = np.abs(np.fft.rfft(seg * np.hanning(frame_len)))
        freqs = np.fft.rfftfreq(frame_len, 1.0 / sr)
        total = spec.sum()
        if total > 1e-12:
            centroids.append(float((freqs * spec).sum() / total))
    return float(np.mean(centroids)) if centroids else None


def _syllable_rate(audio: np.ndarray, sr: int) -> Optional[float]:
    """能量包络峰计数估算音节速率 (音节/秒)."""
    hop = int(sr * 0.010)  # 10ms
    n_hops = len(audio) // hop
    if n_hops < 50:
        return None
    env = np.array([
        float(np.sqrt(np.mean(audio[i * hop:(i + 1) * hop] ** 2)))
        for i in range(n_hops)
    ])
    # 平滑 + 归一化
    kernel = np.ones(5) / 5
    env_s = np.convolve(env, kernel, mode="same")
    env_max = env_s.max()
    if env_max < 1e-6:
        return None
    env_n = env_s / env_max

    # 峰检测: 局部极大 + 高于阈值 (有声核)
    peaks = []
    for i in range(2, n_hops - 2):
        if (env_n[i] >= env_n[i - 1] and env_n[i] >= env_n[i + 1]
                and env_n[i] > 0.25 and env_n[i] > env_n[i - 2] and env_n[i] > env_n[i + 2]):
            # 最小峰间距 ~120ms (防抖动)
            if not peaks or (i - peaks[-1]) > 12:
                peaks.append(i)
    duration = n_hops * 0.010
    return len(peaks) / duration if duration > 0 else None


# ── 主分析入口 ────────────────────────────────────────────────────────────────

def analyze_reference(source) -> ReferenceAudioProfile:
    """分析参考音频 (路径或 bytes) 生成声学画像."""
    profile = ReferenceAudioProfile()
    try:
        audio, sr = _decode_audio(source)
    except Exception as e:
        profile.warnings.append(f"解码失败: {e}")
        return profile

    audio = np.asarray(audio, dtype=np.float32)
    profile.sample_rate = sr
    profile.duration_s = len(audio) / sr

    if profile.duration_s < 0.3:
        profile.warnings.append(f"时长过短 ({profile.duration_s:.2f}s)")
        return profile

    # ── F0 逐帧 ──
    frame_len = int(sr * _FRAME_MS / 1000)
    hop = int(sr * _HOP_MS / 1000)
    f0s = []
    for start in range(0, len(audio) - frame_len, hop):
        f0 = _autocorr_f0(audio[start:start + frame_len], sr)
        if f0 is not None:
            f0s.append(f0)

    total_frames = max((len(audio) - frame_len) // hop, 1)
    profile.voiced_ratio = len(f0s) / total_frames
    if f0s:
        profile.f0_median_hz = float(np.median(f0s))
        profile.f0_mean_hz = float(np.mean(f0s))
    else:
        profile.warnings.append("未检测到有声帧 (F0 全空)")

    profile.spectral_centroid_hz = _spectral_centroid(audio, sr)
    profile.syllable_rate = _syllable_rate(audio, sr)

    # ── 性别 & 明暗度推断 ──
    if profile.f0_median_hz is not None:
        if profile.f0_median_hz < 165:
            profile.gender_guess = "male"
        else:
            profile.gender_guess = "female"
    if profile.spectral_centroid_hz is not None:
        # 经验阈值 (16k 采样): 男声中位 ~1.2k, 女声中位 ~2k
        if profile.gender_guess == "male":
            profile.brightness = "dark" if profile.spectral_centroid_hz < 1000 else ("bright" if profile.spectral_centroid_hz > 1600 else "neutral")
        else:
            profile.brightness = "dark" if profile.spectral_centroid_hz < 1500 else ("bright" if profile.spectral_centroid_hz > 2600 else "neutral")

    # ── 置信度 ──
    dur_factor = min(1.0, profile.duration_s / 6.0)
    conf = profile.voiced_ratio * 0.6 + dur_factor * 0.4
    if profile.f0_median_hz is None:
        # 无任何有声帧: F0/性别/明暗度全未知, 建议等同盲猜 → 置信度诚实归零
        # (纯时长因子不应在零 voiced 样本上独扛出非零置信度)
        conf = 0.0
    if profile.duration_s < _MIN_DURATION_S:
        profile.warnings.append(f"参考音频较短 ({profile.duration_s:.1f}s < {_MIN_DURATION_S}s), 参数估计置信度受限")
    profile.confidence = round(float(np.clip(conf, 0.0, 1.0)), 3)

    logger.info(
        f"[RefAnalysis] f0_med={profile.f0_median_hz}Hz syl_rate={profile.syllable_rate} "
        f"centroid={profile.spectral_centroid_hz}Hz dur={profile.duration_s:.1f}s "
        f"gender={profile.gender_guess} bright={profile.brightness} conf={profile.confidence}"
    )
    return profile


# ── Kokoro 参数映射 ──────────────────────────────────────────────────────────

# blend 建议 (gender × brightness → 双音色混合语法; v6 验证过的混合声理念)
# base_f0 为该混合声的近似基频, 用于计算 pitch_st
_BLEND_TABLE = {
    ("male", "dark"):    ("am_onyx*0.6+am_fenrir*0.4", 102.0),
    ("male", "neutral"): ("am_adam", 112.0),
    ("male", "bright"):  ("am_puck*0.6+am_liam*0.4", 128.0),
    ("female", "dark"):   ("af_nicole*0.6+af_sarah*0.4", 205.0),
    ("female", "neutral"): ("af_bella", 210.0),
    ("female", "bright"):  ("af_sky", 220.0),
}
_BLEND_TABLE_ZH = {
    ("male", "dark"):    ("zm_yunyang*0.6+zm_yunjian*0.4", 112.0),
    ("male", "neutral"): ("zm_yunxi", 122.0),
    ("male", "bright"):  ("zm_yunxia*0.6+zm_yunxi*0.4", 125.0),
    ("female", "dark"):    ("zf_xiaoni*0.5+zf_xiaoxuan*0.5", 212.0),
    ("female", "neutral"): ("zf_xiaobei", 218.0),
    ("female", "bright"):  ("zf_xiaoxiao", 225.0),
}

# 典型音节速率 (音节/秒)
_TYPICAL_SYL_RATE = {"zh": 4.5, "en": 3.5}


def suggest_kokoro_params(
    profile: ReferenceAudioProfile,
    language: str = "zh",
    gender_hint: Optional[str] = None,
) -> KokoroCloneSuggestion:
    """将参考音频画像映射为 Kokoro 近似克隆参数.

    Args:
        profile: analyze_reference() 的输出
        language: 目标语言 (zh/en), 决定音色池与速率基准
        gender_hint: 显式性别提示 ("male"/"female"), 覆盖 F0 推断 —
            165-200Hz 重叠区 F0 推断不可靠, 调用方已知说话人性别时建议传入

    Returns:
        KokoroCloneSuggestion (blend_voice / pitch_st / speed / confidence)
    """
    # gender_hint 覆盖 F0 推断
    effective_gender = (gender_hint if gender_hint in ("male", "female")
                        else profile.gender_guess)
    if gender_hint in ("male", "female") and gender_hint != profile.gender_guess:
        profile.warnings.append(
            f"gender_hint={gender_hint} 覆盖 F0 推断 ({profile.gender_guess})"
        )
    s = KokoroCloneSuggestion(
        gender_guess=effective_gender,
        brightness=profile.brightness,
    )
    lang = "zh" if language.startswith("zh") else "en"
    table = _BLEND_TABLE_ZH if lang == "zh" else _BLEND_TABLE
    gender = "female" if s.gender_guess == "female" else "male"

    # ── blend 音色选择 ──
    # 策略: F0 可用时按「基频距离最小」在同性别三档中选声 (F0 匹配主导,
    # 明暗度只作并列打破项) — 避免 centroid 判 dark 后把高音男声映射到
    # 最低基频音色导致 pitch_st 顶 clamp; F0 缺失时退回明暗度直选。
    if profile.f0_median_hz is not None and profile.f0_median_hz > 0:
        candidates = {b: table[(gender, b)] for b in ("dark", "neutral", "bright")}
        # 基频距离排序; 并列时按明暗度优先
        ordered = sorted(
            candidates.items(),
            key=lambda kv: (abs(12.0 * np.log2(profile.f0_median_hz / kv[1][1])),
                            0 if kv[0] == profile.brightness else 1),
        )
        s.blend_voice, base_f0 = ordered[0][1]
    else:
        s.blend_voice, base_f0 = table.get(
            (gender, profile.brightness), table[(gender, "neutral")]
        )

    # ── pitch_st: 参考基频 → 音色基频的移位量 (半音), clamp ±6 ──
    if profile.f0_median_hz is not None and profile.f0_median_hz > 0 and base_f0 > 0:
        ratio = profile.f0_median_hz / base_f0
        s.pitch_st = round(float(np.clip(12.0 * np.log2(ratio), -6.0, 6.0)), 2)
        if abs(s.pitch_st) >= 5.9:
            profile.warnings.append(
                f"pitch 移位量已达 clamp 边界 ({s.pitch_st:+.1f}st): 参考音高与所选音色差异过大, 克隆近似度受限"
            )

    # ── speed: 参考音节速率 / 语言典型速率, clamp [0.7, 1.3] ──
    if profile.syllable_rate is not None and profile.syllable_rate > 0:
        typical = _TYPICAL_SYL_RATE.get(lang, 4.0)
        s.speed = round(float(np.clip(profile.syllable_rate / typical, 0.7, 1.3)), 2)

    s.confidence = profile.confidence
    return s


__all__ = [
    "ReferenceAudioProfile",
    "KokoroCloneSuggestion",
    "analyze_reference",
    "suggest_kokoro_params",
]
