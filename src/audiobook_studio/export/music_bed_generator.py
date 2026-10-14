"""
程序化音乐床生成器 (v6 移植 + 通用化).

将 v6 的本章定制和声床泛化为：
输入: 情绪时间线 [(start_s, end_s, emotion_tag, intensity)]
输出: 按情绪分段配和声的整段床 (solo 标定 ~-26 LUFS)

纯 numpy/scipy/soundfile 实现，无 torch 依赖。
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import soundfile as sf
from scipy.signal import lfilter

logger = logging.getLogger(__name__)


@dataclass
class EmotionSegment:
    """情绪时间线分段."""
    start_s: float
    end_s: float
    emotion: str
    intensity: float  # 0.0 - 1.0


# 和弦字典 (MIDI 音符号)
CHORDS = {
    # 小调系
    "Am": [45, 57, 60, 64],
    "F": [41, 53, 57, 60],
    "E": [40, 52, 56, 59],
    "Am5": [45, 57, 64],      # 无三度的力量和弦
    # 大调系
    "C": [48, 55, 60, 64],
    "G": [43, 55, 59, 62],
    "Cadd9": [48, 55, 62, 64],
}


# 情绪 -> 和弦进行映射 (可微调)
EMOTION_TO_PROGRESSION = {
    # 紧张/焦虑/恐惧/悲伤/阴郁 -> 小调系
    "tense": (["Am", "F", "Am", "E"], -27.5),
    "anxious": (["Am", "F", "Am", "E"], -27.5),
    "fearful": (["Am", "F", "Am", "E"], -27.5),
    "sad": (["Am", "F", "Am", "E"], -28.0),
    "gloomy": (["Am", "F", "Am", "E"], -28.5),
    # 愤怒/暴怒 -> 小调强进行
    "angry": (["Am", "E", "Am", "E"], -26.5),
    "furious": (["Am", "E", "Am", "E"], -26.0),
    # 中性/平静/怀旧 -> 轻小调
    "neutral": (["Am", "F", "C", "G"], -29.0),
    "calm": (["Am", "F", "C", "G"], -29.5),
    "nostalgic": (["Am", "F", "C", "G"], -29.0),
    # 开心/兴奋/希望/胜利 -> 大调系
    "happy": (["C", "F", "G", "C"], -27.0),
    "excited": (["C", "G", "Am", "F"], -26.5),
    "hopeful": (["C", "F", "G", "C"], -27.5),
    "triumphant": (["C", "G", "C", "F"], -25.5),
    # 人群/庆祝场景 -> 特殊标记 (后续加人群层)
    "crowd": (["C", "G", "Am", "F"], -27.0),
    "celebration": (["C", "G", "C", "F"], -26.0),
}

DEFAULT_PROGRESSION = (["Am", "F", "C", "G"], -28.0)  # 温和中性循环
DEFAULT_SR = 44100
BED_TARGET_LUFS = -26.0


def midi_hz(m: int) -> float:
    """MIDI 音符号转频率."""
    return 440.0 * 2 ** ((m - 69) / 12)


def bandpass_fft(x: np.ndarray, sr: int, lo: float, hi: float, trans: float = 30.0) -> np.ndarray:
    """FFT 带通滤波 (带升余弦过渡带)."""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / sr)
    g = np.ones_like(f)
    g[f < lo] = 0
    g[f > hi] = 0
    m1 = (f >= lo) & (f < lo + trans)
    if np.any(m1):
        g[m1] = 0.5 * (1 - np.cos(np.pi * (f[m1] - lo) / trans))
    m2 = (f > hi - trans) & (f <= hi)
    if np.any(m2):
        g[m2] = 0.5 * (1 + np.cos(np.pi * (f[m2] - (hi - trans)) / trans))
    return np.fft.irfft(X * g, n=len(x)).astype(np.float32)


def synth_pad_chord(
    n_samples: int,
    notes: List[int],
    sr: int = DEFAULT_SR,
    detune_pct: float = 0.0012,      # ±0.12%
    harm2_gain: float = 0.45,
    harm3_gain: float = 0.22,
) -> np.ndarray:
    """
    合成和弦 pad：正弦 + 2/3 次谐波，双振荡器失谐.
    """
    t = np.arange(n_samples) / sr
    out = np.zeros(n_samples, dtype=np.float32)
    for m in notes:
        f = midi_hz(m)
        for sign in (+1, -1):
            fd = f * (1 + sign * detune_pct)
            w = 2 * np.pi * fd * t
            out += np.sin(w) + harm2_gain * np.sin(2 * w) + harm3_gain * np.sin(3 * w)
    out /= (len(notes) * 2)
    return out.astype(np.float32)


def env_db(
    total_n: int,
    sr: int,
    windows: List[Tuple[float, float, float, float, float, float]],
) -> np.ndarray:
    """
    分段电平包络 (dB 线性插值 + 升余弦边沿).
    windows: list of (t0, t1, db0, db1, edge_in, edge_out)
    """
    t = np.arange(total_n) / sr
    lin = np.zeros(total_n, dtype=np.float32)
    for t0, t1, d0, d1, ei, eo in windows:
        m = (t >= t0) & (t <= t1)
        if not np.any(m):
            continue
        frac = (t[m] - t0) / max(t1 - t0, 1e-6)
        db = d0 + (d1 - d0) * frac
        # 边沿升余弦收边
        edge_m = np.ones_like(db)
        if ei > 0:
            fi = (t[m] - t0) / ei
            fi = np.clip(fi, 0, 1)
            edge_m *= 0.5 * (1 - np.cos(np.pi * fi))
        if eo > 0:
            fo = (t1 - t[m]) / eo
            fo = np.clip(fo, 0, 1)
            edge_m *= 0.5 * (1 - np.cos(np.pi * fo))
        lin[m] = 10 ** (db / 20) * edge_m
    return lin


def build_heartbeat(
    total_n: int,
    sr: int,
    bpm: float = 62.0,
    lub_dur: float = 0.32,
    dub_dur: float = 0.26,
    lub_amp: float = 1.0,
    dub_amp: float = 0.6,
    f: float = 48.0,
    decay: float = 0.10,
) -> np.ndarray:
    """构建 lub-dub 心跳序列."""
    beat = int(sr * 60 / bpm)

    def thump(dur: float, amp: float) -> np.ndarray:
        n = int(dur * sr)
        tt = np.arange(n) / sr
        e = np.exp(-tt / decay)
        return (amp * np.sin(2 * np.pi * f * tt) * e).astype(np.float32)

    lub = thump(lub_dur, lub_amp)
    dub = thump(dub_dur, dub_amp)

    out = np.zeros(total_n, dtype=np.float32)
    k = 0
    gap = int(0.24 * sr)  # lub-dub 间隔 ~240ms
    while k * beat + len(lub) + gap < total_n:
        s = k * beat
        end_lub = s + len(lub)
        if end_lub <= total_n:
            out[s:end_lub] += lub[:total_n - s]
        d = s + gap
        end_dub = d + len(dub)
        if d < total_n:
            out[d:min(end_dub, total_n)] += dub[:total_n - d]
        k += 1
    return out


def build_crowd(total_n: int, sr: int, seed: int = 42) -> np.ndarray:
    """构建人群带通噪声层."""
    rng = np.random.RandomState(seed)
    x = rng.randn(total_n)
    # 主体 350-1400Hz
    b = bandpass_fft(x, sr, 350, 1400)
    # 高频成分 2-4kHz × 0.3
    hi = bandpass_fft(x, sr, 2000, 4000) * 0.3
    y = b + hi
    # 慢随机幅度调制 (0.5Hz 平滑)
    mod_n = int(total_n / (sr * 2)) + 2
    mod_t = np.arange(mod_n) * 2.0
    mod_v = 0.7 + 0.3 * rng.rand(mod_n)
    t_bed = np.arange(total_n) / sr
    mod = np.interp(t_bed, mod_t, mod_v)
    return (y * mod).astype(np.float32)


def schroeder_reverb(x: np.ndarray, sr: int) -> np.ndarray:
    """Schroeder 混响: 4 comb + 2 allpass."""
    combs = [1601, 1613, 1487, 1277]  # 样本 @44.1k
    aps = [225, 556]
    y = np.zeros_like(x)
    for D in combs:
        g = 0.84
        a = np.zeros(D + 1)
        a[0] = 1
        a[-1] = -g
        y += lfilter([1.0], a, x)
    y /= len(combs)
    for D in aps:
        g = 0.5
        b = np.zeros(D + 1)
        b[0] = -g
        b[-1] = 1
        a = np.zeros(D + 1)
        a[0] = 1
        a[-1] = -g
        y = lfilter(b, a, y)
    return y


def measure_lufs_ebur128(path: Path) -> float:
    """用 ffmpeg ebur128 测量 integrated loudness (LUFS)."""
    import subprocess
    import re

    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    err = r.stderr[r.stderr.find("Summary:") :]
    match = re.search(r"I:\s*(-?\d+\.?\d*)\s*LUFS", err)
    if not match:
        raise RuntimeError(f"ebur128 parse failed: {err[-200:]}")
    return float(match.group(1))


def emotion_to_progression(emotion: str) -> Tuple[List[str], float]:
    """
    情绪标签 -> (和弦进行列表, 基础 dB).
    未知情绪回退到 DEFAULT_PROGRESSION.
    """
    key = emotion.lower().strip()
    if key in EMOTION_TO_PROGRESSION:
        return EMOTION_TO_PROGRESSION[key]
    # 模糊匹配：包含关键词
    for k, v in EMOTION_TO_PROGRESSION.items():
        if k in key:
            return v
    return DEFAULT_PROGRESSION


def merge_adjacent_same_chords(
    timeline: List[EmotionSegment],
) -> List[Tuple[float, float, List[str], float]]:
    """
    合并相邻同和弦进行的情绪段，返回 (t0, t1, chords, base_db).
    """
    if not timeline:
        return []

    merged = []
    for seg in timeline:
        chords, base_db = emotion_to_progression(seg.emotion)
        # intensity 映射到 dB 偏移: 0.0 -> 0dB, 1.0 -> +4dB (更亮/更响)
        db_offset = seg.intensity * 4.0
        adj_db = base_db + db_offset
        if merged and merged[-1][2] == chords:
            # 同和弦进行：延长结束时间
            merged[-1] = (merged[-1][0], seg.end_s, chords, merged[-1][3])
        else:
            merged.append((seg.start_s, seg.end_s, chords, adj_db))
    return merged


def generate_music_bed(
    timeline: List[EmotionSegment],
    total_duration_s: float,
    out_path: Path,
    sr: int = DEFAULT_SR,
    seed: int = 42,
    enable_heartbeat: bool = True,
    enable_crowd: bool = True,
    enable_reverb: bool = True,
    reverb_wet: float = 0.18,
    lfo_hz: float = 0.08,
    lfo_depth: float = 0.12,
    pad_bandpass: Tuple[float, float] = (65.0, 2200.0),
    fade_in_s: float = 1.5,
    fade_out_s: float = 4.5,
) -> Path:
    """
    生成程序化音乐床.

    Args:
        timeline: 情绪时间线 [(start_s, end_s, emotion, intensity)]
        total_duration_s: 总时长 (秒)
        out_path: 输出文件路径
        sr: 采样率 (默认 44100)
        seed: 随机种子
        enable_heartbeat: 是否启用心跳层
        enable_crowd: 是否启用人群层 (针对 crowd/celebration 等情绪自动判断)
        enable_reverb: 是否启用 Schroeder 混响
        reverb_wet: 混响湿信号比例
        lfo_hz: 慢 LFO 频率
        lfo_depth: LFO 深度
        pad_bandpass: pad 带通范围
        fade_in_s: 整体淡入时长
        fade_out_s: 整体淡出时长

    Returns:
        输出文件路径
    """
    np.random.seed(seed)
    total_n = int(total_duration_s * sr)

    # 1. 合并相邻同和弦进行
    merged = merge_adjacent_same_chords(timeline)

    # 2. 生成 pad (和弦 pad + 交叉淡入淡出 + LFO + 带通)
    pad = np.zeros(total_n, dtype=np.float32)
    chord_dur = 8.0  # 每个和弦 8 秒
    crossfade_s = 2.5  # 交叉淡入淡出 2.5s

    for t0, t1, chords, base_db in merged:
        t0_n = int(t0 * sr)
        t1_n = int(t1 * sr)
        seg_n = t1_n - t0_n
        if seg_n <= 0:
            continue
        ch_n = seg_n / len(chords)
        for ci, ch in enumerate(chords):
            cs = t0_n + int(ci * ch_n)
            # 每个和弦段包含 2.5s 淡出尾
            n_ch = int(ch_n + crossfade_s * sr)
            n_ch = min(n_ch, total_n - cs)
            if n_ch <= 0:
                continue
            w = synth_pad_chord(n_ch, CHORDS[ch], sr)
            # 包络：淡入/淡出 2.5s 升余弦
            env = np.ones(n_ch, dtype=np.float32)
            fi = int(crossfade_s * sr)
            fo = int(crossfade_s * sr)
            if ci > 0 and n_ch >= fi:
                env[:fi] = 0.5 * (1 - np.cos(np.linspace(0, np.pi, fi)))
            if n_ch >= fo:
                env[-fo:] = 0.5 * (1 + np.cos(np.linspace(0, np.pi, fo)))
            pad[cs:cs + n_ch] += w * env * (10 ** (base_db / 20))

    # 慢 LFO 调制 (0.08Hz, 深度 0.12)
    t_bed = np.arange(total_n) / sr
    lfo = 1 - lfo_depth * (0.5 + 0.5 * np.sin(2 * np.pi * lfo_hz * t_bed))
    pad *= lfo.astype(np.float32)

    # FFT 带通 65-2200Hz
    pad = bandpass_fft(pad, sr, pad_bandpass[0], pad_bandpass[1])

    # 3. 心跳层 (可选，针对 tense/anxious/fearful/angry 等)
    hb = np.zeros(total_n, dtype=np.float32)
    if enable_heartbeat:
        hb0 = build_heartbeat(total_n, sr)
        # 心跳窗：根据情绪时间线决定哪里放心跳
        hb_windows = []
        for seg in timeline:
            emo = seg.emotion.lower()
            if emo in ("tense", "anxious", "fearful", "angry", "furious", "sad", "gloomy"):
                # intensity 映射到相对电平：0.0 -> -12dB, 1.0 -> -6dB
                rel_db = -12 + seg.intensity * 6
                hb_windows.append((seg.start_s, seg.end_s, rel_db, rel_db, 0.4, 0.4))
        if hb_windows:
            hb_env = env_db(total_n, sr, hb_windows)
            hb = hb0 * hb_env

    # 4. 人群层 (可选，针对 crowd/celebration/excited/triumphant)
    crowd = np.zeros(total_n, dtype=np.float32)
    if enable_crowd:
        crowd0 = build_crowd(total_n, sr, seed)
        crowd_windows = []
        for seg in timeline:
            emo = seg.emotion.lower()
            if emo in ("crowd", "celebration", "excited", "triumphant", "happy"):
                rel_db = -8 + seg.intensity * 4  # -8 到 -4 dB
                crowd_windows.append((seg.start_s, seg.end_s, rel_db, rel_db, 3.0, 0.0))
        if crowd_windows:
            crowd_env = env_db(total_n, sr, crowd_windows)
            crowd = crowd0 * crowd_env

    # 5. 干声求和 -> 混响
    bed_dry = pad + hb + crowd
    bed = bed_dry
    if enable_reverb:
        bed_rev = schroeder_reverb(bed_dry, sr)
        bed = (1 - reverb_wet) * bed_dry + reverb_wet * bed_rev

    # 6. 整体淡入淡出
    fade = np.ones(total_n, dtype=np.float32)
    fi_n = int(fade_in_s * sr)
    if fi_n > 0:
        fade[:fi_n] = 0.5 * (1 - np.cos(np.linspace(0, np.pi, fi_n)))
    fo_n = int((total_duration_s - fade_out_s) * sr)
    if fo_n < total_n:
        fade[fo_n:] = 0.5 * (1 + np.cos(np.linspace(0, np.pi, total_n - fo_n)))
    bed *= fade

    # 7. 写临时文件并测量 LUFS -> 线性增益校准到 -26 LUFS
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(".tmp.wav")
    sf.write(str(tmp_path), bed, sr, subtype="FLOAT")

    bed_lufs = measure_lufs_ebur128(tmp_path)
    gain_db = BED_TARGET_LUFS - bed_lufs
    bed *= 10 ** (gain_db / 20)

    # 重写最终文件
    sf.write(str(out_path), bed, sr, subtype="PCM_16")
    tmp_path.unlink(missing_ok=True)

    logger.info(f"[music_bed] generated: {out_path} ({total_duration_s:.1f}s, {bed_lufs:.1f} LUFS -> gain {gain_db:+.1f}dB -> {BED_TARGET_LUFS} LUFS)")
    return out_path


# 便捷函数：从 paragraphs 列表构建情绪时间线
def build_timeline_from_paragraphs(
    paragraphs: List[dict],
    default_intensity: float = 0.5,
    gap_between: float = 0.0,
) -> List[EmotionSegment]:
    """
    从 paragraphs 列表构建情绪时间线.

    paragraphs 元素需包含:
    - duration_ms: 段落时长 (毫秒)
    - emotion: 情绪标签 (可选)
    - emotion_intensity: 强度 0-1 (可选)

    返回按累计时长计算 start/end 的 EmotionSegment 列表.
    """
    timeline = []
    cur_s = 0.0
    for p in paragraphs:
        dur_s = (p.get("duration_ms") or 3000) / 1000.0
        emotion = p.get("emotion") or "neutral"
        intensity = p.get("emotion_intensity") or default_intensity
        timeline.append(EmotionSegment(
            start_s=cur_s,
            end_s=cur_s + dur_s,
            emotion=emotion,
            intensity=max(0.0, min(1.0, intensity)),
        ))
        cur_s += dur_s + gap_between
    return timeline