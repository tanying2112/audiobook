"""B4 真实跨语言验证：用免费 LLM 翻译 (en/ja/ko -> zh) + 真实免费 TTS 生成外语音频。

仅使用免费资源（无付费 API）：
- 翻译：项目 LLM 路由器 ``create_router().call(stage="translate", ...)``
  （底层走免费 LLM API 轮转池 / QuotaRegistry，需网络）
- TTS：Edge-TTS（微软免费 TTS 服务，需网络），分别用对应外语音色生成外语音频，
  并用中文音色生成译文音频以展示跨语言对照。

产出：``output/b4_{lang}_source.mp3``（外语音频）与 ``output/b4_{lang}_zh.mp3``（译文音频）。

用法：
    python scripts/run_cross_language_b4.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Make the project root importable so ``src.audiobook_studio`` resolves.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Force real (non-mock) LLM so the free-LLM translation actually runs.
os.environ.pop("MOCK_LLM", None)

import edge_tts
from pydantic import BaseModel

from src.audiobook_studio.llm.router import create_router


class TranslationResult(BaseModel):
    translated_text: str


# 外语样本文本 + 对应 Edge-TTS 外语音色
SAMPLES = {
    "en": (
        "en-US-AriaNeural",
        "Hello, welcome to the audiobook studio. This is a free cross-lingual demo.",
    ),
    "ja": (
        "ja-JP-NanamiNeural",
        "こんにちは、オーディオブックスタジオへようこそ。無料の多言語デモです。",
    ),
    "ko": (
        "ko-KR-SunHiNeural",
        "안녕하세요, 오디오북 스튜디오에 오신 것을 환영합니다. 무료 다국어 데모입니다.",
    ),
}

ZH_VOICE = "zh-CN-XiaoxiaoNeural"


async def _tts(text: str, voice: str, out: Path) -> None:
    await edge_tts.Communicate(text, voice).save(str(out))


def main() -> None:
    router = create_router()
    out_dir = Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)

    for lang, (voice, source) in SAMPLES.items():
        result = router.call(
            stage="translate",
            response_model=TranslationResult,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert translator. Translate accurately to "
                    "Simplified Chinese (zh-CN). Output only the translation, no notes.",
                },
                {
                    "role": "user",
                    "content": f"Translate the following text from {lang} to zh-CN. Text: {source}",
                },
            ],
        )
        zh = result.output.translated_text.strip()

        foreign_audio = out_dir / f"b4_{lang}_source.mp3"
        zh_audio = out_dir / f"b4_{lang}_zh.mp3"
        asyncio.run(_tts(source, voice, foreign_audio))
        asyncio.run(_tts(zh, ZH_VOICE, zh_audio))

        print(
            f"[{lang}] {source}\n"
            f"   -> {zh}\n"
            f"   foreign_audio={foreign_audio.name} ({foreign_audio.stat().st_size}B) "
            f"zh_audio={zh_audio.name} ({zh_audio.stat().st_size}B)"
        )
        assert foreign_audio.stat().st_size > 0, "外语音频为空"
        assert zh_audio.stat().st_size > 0, "译文音频为空"

    print("B4_OK: 免费 LLM 跨语言翻译 (en/ja/ko->zh) + 外语音频生成成功")


if __name__ == "__main__":
    main()
