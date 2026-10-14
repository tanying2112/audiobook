#!/usr/bin/env python3
"""Test Edge TTS on paragraphs from Football Forever."""

import asyncio
import sys
from pathlib import Path

import edge_tts


async def test_edge_tts():
    """Test Edge TTS with real audio generation."""
    output_dir = Path("./output/test_edge_tts")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Test texts from Football Forever
    test_texts = [
        "It is the last game of the year. We need to win to get the Cup.",
        "I am Albertino, or Tino to my friends.",
        "We want to win, but nobody answers.",
    ]

    # Use a good English voice
    voice = "en-US-AriaNeural"  # American female voice
    # voice = "en-GB-SoniaNeural"  # British female voice
    # voice = "en-US-GuyNeural"  # American male voice

    for i, text in enumerate(test_texts):
        print(f"\n[{i+1}/{len(test_texts)}] Synthesizing: {text[:50]}...")
        try:
            output_path = output_dir / f"test_{i}.mp3"
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(str(output_path))

            if output_path.exists():
                size = output_path.stat().st_size
                print(f"  ✅ Generated: {output_path} ({size} bytes)")
            else:
                print(f"  ❌ Failed to generate audio")
                return False
        except Exception as e:
            print(f"  ❌ Error: {e}")
            import traceback

            traceback.print_exc()
            return False

    print(f"\n✅ All {len(test_texts)} audio files generated successfully!")
    print(f"Output directory: {output_dir}")
    return True


if __name__ == "__main__":
    success = asyncio.run(test_edge_tts())
    sys.exit(0 if success else 1)
