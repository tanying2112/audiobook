#!/usr/bin/env python3
"""Convert Football Forever PDF text to audiobook using Edge TTS."""

import asyncio
import re
import sys
from pathlib import Path

import edge_tts


def split_into_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs for TTS."""
    # Split by double newlines or single newlines with empty lines
    paragraphs = []
    current = []

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            if current:
                para = " ".join(current)
                if len(para) > 20:  # Skip very short paragraphs
                    paragraphs.append(para)
                current = []
        else:
            current.append(line)

    # Add last paragraph
    if current:
        para = " ".join(current)
        if len(para) > 20:
            paragraphs.append(para)

    return paragraphs


async def synthesize_paragraph(text: str, output_path: Path, voice: str = "en-US-AriaNeural"):
    """Synthesize a single paragraph."""
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(output_path))
        return True
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False


async def convert_to_audio(input_file: Path, output_dir: Path, voice: str = "en-US-AriaNeural"):
    """Convert text file to audiobook."""
    print(f"Reading: {input_file}")

    # Read text
    text = input_file.read_text(encoding="utf-8")
    print(f"Text length: {len(text)} characters")

    # Split into paragraphs
    paragraphs = split_into_paragraphs(text)
    print(f"Split into {len(paragraphs)} paragraphs")

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Synthesize each paragraph
    audio_files = []
    for i, para in enumerate(paragraphs):
        output_path = output_dir / f"para_{i:04d}.mp3"
        print(f"[{i+1}/{len(paragraphs)}] Synthesizing...")

        success = await synthesize_paragraph(para, output_path, voice)
        if success:
            audio_files.append(output_path)
            print(f"  ✅ {output_path.name} ({output_path.stat().st_size} bytes)")
        else:
            print(f"  ❌ Failed")

    print(f"\n✅ Generated {len(audio_files)} audio files")
    return audio_files


async def main():
    # Input file
    input_file = Path("/Users/guwj/Documents/audiobook/data/mock_data/Football Forever/chapter_01.txt")
    if not input_file.exists():
        print(f"❌ Input file not found: {input_file}")
        return False

    # Output directory
    output_dir = Path("/Users/guwj/Documents/audiobook/output/football_forever_audio")

    # Generate audio
    audio_files = await convert_to_audio(input_file, output_dir)

    if audio_files:
        print(f"\n📁 Audio files saved to: {output_dir}")
        print(f"Total files: {len(audio_files)}")

        # Create a concatenated version (simple concatenation for MP3)
        print("\n🔗 Creating concatenated audiobook...")
        concat_path = output_dir / "football_forever_full.mp3"

        # For MP3, we can use simple concatenation (works for most MP3 players)
        with open(concat_path, "wb") as outfile:
            for audio_file in audio_files:
                with open(audio_file, "rb") as infile:
                    outfile.write(infile.read())

        print(f"✅ Concatenated audiobook: {concat_path}")
        print(f"   Size: {concat_path.stat().st_size / 1024 / 1024:.1f} MB")

        return True
    else:
        print("❌ No audio files generated")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
