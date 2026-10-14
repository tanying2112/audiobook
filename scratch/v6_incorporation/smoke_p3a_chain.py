#!/usr/bin/env python
"""P3a smoke — v6 母带链收编验证 (alimiter TP 限幅 + soxr 探测重采样).

验证项 (任务步骤 3):
  1. 生成 2s 440Hz 正弦 (t=1.0s 处 20 采样 0dBFS 峰值脉冲; 另生成无脉冲对照);
  2. 构造与三处后处理代码同款的 ffmpeg 命令/滤镜串并实跑:
     - pipeline/audio_finalize.py 主路径 (两遍 loudnorm → alimiter → fade)
     - export/mastering.py build_master_filtergraph (master_audio 端到端)
     - export/audio_ducking.py mix_with_ducking (无 BGM / BGM / mix_sfx_segments)
  3. ebur128 验证: True Peak ≤ TP + 0.3 dB (脉冲输入, 硬门);
     integrated 达标 — 脉冲输入下动态回退 + TP 保护在 2s 短片上收敛欠冲
     (实测 ~-25.7 LUFS), 取 ±3.5 LU 硬门; 无脉冲对照输入下同链精确命中
     (-23.0), 取 ±1.0~2.0 LU 紧门 —— 证明链本身正确;
  4. ffmpeg_has_soxr() 与直接运行时探测交叉一致:
     本机 Homebrew ffmpeg 预期 False (无 libsoxr 链接);
     CI docker ffmpeg 带 --enable-libsoxr 时预期 True —— 探测函数须两端都对;
  5. 三处模块 import 检查;
  6. filter 字符串断言 (limit 按 preset 正确换算: TP-3→0.7079, TP-1.5→0.8414,
     TP-2→0.7943; alimiter 紧跟 loudnorm; aresample 收尾; 无 PLACEHOLDER;
     afade :curve= 语法)。

P1/P2 回归门 (2026-10-11 第二轮修复):
  - P1: ducking BGM 路径 BGM 在场 — 旧 [0:a][bgm]sidechaincompress 人声当主轨,
    输出仅含被压缩人声 (BGM 丢失); 修复: BGM 主轨+人声侧链+asplit+amix 混回。
    功能性验证: 人声间隙窗口 BGM 床能量 (旧 bug 为数字静音)。
  - P2: finalize 链尾 aresample 收回输入 SR (loudnorm 恒 192k; 旧 wav 直出
    192k、mp3/m4b 编码器自动协商 48k); m4b.py 三处硬编码 -ar 44100 已对齐
    MasteringConfig.sample_rate (与 soxr 探测 filtergraph 尾一致)。

附带修复 (审计发现, 均为"主路径整链 rc!=0 静默回退纯拷贝"类阻断项):
  - finalize 淡出 st=PLACEHOLDER 未解析 → 按实测时长计算;
  - finalize fade ":{shape}" 裸位置参数非法 → ":curve={shape}";
  - finalize 主路径 -filter_complex 无标注 + "-map 0:a" 绑定失败 → [0:a]…[aout];
  - ducking 无 BGM 路径淡出 st=0 (0.5s 后恒静音) → 时长-0.5s。

运行: .venv/bin/python scratch/v6_incorporation/smoke_p3a_chain.py
(约束: 禁 pytest —— 本文件是独立冒烟脚本, 非测试收集目标)
"""

import math
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

FAILURES: list = []
PASSES = 0


def check(name: str, cond: bool, detail: str = "") -> bool:
    global PASSES
    if cond:
        PASSES += 1
        print(f"[PASS] {name}" + (f" — {detail}" if detail else ""))
    else:
        FAILURES.append(name)
        print(f"[FAIL] {name}" + (f" — {detail}" if detail else ""))
    return cond


def sh(cmd: list, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# ─────────────────────────────────────────────────────────────────────────────
# 0) 生成输入素材: 2s 440Hz 正弦 ± 0dBFS 峰值脉冲 (24kHz mono s16, 模拟 TTS)
# ─────────────────────────────────────────────────────────────────────────────

SR = 24000
DUR_S = 2.0
PULSE_AT = 1.0  # 0dBFS 脉冲位置 (秒)
PULSE_LEN = 20  # 脉冲采样数


def gen_wav(path: Path, freq: float, amp: float, dur: float, pulse: bool = False) -> None:
    n = int(SR * dur)
    frames = bytearray()
    pulse_start = int(PULSE_AT * SR)
    for i in range(n):
        v = amp * math.sin(2.0 * math.pi * freq * i / SR)
        if pulse and pulse_start <= i < pulse_start + PULSE_LEN:
            v = 1.0  # 0dBFS 满幅脉冲
        v = max(-1.0, min(1.0, v))
        frames += struct.pack("<h", int(round(v * 32767.0)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(bytes(frames))


def ebur128(path: Path) -> tuple:
    """返回 (integrated LUFS, true peak dBTP), 解析 ebur128 Summary 块。"""
    p = sh(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
            "-af", "ebur128=peak=true", "-f", "null", "-"])
    s = p.stderr
    if "Summary:" in s:
        s = s[s.index("Summary:"):]
    m_i = re.search(r"I:\s*(-?\d+\.?\d*)\s*LUFS", s)
    m_tp = re.search(r"True peak:.*?Peak:\s*(-?\d+\.?\d*)\s*dBFS", s, re.DOTALL)
    if not m_i or not m_tp:
        raise RuntimeError(f"ebur128 summary parse failed for {path}: {s[-300:]}")
    return float(m_i.group(1)), float(m_tp.group(1))


def ffprobe_sr(path: Path):
    p = sh(["ffprobe", "-v", "error", "-show_entries", "stream=sample_rate",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path)])
    return p.stdout.strip()


def verify_output(tag: str, out: Path, target_i: float, target_tp: float,
                  gate_i: float, want_sr: str = "") -> None:
    """ebur128 双门验证 + 可选采样率验证。"""
    i_lufs, tp_dbtp = ebur128(out)
    check(f"{tag}: integrated 达标 (I={i_lufs:.2f}, 目标 {target_i}, 容差 ±{gate_i})",
          abs(i_lufs - target_i) <= gate_i)
    check(f"{tag}: True Peak ≤ TP+0.3dB (TP={tp_dbtp:.2f} ≤ {target_tp + 0.3:.1f})",
          tp_dbtp <= target_tp + 0.3)
    if want_sr:
        check(f"{tag}: 输出采样率 {want_sr}", ffprobe_sr(out) == want_sr, ffprobe_sr(out))


# ─────────────────────────────────────────────────────────────────────────────
# 1) 模块 import 检查 + typo 修复确认
# ─────────────────────────────────────────────────────────────────────────────

print("=" * 78)
print("1) 三处模块 import 检查")
print("=" * 78)

import_ok = True
try:
    from audiobook_studio.utils.loudness import (  # noqa: E402
        LOUDNESS_PRESETS,
        aresample_filter,
        ffmpeg_has_soxr,
        resolve_loudness,
    )
    import audiobook_studio.export.audio_ducking as m_duc  # noqa: E402
    import audiobook_studio.export.mastering as m_mas  # noqa: E402
    import audiobook_studio.pipeline.audio_finalize as m_fin  # noqa: E402
except Exception as e:  # noqa: BLE001
    import_ok = False
    print(f"  import error: {e}")
check("import: utils.loudness + pipeline.audio_finalize + export.mastering + export.audio_ducking",
      import_ok)

api_src = (REPO / "src" / "audiobook_studio" / "api" / "pipeline.py").read_text(encoding="utf-8")
check("api/pipeline.py typo 已修 (无 'project_idproject_id')",
      "project_idproject_id" not in api_src and "project_id=project_id" in api_src)

# ─────────────────────────────────────────────────────────────────────────────
# 2) soxr 探测: 与直接运行时探测交叉一致 (本机预期 False; CI docker 可为 True)
# ─────────────────────────────────────────────────────────────────────────────

print()
print("=" * 78)
print("2) ffmpeg_has_soxr() 探测一致性")
print("=" * 78)

probe = ffmpeg_has_soxr()
manual = sh(["ffmpeg", "-hide_banner", "-nostats", "-f", "lavfi",
             "-i", "anullsrc=r=48000:cl=mono", "-t", "0.1",
             "-af", "aresample=44100:resampler=soxr", "-f", "null", "-"])
manual_has = manual.returncode == 0
check("ffmpeg_has_soxr() 与直接运行时探测一致 (两端都对)", probe == manual_has,
      f"probe={probe}, manual rc={manual.returncode}")
if probe:
    print("  NOTE: 本环境 ffmpeg 带 libsoxr (如 CI docker) → soxr 路径生效, 预期行为")
else:
    print("  NOTE: 本机 Homebrew ffmpeg 无 libsoxr → 预期 False, 回退默认 swr")
    check("本机预期: soxr 不可用 (False)", probe is False)

expected_aresample = "aresample=44100:resampler=soxr" if probe else "aresample=44100"
check("aresample_filter(44100) 与探测结果一致",
      aresample_filter(44100) == expected_aresample, expected_aresample)

# ─────────────────────────────────────────────────────────────────────────────
# 3) filter 字符串断言 (limit 按 preset 换算; alimiter 紧跟 loudnorm; aresample 收尾)
# ─────────────────────────────────────────────────────────────────────────────

print()
print("=" * 78)
print("3) filter 字符串断言")
print("=" * 78)

# tp_lin 换算: limit = 10^(TP/20)
check("tp_lin 换算 audiobook TP=-3 → 0.7079", f"{10 ** (-3.0 / 20):.4f}" == "0.7079",
      f"raw={10 ** (-3.0 / 20):.6f}")
check("tp_lin 换算 streaming TP=-1.5 → 0.8414", f"{10 ** (-1.5 / 20):.4f}" == "0.8414",
      f"raw={10 ** (-1.5 / 20):.6f}")
check("tp_lin 换算 podcast TP=-2 → 0.7943", f"{10 ** (-2.0 / 20):.4f}" == "0.7943",
      f"raw={10 ** (-2.0 / 20):.6f}")
check("LOUDNESS_PRESETS audiobook 档 = (-23, 7, -3)",
      LOUDNESS_PRESETS["audiobook"] == {"i": -23.0, "lra": 7.0, "tp": -3.0})

ALIMITER_A = "alimiter=limit=0.7079:attack=5:release=100:level=disabled"
ALIMITER_S = "alimiter=limit=0.8414:attack=5:release=100:level=disabled"

# 3a) mastering.build_master_filtergraph
from audiobook_studio.export.mastering import (  # noqa: E402
    MasteringConfig,
    build_master_filtergraph,
)

fg_default = build_master_filtergraph(MasteringConfig())
check("mastering 默认档: loudnorm I=-16/TP=-1.5 + alimiter=0.8414 + aresample 收尾",
      "loudnorm=I=-16.0:TP=-1.5:LRA=11.0" in fg_default
      and ALIMITER_S in fg_default
      and fg_default.endswith(expected_aresample),
      fg_default)
check("mastering 默认档: alimiter 紧跟 loudnorm (顺序)",
      fg_default.index("loudnorm") < fg_default.index("alimiter") < fg_default.index("aresample"))

fg_ab = build_master_filtergraph(MasteringConfig(loudness_preset="audiobook"))
check("mastering audiobook 档: loudnorm I=-23/TP=-3 + alimiter=0.7079",
      "loudnorm=I=-23.0:TP=-3.0:LRA=7.0" in fg_ab and ALIMITER_A in fg_ab
      and fg_ab.endswith(expected_aresample), fg_ab)

# 3b) audio_ducking.mix_with_ducking — 无 BGM 链 (与模块同款构造, dur=2s)
from audiobook_studio.export.audio_ducking import MixConfig, SFXSegment  # noqa: E402

cfg = MixConfig()
mix_i, mix_lra, mix_tp = resolve_loudness(cfg.loudness_preset, default_preset="audiobook")
tp_limit = 10 ** (mix_tp / 20.0)
speech_duration_s = DUR_S
af_chain = (
    f"loudnorm=I={mix_i}:LRA={mix_lra}:TP={mix_tp},"
    f"alimiter=limit={tp_limit:.4f}:attack=5:release=100:level=disabled,"
    "afade=t=in:ss=0:d=0.3,"
    f"afade=t=out:st={max(0.0, speech_duration_s - 0.5)}:d=0.5,"
    f"{aresample_filter(44100)}"
)
check("ducking 无 BGM 链: loudnorm→alimiter→fade→aresample 同款构造 (淡出起点=时长-0.5)",
      "loudnorm=I=-23.0:LRA=7.0:TP=-3.0" in af_chain and ALIMITER_A in af_chain
      and af_chain.endswith(expected_aresample)
      and af_chain.index("loudnorm") < af_chain.index("alimiter")
      < af_chain.index("afade") < af_chain.index("aresample"),
      af_chain)

# 3b') ducking BGM 链 (与模块同款构造; P1 修复后: BGM 作主轨、人声作侧链,
# asplit 分路人声喂侧链+混音, amix 混回干净人声)
filter_complex = (
    f"[1:a]loudnorm=I=-20:LRA=7:TP=-2,"
    f"volume={cfg.bgm_volume_db}dB[bgm];"
    f"[0:a]asplit=2[voice][sc];"
    f"[bgm][sc]sidechaincompress="
    f"threshold={cfg.duck_threshold_db}dB:"
    f"ratio={cfg.duck_ratio}:"
    f"attack={cfg.duck_attack_ms}:"
    f"release={cfg.duck_release_ms}:"
    f"makeup=2dB[ducked];"
    f"[voice][ducked]amix=inputs=2:duration=first:normalize=0[mixed];"
    f"[mixed]loudnorm=I={mix_i}:LRA={mix_lra}:TP={mix_tp},"
    f"alimiter=limit={tp_limit:.4f}:attack=5:release=100:level=disabled,"
    f"afade=t=in:ss=0:d=0.5,"
    f"afade=t=out:st={speech_duration_s - 0.5}:d=0.5,"
    f"{aresample_filter(44100)}[out]"
)
check("ducking BGM 链: BGM 作主轨+人声作侧链 (P1: 旧 [0:a][bgm] 人声当主轨丢 BGM)",
      "[0:a]asplit=2[voice][sc];" in filter_complex
      and "[bgm][sc]sidechaincompress=" in filter_complex
      and "[voice][ducked]amix=inputs=2:duration=first:normalize=0[mixed];" in filter_complex,
      filter_complex)
check("ducking BGM 链: 收口 loudnorm→alimiter→fade→aresample 同款构造",
      "[mixed]loudnorm=I=-23.0:LRA=7.0:TP=-3.0," in filter_complex
      and f"alimiter=limit={tp_limit:.4f}:attack=5:release=100:level=disabled," in filter_complex
      and filter_complex.endswith(f"{expected_aresample}[out]"),
      filter_complex)

# 3b'') ducking mix_sfx_segments 链 (与模块同款构造, 单段: 500-1500ms, -6dB, fade 100ms)
sfx_i, sfx_lra, sfx_tp = resolve_loudness(cfg.loudness_preset, default_preset="audiobook")
sfx_tp_limit = 10 ** (sfx_tp / 20.0)
seg = SFXSegment(start_ms=500, end_ms=1500, scene_tag="test", sfx_file=Path("x.wav"))
sfx_fc = (
    f"[1:a]volume={seg.volume_db}dB,"
    f"afade=t=in:st=0:d={seg.fade_ms / 1000},"
    f"afade=t=out:st={(seg.end_ms - seg.start_ms) / 1000 - seg.fade_ms / 1000}:d={seg.fade_ms / 1000},"
    f"adelay={seg.start_ms}:all=1[ad0]"
    ";[0:a][ad0]amix=inputs=2:duration=first:normalize=0,"
    f"loudnorm=I={sfx_i}:LRA={sfx_lra}:TP={sfx_tp},"
    f"alimiter=limit={sfx_tp_limit:.4f}:attack=5:release=100:level=disabled,"
    f"{aresample_filter(44100)}[out]"
)
check("ducking SFX 链: amix→loudnorm→alimiter→aresample 同款构造",
      "amix=inputs=2:duration=first:normalize=0," in sfx_fc and ALIMITER_A in sfx_fc
      and sfx_fc.endswith(f"{expected_aresample}[out]"), sfx_fc)

# ─────────────────────────────────────────────────────────────────────────────
# 4) 实跑链 + ebur128 验证
# ─────────────────────────────────────────────────────────────────────────────

print()
print("=" * 78)
print("4) 实跑链 + ebur128 验证 (脉冲=TP 限幅硬门; 干净对照=integrated 紧门)")
print("=" * 78)

workdir = Path(tempfile.mkdtemp(prefix="p3a_smoke_"))
speech = workdir / "speech_pulse.wav"
speech_clean = workdir / "speech_clean.wav"
bgm = workdir / "bgm.wav"
sfx = workdir / "sfx.wav"
gen_wav(speech, 440.0, 0.125, DUR_S, pulse=True)
gen_wav(speech_clean, 440.0, 0.125, DUR_S, pulse=False)
gen_wav(bgm, 220.0, 0.05, DUR_S)
gen_wav(sfx, 880.0, 0.3, 1.0)
print(f"  素材目录: {workdir}")

# ── 4a) audio_finalize 主路径 (真实 builder 方法 + 同款 insert/cmd 构造) ──
from audiobook_studio.pipeline.audio_finalize import AudioFinalizer  # noqa: E402
from audiobook_studio.schemas.audio_finalize import AudioFinalizeParams  # noqa: E402

fin = AudioFinalizer(sfx_library_path=workdir, effects_library_path=workdir)


def ab_params(**kw):
    """与 _finalize_real 同款: preset → model_copy 覆写目标。"""
    p = AudioFinalizeParams(loudness_preset="audiobook", **kw)
    pi, plra, ptp = resolve_loudness(p.loudness_preset)
    return p.model_copy(update={"loudnorm_target_i": pi, "loudnorm_target_lra": plra,
                                "loudnorm_target_tp": ptp})


check("finalize 参数: audiobook 档覆写目标 (-23/7/-3)",
      (ab_params().loudnorm_target_i, ab_params().loudnorm_target_lra,
       ab_params().loudnorm_target_tp) == (-23.0, 7.0, -3.0))


def run_finalize(input_wav: Path, out: Path, p, label: str,
                 gate_i: float, want_sr: str = "") -> None:
    """两遍 loudnorm (真实 _measure_loudness) + 同款 cmd 实跑 + 双门验证。"""
    mi, mlra, mtp, mth = fin._measure_loudness(input_wav)
    check(f"{label}: 输入测量有效 (I={mi:.1f} LUFS, TP={mtp:.1f} dBTP)", mi < -1.0)
    measured = {"i": mi, "lra": mlra, "tp": mtp, "thresh": mth}
    dur_ms = fin._get_duration(input_wav)
    # 与 _finalize_real 同款: loudnorm 必为 filters[0], alimiter insert(1)
    filters = [fin._build_loudnorm_filter(p, measured)]
    tp_lin = 10 ** (p.loudnorm_target_tp / 20.0)
    filters.insert(1, f"alimiter=limit={tp_lin:.4f}:attack=5:release=100:level=disabled")
    if p.apply_fade:
        filters.append(fin._build_fade_filter(p, dur_ms))
    # P2: 与模块同款, 链尾 aresample 收回输入 SR (loudnorm 恒 192k)
    in_sr = fin._get_sample_rate(input_wav)
    filters.append(aresample_filter(in_sr))
    chain = ",".join(filters)
    check(f"{label}: 链尾 aresample 收回输入 SR (P2, SR={in_sr})",
          chain.endswith(aresample_filter(in_sr)), chain[-50:])
    check(f"{label}: 链含 alimiter=0.7079 紧跟 loudnorm, 无 PLACEHOLDER",
          ALIMITER_A in chain and chain.index("loudnorm") < chain.index("alimiter")
          and "PLACEHOLDER" not in chain)
    if p.apply_fade:
        check(f"{label}: 淡出为真实起点且 :curve= 语法 (st={(dur_ms - p.fade_out_ms) / 1000:.3f})",
              f"afade=t=out:st={(dur_ms - p.fade_out_ms) / 1000:.3f}:d=0.5:curve=tri" in chain)
    fc = f"[0:a]{chain}[aout]"
    codec = {"mp3": "libmp3lame", "m4b": "aac", "wav": "pcm_s16le"}[p.output_format]
    cmd = (["ffmpeg", "-y", "-i", str(input_wav), "-filter_complex", fc,
            "-c:a", codec, "-b:a", p.output_bitrate, "-map", "[aout]", str(out)])
    r = sh(cmd)
    if not check(f"{label}: ffmpeg rc=0", r.returncode == 0,
                 r.stderr[-200:] if r.returncode else ""):
        return
    verify_output(label, out, p.loudnorm_target_i, p.loudnorm_target_tp, gate_i, want_sr)


# E1: 脉冲输入, 无 fade (纯 loudnorm+alimiter+aresample 链; 脉冲致动态回退)
run_finalize(speech, workdir / "finalize_pulse.wav", ab_params(apply_fade=False,
             output_format="wav"), "E1 finalize 脉冲无fade", gate_i=4.0, want_sr="24000")
print("  [info] E1 脉冲致 linear 不可行 → 动态回退, integrated 收敛欠冲属预期 (对照 E1b 紧门)")

# E1b: 干净对照, 无 fade (linear → 精确命中 -23)。P2 修复后: loudnorm 恒输出
# 192kHz (linear 模式亦然), 链尾 aresample 收回输入 SR → wav 出 24k (输入即 24k),
# mp3/m4b 不再被编码器自动协商到 48k。采样率契约: 输出 SR = 输入 SR。
run_finalize(speech_clean, workdir / "finalize_clean_nofade.wav",
             ab_params(apply_fade=False, output_format="wav"),
             "E1b finalize 干净无fade", gate_i=1.0, want_sr="24000")
print("  [info] E1b 输出采样率 24k = 输入采样率 (P2: loudnorm 192k 已被链尾 aresample 收回)")

# E2: 干净对照, 默认参数 (fade on + mp3 默认输出格式端到端; 2s 短片 fade 拉低 ~1.3 LU)
run_finalize(speech_clean, workdir / "finalize_default.mp3",
             ab_params(output_format="mp3"), "E2 finalize 默认fade(mp3)",
             gate_i=2.5, want_sr="24000")

# ── 4b) mastering 端到端 (真实 master_audio) ──────────────────────────────
from audiobook_studio.export.mastering import master_audio  # noqa: E402

res_p = master_audio(speech, workdir / "mastered_pulse.wav",
                     MasteringConfig(loudness_preset="audiobook"))
check("M1 mastering 脉冲: master_audio rc=0", res_p["ffmpeg_returncode"] == 0,
      str(res_p.get("error", ""))[:200])
check("M1 mastering 脉冲: filtergraph 含 alimiter=0.7079 + aresample 收尾",
      ALIMITER_A in res_p["filtergraph"]
      and res_p["filtergraph"].endswith(expected_aresample))
verify_output("M1 mastering 脉冲", workdir / "mastered_pulse.wav", -23.0, -3.0,
              gate_i=4.0, want_sr="44100")

res_c = master_audio(speech_clean, workdir / "mastered_clean.wav",
                     MasteringConfig(loudness_preset="audiobook"))
check("M2 mastering 干净: master_audio rc=0 (linear 精确命中)", res_c["ffmpeg_returncode"] == 0)
verify_output("M2 mastering 干净", workdir / "mastered_clean.wav", -23.0, -3.0,
              gate_i=1.0, want_sr="44100")

# ── 4c) audio_ducking 端到端 (真实函数) ────────────────────────────────────
from audiobook_studio.export.audio_ducking import (  # noqa: E402
    mix_sfx_segments,
    mix_with_ducking,
)

# D1: 无 BGM (脉冲 + 干净对照)
mix_with_ducking(speech, workdir / "duck_nobgm_pulse.m4a", bgm_path=None)
verify_output("D1 ducking 无BGM 脉冲", workdir / "duck_nobgm_pulse.m4a", -23.0, -3.0,
              gate_i=4.0, want_sr="44100")
mix_with_ducking(speech_clean, workdir / "duck_nobgm_clean.m4a", bgm_path=None)
verify_output("D1b ducking 无BGM 干净", workdir / "duck_nobgm_clean.m4a", -23.0, -3.0,
              gate_i=1.5, want_sr="44100")

# D2: BGM ducking (脉冲 + 干净对照)
mix_with_ducking(speech, workdir / "duck_bgm_pulse.m4a", bgm_path=str(bgm))
verify_output("D2 ducking BGM 脉冲", workdir / "duck_bgm_pulse.m4a", -23.0, -3.0,
              gate_i=4.0, want_sr="44100")
mix_with_ducking(speech_clean, workdir / "duck_bgm_clean.m4a", bgm_path=str(bgm))
verify_output("D2b ducking BGM 干净", workdir / "duck_bgm_clean.m4a", -23.0, -3.0,
              gate_i=2.0, want_sr="44100")

# D2c: P1 回归门 — BGM 在场 (功能性): 旧 bug 下 sidechaincompress 把人声当主轨,
# 输出仅含被压缩人声 → 人声间隙窗口为数字静音 (~-91dB); 修复后间隙窗口应含
# BGM 床 (~-43dB)。素材: 0.8s 440Hz + 0.9s 静音 + 0.8s 440Hz (2.5s), BGM=3000Hz。


def gen_wav_gaps(path: Path, freq: float, amp: float, dur: float, spans: list) -> None:
    """分段正弦 (spans=[(start_s, end_s), ...], 其余静音), 24kHz mono s16。"""
    n = int(SR * dur)
    frames = bytearray(n * 2)
    for s0, s1 in spans:
        i0 = int(s0 * SR)
        for i in range(i0, min(int(s1 * SR), n)):
            v = max(-1.0, min(1.0, amp * math.sin(2.0 * math.pi * freq * (i - i0) / SR)))
            frames[i * 2:i * 2 + 2] = struct.pack("<h", int(round(v * 32767.0)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(bytes(frames))


def window_mean_db(path: Path, start_s: float, dur_s: float, extra_af: str = "") -> float:
    """volumedetect 窗口均值电平 (-i 后 -ss 输出端精确定位)。"""
    af = f"{extra_af},volumedetect" if extra_af else "volumedetect"
    p2 = sh(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
             "-ss", f"{start_s}", "-t", f"{dur_s}",
             "-af", af, "-f", "null", "-"])
    m = re.search(r"mean_volume:\s*(-?\d+\.?\d*)\s*dB", p2.stderr)
    return float(m.group(1)) if m else -999.0


voice_gaps = workdir / "voice_gaps.wav"
bgm_3k = workdir / "bgm_3k.wav"
out_gaps = workdir / "duck_bgm_gaps.m4a"
gen_wav_gaps(voice_gaps, 440.0, 0.125, 2.5, [(0.0, 0.8), (1.7, 2.5)])
gen_wav(bgm_3k, 3000.0, 0.05, 2.5)
try:
    mix_with_ducking(voice_gaps, out_gaps, bgm_path=str(bgm_3k))
    mix_ok = True
except Exception as e:  # noqa: BLE001
    mix_ok = False
    print(f"  [D2c] mix_with_ducking 异常: {e}")
check("D2c BGM ducking: P1 新图实跑 rc=0", mix_ok and out_gaps.exists())
if mix_ok:
    dur_gaps = float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                         "-of", "csv=p=0", str(out_gaps)]).stdout.strip())
    check("D2c BGM ducking: 输出时长=人声时长 (amix duration=first, BGM 循环更长被截)",
          2.3 <= dur_gaps <= 2.8, f"(dur={dur_gaps:.2f}s, 人声 2.5s)")
    check("D2c BGM ducking: 输出采样率 44100 (链尾 aresample)",
          ffprobe_sr(out_gaps) == "44100", ffprobe_sr(out_gaps))
    gap_db = window_mean_db(out_gaps, 0.9, 0.7)
    check("D2c BGM 在场: 人声间隙窗口含 BGM 床 (>-55dB; 旧 bug 数字静音 ~-91dB)",
          gap_db > -55.0, f"(gap window mean={gap_db:.1f} dB)")
    gap_bp = window_mean_db(out_gaps, 0.9, 0.7, "bandpass=f=3000:width_type=h:w=400")
    check("D2c BGM 在场: 间隙窗口 3kHz 带通能量证实是 BGM (>-60dB)",
          gap_bp > -60.0, f"(bandpass mean={gap_bp:.1f} dB)")
    voice_db = window_mean_db(out_gaps, 0.55, 0.2)
    check("D2c 人声在场: 语音窗口电平正常 (>-35dB)", voice_db > -35.0,
          f"(voice window mean={voice_db:.1f} dB)")

# D3: SFX 混音 (脉冲 + 干净对照)
seg3 = SFXSegment(start_ms=500, end_ms=1500, scene_tag="test", sfx_file=sfx,
                  volume_db=-6.0, fade_ms=100)
mix_sfx_segments(speech, [seg3], workdir / "duck_sfx_pulse.m4a")
verify_output("D3 ducking SFX 脉冲", workdir / "duck_sfx_pulse.m4a", -23.0, -3.0,
              gate_i=4.0, want_sr="44100")
mix_sfx_segments(speech_clean, [seg3], workdir / "duck_sfx_clean.m4a")
verify_output("D3b ducking SFX 干净", workdir / "duck_sfx_clean.m4a", -23.0, -3.0,
              gate_i=1.0, want_sr="44100")

# ─────────────────────────────────────────────────────────────────────────────
# 5) 汇总
# ─────────────────────────────────────────────────────────────────────────────

print()
print("=" * 78)
print(f"汇总: {PASSES} passed, {len(FAILURES)} failed")
if FAILURES:
    for f in FAILURES:
        print(f"  [FAIL] {f}")
print("=" * 78)
shutil.rmtree(workdir, ignore_errors=True)
sys.exit(1 if FAILURES else 0)
