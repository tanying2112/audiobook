"""B3 端到端验证：用真实免费资源跑 TTS -> BGM 混音 -> MP4 封装。

仅使用免费资源（无付费 API / 无 GPU）：
- TTS：Edge-TTS（微软免费 TTS 服务，需网络）
- BGM：本地 ffmpeg 生成轻柔正弦垫底（lavfi，无模型下载 / 无网络）
- 混音 / 封装：项目自带 ``src.audiobook_studio.pipeline.multimodal``（ffmpeg）

产出：可播放的 MP4（音频轨 + 黑场画布 + 软字幕轨），写入 ``output/e2e_bgm_demo.mp4``。

用法：
    python scripts/run_e2e_bgm_mp4.py [--text "..."] [--voice zh-CN-XiaoxiaoNeural]
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the project root importable so ``src.audiobook_studio`` resolves
# whether the script is run directly or as a module.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse
import asyncio
import subprocess
import tempfile
import textwrap
from pathlib import Path

import edge_tts

from src.audiobook_studio.pipeline.multimodal import (
    mix_with_bg_music,
    mux_audio_subtitle_to_mp4,
)


DEFAULT_TEXT = (
    "欢迎使用有声书工作室。这是一段用免费资源生成的示例音频，"
    "包含背景音乐混音与字幕封装，全程无需付费 API 或显卡。"
)


async def _tts(text: str, voice: str, out: Path) -> None:
    communicator = edge_tts.Communicate(text, voice)
    await communicator.save(str(out))


def _gen_bgm_tone(out: Path, duration: float = 20.0) -> None:
    """Free, local BGM bed: a soft sine pad via ffmpeg lavfi (no network)."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "sine=frequency=220:sample_rate=24000",
            "-t", str(duration), "-af", "volume=0.05",
            "-c:a", "libmp3lame", "-q:a", "6", str(out),
        ],
        check=True, capture_output=True, text=True,
    )


def _write_srt(out: Path, text: str) -> None:
    out.write_text(
        textwrap.dedent(
            """\
            1
            00:00:00,000 --> 00:00:30,000
            {text}
            """
        ).format(text=text)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--voice", default="zh-CN-XiaoxiaoNeural")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        tts_mp3 = tmp / "tts.mp3"
        bgm_mp3 = tmp / "bgm.mp3"
        mixed = tmp / "mixed.mp3"
        srt = tmp / "sub.srt"
        mp4 = tmp / "out.mp4"

        asyncio.run(_tts(args.text, args.voice, tts_mp3))
        _gen_bgm_tone(bgm_mp3)
        mix_with_bg_music(tts_mp3, bgm_mp3, mixed, bgm_gain_db=-22.0)
        _write_srt(srt, args.text)
        mux_audio_subtitle_to_mp4(mixed, srt, mp4)

        product = Path("output/e2e_bgm_demo.mp4")
        product.parent.mkdir(parents=True, exist_ok=True)
        product.write_bytes(mp4.read_bytes())

        probe = subprocess.run(
            ["ffprobe", "-v", "error",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(product)],
            capture_output=True, text=True, check=True,
        )
        streams = [s for s in probe.stdout.splitlines() if s]
        print("STREAMS:", ",".join(streams))
        print("MP4_SIZE_BYTES:", product.stat().st_size)
        assert "audio" in streams, "MP4 缺少音频轨"
        assert "video" in streams, "MP4 缺少视频轨"
        print(f"B3_OK: 可播放 MP4 -> {product}")


if __name__ == "__main__":
    main()
