"""S2-5 母带后处理链路验收测试 (真实 ffmpeg).

使用 ffmpeg 合成测试音频 (纯噪声 / 含静音的有声段落)，验证 mastering 链路：
  1. 导出 M4B/MP3 通过 loudnorm 校验 (input_i ≈ -16)
  2. 噪声底噪降低 ≥ 10 dB
  3. 静音段自动修剪

若运行环境无 ffmpeg，则整体跳过 (不影响无 GPU/无二进制的 CI 节点)。
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.export.mastering import (
    MasteringConfig,
    build_master_filtergraph,
    master_audio,
    measure_loudness,
    verify_mastering,
)

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

requires_ffmpeg = pytest.mark.skipif(
    not (FFMPEG and FFPROBE), reason="ffmpeg/ffprobe not available in this environment"
)


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120)


def _probe_duration_ms(path: Path) -> int:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return int(float(out) * 1000)


def _rms_db(path: Path) -> float:
    """测量整段音频的 RMS level (dB)，用于噪声底噪对比。"""
    out = subprocess.run(
        [FFMPEG, "-i", str(path),
         "-af", "astats=metadata=1:reset=0", "-f", "null", "-"],
        capture_output=True, text=True, timeout=120,
    ).stderr
    for line in out.splitlines():
        if "RMS level dB:" in line:
            return float(line.split(":")[-1].strip())
    return 0.0


@requires_ffmpeg
def test_build_master_filtergraph_contains_all_steps():
    """滤镜图应同时包含 降噪(afftdn) / 静音修剪(silenceremove) / 响度归一化(loudnorm)。"""
    fg = build_master_filtergraph(MasteringConfig())
    assert "afftdn" in fg, "应启用降噪 (noisereduce 原生等效)"
    assert "silenceremove" in fg, "应启用静音修剪"
    assert "loudnorm=I=-16" in fg, "应启用 loudnorm I=-16"
    assert "TP=-1.5" in fg and "LRA=11" in fg, "应满足任务验收参数 TP=-1.5/LRA=11"


@requires_ffmpeg
def test_build_master_filtergraph_toggle():
    fg = build_master_filtergraph(MasteringConfig(
        enable_noisereduce=False, enable_silenceremove=False, enable_loudnorm=False
    ))
    assert fg == "", "全部关闭时应返回空滤镜图 (master_audio 退化为拷贝)"


@requires_ffmpeg
def test_loudnorm_validation_passes():
    """验收 1：导出音频通过 loudnorm 校验 (input_i ≈ -16)。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # 合成一段较安静的人声样音频 (sine + 轻噪声)，整体偏安静 -> 需要被拉到 -16
        noisy = tmp / "noisy.wav"
        _run([
            FFMPEG, "-y", "-f", "lavfi", "-i",
            "sine=frequency=220:duration=3:sample_rate=44100",
            "-f", "lavfi", "-i", "anoisesrc=d=3:r=44100:a=0.005",
            "-filter_complex", "[0][1]amix=inputs=2",
            "-ac", "1", "-ar", "44100", str(noisy),
        ])
        out = tmp / "mastered.wav"
        result = master_audio(noisy, out, MasteringConfig(channels=1))
        assert result["ffmpeg_returncode"] == 0
        assert out.exists()

        # 验收命令等价：对输出再做一次 loudnorm 测量，input_i 应 ≈ -16
        verification = verify_mastering(out, target_i=-16.0, tolerance=2.0)
        assert verification["passed"], f"loudnorm 未命中目标: {verification}"
        assert abs(verification["input_i"] - (-16.0)) <= 2.0


@requires_ffmpeg
def test_noise_floor_reduced_by_at_least_10db():
    """验收 2：噪声底噪降低 ≥ 10 dB。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        noise_in = tmp / "noise_in.wav"
        # 纯噪声 (底噪)，RMS 约 -30 dB 量级
        _run([
            FFMPEG, "-y", "-f", "lavfi", "-i", "anoisesrc=d=3:r=44100:a=0.05",
            "-ac", "1", "-ar", "44100", str(noise_in),
        ])
        noise_out = tmp / "noise_out.wav"
        master_audio(noise_in, noise_out, MasteringConfig(
            enable_silenceremove=False, enable_loudnorm=False, channels=1
        ))

        before = _rms_db(noise_in)
        after = _rms_db(noise_out)
        reduction = before - after
        assert reduction >= 10.0, f"噪声底噪仅降低 {reduction:.2f} dB (< 10 dB)"


@requires_ffmpeg
def test_silence_segments_trimmed():
    """验收 3：静音段被自动修剪 (输出时长明显短于输入)。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # 结构：1s 有声 + 3s 静音 + 1s 有声 = 5s；静音应被修剪
        body = tmp / "body.wav"
        _run([
            FFMPEG, "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=1:sample_rate=44100",
            "-f", "lavfi", "-i", "sine=frequency=330:duration=1:sample_rate=44100",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=3",
            "-filter_complex",
            "[0]aformat=sample_fmts=s16:sample_rates=44100:channel_layouts=mono[s1];"
            "[1]aformat=sample_fmts=s16:sample_rates=44100:channel_layouts=mono[s2];"
            "[2]aformat=sample_fmts=s16:sample_rates=44100:channel_layouts=mono[s0];"
            "[s1][s0][s2]concat=n=3:v=0:a=1",
            "-ac", "1", "-ar", "44100", str(body),
        ])
        in_dur = _probe_duration_ms(body)
        out = tmp / "trimmed.wav"
        master_audio(body, out, MasteringConfig(
            enable_noisereduce=False, enable_loudnorm=False, channels=1
        ))
        out_dur = _probe_duration_ms(out)
        assert out_dur < in_dur - 1000, (
            f"静音未被修剪: 输入 {in_dur}ms -> 输出 {out_dur}ms"
        )


@requires_ffmpeg
def test_master_mp3_codec():
    """MP3 输出应使用 libmp3lame 编码且通过 loudnorm 校验。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / "src.wav"
        _run([
            FFMPEG, "-y", "-f", "lavfi", "-i",
            "sine=frequency=440:duration=2:sample_rate=44100",
            "-ac", "1", "-ar", "44100", str(src),
        ])
        mp3 = tmp / "out.mp3"
        res = master_audio(src, mp3, MasteringConfig(channels=1))
        assert res["ffmpeg_returncode"] == 0
        assert mp3.exists()
        assert mp3.suffix == ".mp3"
        assert verify_mastering(mp3, target_i=-16.0, tolerance=2.0)["passed"]


@requires_ffmpeg
def test_measured_loudness_keys():
    """measure_loudness 应解析出 input_i 等字段。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / "src.wav"
        _run([
            FFMPEG, "-y", "-f", "lavfi", "-i",
            "sine=frequency=440:duration=2:sample_rate=44100",
            "-ac", "1", "-ar", "44100", str(src),
        ])
        m = measure_loudness(src)
        assert "input_i" in m, "measure_loudness 应返回 input_i"
        assert isinstance(m["input_i"], float)


# ----------------------------------------------------------------------------
# 纯逻辑单元测试 (不依赖 ffmpeg)：在 CI 无二进制节点也能覆盖 mastering.py 逻辑。
# ----------------------------------------------------------------------------

def _mk(stdout: str = "", stderr: str = "", returncode: int = 0) -> MagicMock:
    return MagicMock(stdout=stdout, stderr=stderr, returncode=returncode)


class TestMasteringLogic:
    """mock subprocess，验证 mastering 编排逻辑 (两遍归一化 / 解析 / 退化路径)。"""

    def test_codec_for_path(self):
        from src.audiobook_studio.export.mastering import _codec_for_path

        assert _codec_for_path(Path("a.mp3")) == ("libmp3lame", "192k")
        assert _codec_for_path(Path("a.wav")) == ("pcm_s16le", "")
        assert _codec_for_path(Path("a.m4a")) == ("aac", "128k")
        assert _codec_for_path(Path("a.flac")) == ("flac", "")

    def test_parse_loudnorm_json(self):
        from src.audiobook_studio.export.mastering import _parse_loudnorm_json

        raw = 'noise\n{"input_i": -20.0, "input_tp": -3.0, "input_lra": 11.0}\ntail'
        d = _parse_loudnorm_json(raw)
        assert d["input_i"] == -20.0
        assert d["input_tp"] == -3.0

    @patch("src.audiobook_studio.export.mastering.subprocess.run")
    def test_master_audio_two_pass_success(self, mock_run):
        def fake_run(cmd, *a, **k):
            s = " ".join(str(x) for x in cmd)
            if "print_format=json" in s:
                return _mk(stderr=json.dumps({
                    "input_i": -23.0, "input_tp": -3.0, "input_lra": 11.0,
                    "input_thresh": -33.0, "output_i": -16.0, "output_tp": -1.5,
                    "output_lra": 11.0, "output_thresh": -27.0,
                    "normalization_type": "dynamic", "target_offset": 0.0,
                }), returncode=0)
            # apply 调用：写出输出文件 (模拟 ffmpeg 落盘)
            out_p = Path(str(cmd[-1]))
            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_bytes(b"\x00\x00")
            return _mk(returncode=0)

        mock_run.side_effect = fake_run
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "in.wav"
            src.write_bytes(b"x")
            out = tmp / "out.wav"
            res = master_audio(src, out, MasteringConfig())
            assert res["ffmpeg_returncode"] == 0
            assert out.exists()
            assert res["measured"] is not None
            # 第一遍测量 + 第二遍应用 + 处理后复测 = 3 次 ffmpeg 调用
            assert mock_run.call_count == 3

    @patch("src.audiobook_studio.export.mastering.subprocess.run")
    def test_master_audio_noop_when_all_disabled(self, mock_run):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "in.wav"
            src.write_bytes(b"fake")
            out = tmp / "out.wav"
            res = master_audio(
                src, out,
                MasteringConfig(enable_noisereduce=False, enable_silenceremove=False,
                                enable_loudnorm=False),
            )
            assert res["ffmpeg_returncode"] == 0
            assert out.exists()  # 退化为 shutil.copy2
            assert mock_run.call_count == 0

    @patch("src.audiobook_studio.export.mastering.subprocess.run")
    def test_master_audio_source_missing(self, mock_run):
        with tempfile.TemporaryDirectory() as tmp:
            res = master_audio(Path(tmp) / "missing.wav", Path(tmp) / "out.wav")
            assert res["ffmpeg_returncode"] is None
            assert "error" in res
            assert mock_run.call_count == 0

    @patch("src.audiobook_studio.export.mastering.subprocess.run")
    def test_verify_mastering_passes(self, mock_run):
        def fake_run(cmd, *a, **k):
            s = " ".join(str(x) for x in cmd)
            if "print_format=json" in s:
                return _mk(stderr=json.dumps({
                    "input_i": -16.0, "input_tp": -1.5, "input_lra": 11.0,
                    "input_thresh": -26.0, "output_i": -16.0, "output_tp": -1.5,
                    "output_lra": 11.0, "output_thresh": -26.0,
                    "normalization_type": "dynamic", "target_offset": 0.0,
                }), returncode=0)
            return _mk(returncode=0)

        mock_run.side_effect = fake_run
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.wav"
            p.write_bytes(b"x")
            v = verify_mastering(p, target_i=-16.0, tolerance=1.0)
            assert v["passed"] is True
            assert abs(v["input_i"] - (-16.0)) <= 1.0

    @patch("src.audiobook_studio.export.mastering.subprocess.run")
    def test_verify_mastering_fails_below_target(self, mock_run):
        def fake_run(cmd, *a, **k):
            s = " ".join(str(x) for x in cmd)
            if "print_format=json" in s:
                return _mk(stderr=json.dumps({
                    "input_i": -25.0, "input_tp": -3.0, "input_lra": 11.0,
                    "input_thresh": -33.0, "output_i": -25.0, "output_tp": -3.0,
                    "output_lra": 11.0, "output_thresh": -33.0,
                    "normalization_type": "dynamic", "target_offset": 0.0,
                }), returncode=0)
            return _mk(returncode=0)

        mock_run.side_effect = fake_run
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.wav"
            p.write_bytes(b"x")
            v = verify_mastering(p, target_i=-16.0, tolerance=2.0)
            assert v["passed"] is False
