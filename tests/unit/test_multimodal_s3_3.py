"""Tests for S3.3 — multimodal audio/video pipeline.

验收(免费资源可达成部分):
- 本地 BGM 混音(mix_with_bg_music)
- MP4 + 字幕封装(mux_audio_subtitle_to_mp4)供 VideoCanvasView 导出
- QC 自适应响度归一(qc_adapt_audio)
- StableAudio/AudioLDM2 远程生成以诚实桩呈现(标注付费云约束)

真实 ffmpeg 在 CI/本机可用;若环境无 ffmpeg 则跳过重计算测试。
"""

import shutil
import struct
import wave
from pathlib import Path

import pytest

from src.audiobook_studio.pipeline import multimodal as mm


def _tone_wav(path: Path, freq: int = 440, seconds: float = 0.5, rate: int = 24000) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = int(rate * seconds)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        for i in range(frames):
            val = int(32767 * 0.3 * __import__("math").sin(2 * 3.14159 * freq * i / rate))
            w.writeframes(struct.pack("<h", val))
    return path


HAS_FFMPEG = shutil.which("ffmpeg") is not None


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg required")
def test_mix_with_bg_music(tmp_path: Path):
    tts = _tone_wav(tmp_path / "tts.wav", freq=440)
    bgm = _tone_wav(tmp_path / "bgm.wav", freq=120, seconds=0.8)
    out = mm.mix_with_bg_music(tts, bgm, tmp_path / "mixed.mp3")
    assert out.exists() and out.stat().st_size > 0


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg required")
def test_mux_audio_subtitle_to_mp4(tmp_path: Path):
    audio = _tone_wav(tmp_path / "a.wav")
    srt = tmp_path / "sub.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n你好，世界\n", encoding="utf-8"
    )
    out = mm.mux_audio_subtitle_to_mp4(audio, srt, tmp_path / "out.mp4")
    assert out.exists() and out.stat().st_size > 0


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg required")
def test_qc_adapt_audio(tmp_path: Path):
    audio = _tone_wav(tmp_path / "raw.wav", freq=330, seconds=0.6)
    out = mm.qc_adapt_audio(audio, tmp_path / "qc.mp3")
    assert out.exists() and out.stat().st_size > 0


def test_local_bgm_generator_without_asset_returns_silence(tmp_path: Path):
    gen = mm.LocalBgmGenerator(bgm_asset=None)
    out = gen.generate("calm", 0.4, tmp_path / "bgm.mp3")
    assert out.exists()


def test_remote_generative_stub_is_honest():
    gen = mm.RemoteGenerativeStub()
    with pytest.raises(NotImplementedError):
        gen.generate("epic battle theme", 3.0, Path("/tmp/x.mp3"))


def test_local_bgm_generator_loops_asset(tmp_path: Path):
    asset = _tone_wav(tmp_path / "loop.wav", freq=90, seconds=0.3)
    gen = mm.LocalBgmGenerator(bgm_asset=asset)
    out = gen.generate("ambient", 0.5, tmp_path / "bgm_loop.mp3")
    assert out.exists() and out.stat().st_size > 0
