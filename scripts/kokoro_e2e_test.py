#!/usr/bin/env python3
"""
Kokoro End-to-End 全链路测试
数据流: 文本解析 → 角色/情绪映射 → 声学参数 → TTS合成 → 音频输出

输入: input/test_story.txt (已标注情绪的 3 章中文脚本)
输出: output/kokoro_e2e_test/ (分段音频 + 拼接完整音频)
"""

import re
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

# --- 配置 ---
MODEL_PATH = "models/kokoro-v1.0.onnx"
VOICES_PATH = "models/voices-v1.0.bin"
INPUT_PATH = "input/test_story.txt"
OUTPUT_DIR = Path("output/kokoro_e2e_test")
SAMPLE_RATE = 24000

# 角色 -> 音色映射
CHARACTER_VOICES = {
    "旁白": "zf_xiaoxiao",
    "陆沉": "zm_yunjian",
    "宋老": "zm_yunxi",
    "顾清雪": "zf_xiaobei",
    "阿杰": "zm_yunyang",
}

# 情绪关键词 -> 语速映射
EMOTION_SPEED = {
    "压低声音": 0.80,
    "极度阴沉": 0.75,
    "沙哑冷笑": 0.78,
    "语速缓慢": 0.72,
    "歇斯底里": 1.30,
    "震惊兼暴怒": 1.25,
    "极度恐慌": 1.40,
    "急促": 1.50,
    "疯狂大笑": 1.20,
    "绝望尖叫": 1.35,
    "咬牙切齿": 0.75,
    "悲伤抽泣": 0.65,
    "咆哮怒吼": 1.15,
    "冷嘲热讽": 1.05,
    "高亢": 1.20,
    "温和低沉": 0.85,
    "轻声叹息": 0.70,
    "意味深长": 0.82,
    "语速放缓": 0.80,
}


def parse_story(filepath: str) -> list[dict]:
    """Parse the test story into (character, emotion, text) segments."""
    segments = []
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]

    for para in paragraphs:
        lines = para.strip().split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("第") and "章" in line:
                segments.append({"type": "chapter_title", "text": line})
                continue

            # Match: "CharacterName："inner text""
            # Quotes: " (U+201C) and " (U+201D) - Chinese curly quotes
            match = re.match("^(.+?)[：:]\s*[“”](.+?)[“”]$", line)
            if match:
                character = match.group(1)
                inner = match.group(2)

                # Parse emotion annotation "(emotion) text"
                em_match = re.match(r"[（(]([^）)]+)[）)](.*)", inner)
                if em_match:
                    emotion = em_match.group(1)
                    text = em_match.group(2)
                else:
                    emotion = "neutral"
                    text = inner

                segments.append(
                    {
                        "type": "character_line",
                        "character": character,
                        "emotion_raw": emotion,
                        "text": text,
                        "voice": CHARACTER_VOICES.get(character, "zf_xiaoxiao"),
                    }
                )
            elif "旁白" in line:
                # Narration
                text = re.split(r"[：:]", line, maxsplit=1)[-1].strip()
                segments.append(
                    {
                        "type": "narration",
                        "character": "旁白",
                        "emotion_raw": "neutral",
                        "text": text,
                        "voice": CHARACTER_VOICES["旁白"],
                    }
                )
            else:
                # Plain narration without prefix
                segments.append(
                    {
                        "type": "narration",
                        "character": "旁白",
                        "emotion_raw": "neutral",
                        "text": line,
                        "voice": CHARACTER_VOICES["旁白"],
                    }
                )
    return segments


def infer_speed(emotion: str) -> float:
    """Infer speech speed from emotion annotation."""
    if not emotion or emotion == "neutral":
        return 1.0
    for keyword, speed in EMOTION_SPEED.items():
        if keyword in emotion:
            return speed
    # Heuristic fallback
    if any(w in emotion for w in ["低", "沉", "慢", "叹息", "悲伤"]):
        return 0.80
    if any(w in emotion for w in ["怒", "吼", "疯狂", "暴怒"]):
        return 1.20
    if any(w in emotion for w in ["恐慌", "急", "尖叫"]):
        return 1.35
    if any(w in emotion for w in ["温和", "轻"]):
        return 0.90
    if any(w in emotion for w in ["冷笑", "嘲"]):
        return 0.85
    return 1.0


def synthesize(kokoro: Kokoro, seg: dict, idx: int, out_dir: Path) -> dict:
    """Synthesize a single segment and save to WAV."""
    text = seg["text"]
    voice = seg["voice"]
    character = seg["character"]
    emotion = seg["emotion_raw"]
    speed = infer_speed(emotion)

    # Split long text into sentences
    if len(text) > 100:
        sentences = re.split(r"([。！？；……，])", text)
        chunks = []
        current = ""
        for s in sentences:
            current += s
            if len(current) > 150 and (s.rstrip() and s.rstrip()[-1] in "。！？"):
                chunks.append(current)
                current = ""
        if current:
            chunks.append(current)
    else:
        chunks = [text]

    # Synthesize each chunk
    audio_parts = []
    for chunk in chunks:
        if not chunk.strip():
            continue
        lang = "en-us" if all(ord(c) < 128 for c in chunk.strip()) else "cmn"
        audio, sr = kokoro.create(chunk, voice=voice, speed=speed, lang=lang)
        audio_parts.append(audio)

    full = np.concatenate(audio_parts) if len(audio_parts) > 1 else audio_parts[0]

    # Save
    fname = f"seg_{idx:03d}_{character}_{voice}.wav"
    fpath = out_dir / fname
    sf.write(str(fpath), full, SAMPLE_RATE)

    return {
        "segment_id": idx,
        "character": character,
        "emotion": emotion,
        "speed": speed,
        "voice": voice,
        "text_preview": text[:60] + ("..." if len(text) > 60 else ""),
        "file": str(fpath),
        "duration_s": len(full) / SAMPLE_RATE,
        "chunks": len(chunks),
    }


def main():
    print("=" * 60)
    print("  Kokoro TTS End-to-End Test")
    print("  Text Parse -> Emotion Mapping -> TTS -> Audio")
    print("=" * 60)

    # Check files
    for path, label in [(MODEL_PATH, "Model"), (VOICES_PATH, "Voices"), (INPUT_PATH, "Input")]:
        p = Path(path)
        if not p.exists():
            print(f"ERROR: {label} not found: {path}")
            return 1
        print(f"  {label}: {path} ({p.stat().st_size / 1e6:.0f} MB)")

    # Init Kokoro
    print("\n[1] Initializing Kokoro ONNX engine...")
    start = time.time()
    kokoro = Kokoro(model_path=MODEL_PATH, voices_path=VOICES_PATH)
    voices = kokoro.get_voices()
    print(f"    Loaded in {time.time() - start:.1f}s, {len(voices)} voices available")

    # Parse input
    print("\n[2] Parsing test story...")
    all_segments = parse_story(INPUT_PATH)
    speech_segments = [s for s in all_segments if s["type"] != "chapter_title"]
    print(f"    {len(all_segments)} segments ({len(speech_segments)} speech)")

    # Show summary
    print(f"\n    {'#':>3}  {'Character':<8} {'Emotion':<16} {'Voice':<12} Text preview")
    print(f"    {'-'*3}  {'-'*8} {'-'*16} {'-'*12} {'-'*20}")
    for i, s in enumerate(speech_segments):
        prev = s["text"][:30] + ("..." if len(s["text"]) > 30 else "")
        print(f"    {i:3d}  {s['character']:<8} {s['emotion_raw']:<16} {s['voice']:<12} {prev}")

    # Synthesize
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\n[3] Synthesizing {len(speech_segments)} segments...")
    results = []
    total_start = time.time()

    for i, seg in enumerate(speech_segments):
        print(
            f"    [{i+1:2d}/{len(speech_segments)}] {seg['character']:<8} "
            f"{seg['emotion_raw'][:12]:<12} {seg['voice']:<12}",
            end=" ",
            flush=True,
        )
        t0 = time.time()
        result = synthesize(kokoro, seg, i, OUTPUT_DIR)
        dt = time.time() - t0
        print(f"OK {result['duration_s']:.1f}s ({dt:.1f}s)")

        results.append(result)

    total_elapsed = time.time() - total_start
    total_duration = sum(r["duration_s"] for r in results)

    # Stitch chapter audio
    print("\n[4] Stitching chapter audio...")
    all_audio = []
    for r in results:
        audio, _ = sf.read(r["file"])
        all_audio.append(audio)
    chapter_audio = np.concatenate(all_audio)
    chapter_path = OUTPUT_DIR / "full_chapter.wav"
    sf.write(str(chapter_path), chapter_audio, SAMPLE_RATE)

    # Report
    print("\n" + "=" * 60)
    print("  TEST REPORT")
    print("=" * 60)
    print(f"  Segments:         {len(results)}")
    print(f"  Total duration:   {total_duration:.1f}s ({total_duration/60:.1f} min)")
    print(f"  Synthesis time:   {total_elapsed:.1f}s")
    print(f"  Real-time ratio:  {total_elapsed/total_duration:.1f}x")
    print(f"  Output dir:       {OUTPUT_DIR}")
    print(f"  Chapter audio:    {chapter_path} ({chapter_path.stat().st_size/1024**2:.1f} MB)")
    print(f"\n  Segment details:")
    for r in results:
        print(
            f"    seg_{r['segment_id']:03d} | {r['character']:<8} | "
            f"{r['voice']:<12} | spd={r['speed']:.2f} | "
            f"{r['duration_s']:.1f}s | {r['text_preview']}"
        )

    print(f"\n  END-TO-END TEST PASSED!")
    return 0


if __name__ == "__main__":
    exit(main())
