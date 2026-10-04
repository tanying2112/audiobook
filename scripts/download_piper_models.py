#!/usr/bin/env python3
"""Download Piper voice models (S2-4) — reuses the P0-2 downloader primitives.

Fetches the Chinese voice family (default: ``zh_CN-huayan-medium``) plus any extra
voices requested via ``--voices``. Mirrors ``scripts/download_kokoro_model.py``.

Usage:
    PYTHONPATH=src python scripts/download_piper_models.py
    PYTHONPATH=src python scripts/download_piper_models.py --voices zh_CN-huayan-medium zh_CN-shaoer-medium
    PYTHONPATH=src python scripts/download_piper_models.py --model-dir models/piper --force
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from audiobook_studio.tts.piper_models import (  # noqa: E402
    DEFAULT_PIPER_VOICE,
    PIPER_DEFAULT_MODEL_DIR,
    ensure_piper_models,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Download Piper TTS voice models (S2-4)")
    ap.add_argument(
        "--voices",
        nargs="+",
        default=[DEFAULT_PIPER_VOICE],
        help=f"Voice ids to download (default: {DEFAULT_PIPER_VOICE})",
    )
    ap.add_argument("--model-dir", default=str(PIPER_DEFAULT_MODEL_DIR), help="Target model directory")
    ap.add_argument("--force", action="store_true", help="Re-download even if present")
    args = ap.parse_args()

    ok = ensure_piper_models(
        model_dir=Path(args.model_dir),
        voices=args.voices,
        force=args.force,
    )
    if ok:
        print(f"OK: Piper models ready in {args.model_dir}")
        return 0
    print("FAILED: Piper model download/verification failed (check network).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
