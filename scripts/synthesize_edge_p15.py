#!/usr/bin/env python3
"""Run Edge TTS synthesis for Project 15 (Gift of the Magi v2).

This script extracts text from the PDF, runs Edge TTS synthesis for all valid
paragraphs, and saves output to output/edge_v2_p15/ for comparison with Kokoro.
"""

import asyncio
import os
import re
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import edge_tts
import fitz  # PyMuPDF

from audiobook_studio.pipeline.synthesize import AudioSegment, SynthesizePipeline, _normalize_voice_id
from audiobook_studio.schemas.book import CharacterVoiceBinding
from audiobook_studio.schemas.paragraph import ParagraphAnnotation
from audiobook_studio.schemas.tts_routing import TtsRoutingInput
from audiobook_studio.tts.providers_config import gpu_backends_enabled, select_engine


def extract_paragraphs_from_pdf(pdf_path: str) -> list[tuple[int, str, str]]:
    """Extract paragraphs from PDF, returning (index, speaker, text)."""
    doc = fitz.open(pdf_path)
    full_text = ""
    for i, page in enumerate(doc):
        full_text += page.get_text() + "\n"

    # The book is "The Gift of the Magi" - a short story with some intro
    # Split by double newlines to get paragraphs
    # But we need to handle the structure properly

    # Remove page numbers and headers
    lines = full_text.split("\n")
    cleaned_lines = []
    for line in lines:
        line = line.strip()
        # Skip page numbers, headers, footers
        if re.match(r"^\d+$", line):
            continue
        if "The Gift of the Magi" in line and len(line) < 50:
            continue
        if "O. HENRY" in line and len(line) < 50:
            continue
        if "Level 1" in line and len(line) < 50:
            continue
        if "Retold by" in line and len(line) < 50:
            continue
        if "Series Editors" in line and len(line) < 50:
            continue
        if "Pearson Education" in line:
            continue
        if "Published and distributed" in line:
            continue
        if "*" in line and "Magi" in line:
            continue
        cleaned_lines.append(line)

    text = "\n".join(cleaned_lines)
    # Split by double newline
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip() and len(p.strip()) > 20]

    # Assign speakers based on content analysis
    results = []
    for i, para in enumerate(paragraphs, 1):
        speaker = "_narrator_"
        # Check for dialogue
        if '"' in para or "'" in para:
            # Heuristic: if it's Della or Jim speaking
            if "Della" in para and ("she" in para.lower() or "Della" in para):
                speaker = "Della"
            elif "Jim" in para and ("he" in para.lower() or "Jim" in para):
                speaker = "Jim"
            elif "Mrs. Sofronie" in para:
                speaker = "Mrs. Sofronie"
        results.append((i, speaker, para))

    return results


async def synthesize_paragraph(text: str, voice_id: str, output_path: Path, prosody: dict = None) -> tuple[int, str]:
    """Synthesize a single paragraph using Edge TTS directly."""
    if prosody is None:
        prosody = {}

    # Convert prosody to edge_tts kwargs
    rate = float(prosody.get("rate", 1.0) or 1.0)
    pitch_st = float(prosody.get("pitch", 0.0) or 0.0)
    volume_db = float(prosody.get("volume", 0.0) or 0.0)

    rate_pct = int(round((rate - 1.0) * 100))
    rate_pct = max(-50, min(50, rate_pct))
    pitch_hz = max(-50, min(50, int(round(pitch_st * 6))))

    import math

    vol_pct = int(round((math.pow(10.0, volume_db / 20.0) - 1.0) * 100))
    vol_pct = max(-100, min(100, vol_pct))

    comm_kwargs = {
        "rate": f"{rate_pct:+d}%",
        "pitch": f"{pitch_hz:+d}Hz",
        "volume": f"{vol_pct:+d}%",
    }

    communicate = edge_tts.Communicate(text, voice_id, **comm_kwargs)
    await communicate.save(str(output_path))

    # Measure duration
    try:
        from mutagen.mp3 import MP3

        audio = MP3(str(output_path))
        duration_ms = int(audio.info.length * 1000)
    except Exception:
        duration_ms = max(1000, len(text) * 80)

    return duration_ms, "edge"


async def main():
    # Force Edge TTS by setting prefer_local=False
    os.environ["PREFER_CLOUD_TTS"] = "true"
    os.environ["EDGE_TTS_ENABLED"] = "true"

    # Output directory for Edge TTS
    output_dir = Path("/Users/guwj/Documents/audiobook/output/edge_v2_p15")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Check what we already have
    existing = set()
    for f in output_dir.glob("15_ch1_p*.wav"):
        parts = f.stem.split("_")
        for p in parts:
            if p.startswith("p") and p[1:].isdigit():
                existing.add(int(p[1:]))

    print(f"Already synthesized: {sorted(existing)}")

    # Extract paragraphs from PDF
    pdf_path = "/Users/guwj/Documents/audiobook/data/uploads/32a68fd0-821c-4119-b8b4-35714b00223f_magi.pdf"
    paragraphs = extract_paragraphs_from_pdf(pdf_path)
    print(f"Extracted {len(paragraphs)} paragraphs from PDF")

    # Character voice map - using Edge TTS voice IDs
    # Map speakers to Edge TTS voices
    voice_map = {
        "_narrator_": "en-US-JennyNeural",
        "Della": "en-US-AriaNeural",
        "Jim": "en-US-GuyNeural",
        "Mrs. Sofronie": "en-US-JennyNeural",
    }

    # Synthesize missing paragraphs
    missing = [i for i in range(1, len(paragraphs) + 1) if i not in existing]
    print(f"Missing paragraphs to synthesize: {missing}")

    for idx, speaker, text in paragraphs:
        if idx in existing:
            print(f"  Skipping p{idx} (already exists)")
            continue

        if idx not in missing:
            print(f"  Skipping p{idx} (not in missing list)")
            continue

        voice_id = voice_map.get(speaker, "en-US-JennyNeural")
        output_path = output_dir / f"15_ch1_p{idx}.wav"

        print(f"  Synthesizing p{idx} ({speaker}): {text[:60]}... [voice={voice_id}]")

        try:
            duration, engine = await synthesize_paragraph(
                text=text,
                voice_id=voice_id,
                output_path=output_path,
                prosody={"rate": 1.0, "pitch": 0.0, "volume": 0.0},
            )
            print(f"    ✓ Done: {duration}ms")
        except Exception as e:
            print(f"    ✗ Failed: {e}")

    print(f"\nSynthesis complete. Total files: {len(list(output_dir.glob('15_ch1_p*.wav')))}")


if __name__ == "__main__":
    asyncio.run(main())
