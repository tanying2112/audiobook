#!/usr/bin/env python3
"""
Kokoro-ONNX Model Downloader CLI
================================

Thin CLI wrapper that delegates to src/audiobook_studio/tts/model_downloader.py

Downloads Kokoro-ONNX model files from Hugging Face with:
- Resume support (断点续传)
- Checksum verification (校验)
- Multi-threaded downloads (多线程下载)
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.audiobook_studio.tts.model_downloader import (
    DEFAULT_MODEL_DIR,
    FALLBACK_FILES,
    REQUIRED_FILES,
    download_all_models,
    ensure_models_available,
    get_model_paths,
    verify_models,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Download Kokoro-ONNX model files")
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=DEFAULT_MODEL_DIR,
        help="Directory to store model files",
    )
    parser.add_argument("--force", action="store_true", help="Force re-download even if files exist")
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify existing files, don't download",
    )
    parser.add_argument("--fallback", action="store_true", help="Use fallback URLs (GitHub releases)")
    parser.add_argument("--workers", type=int, default=3, help="Number of parallel downloads")
    parser.add_argument(
        "--show-paths",
        action="store_true",
        help="Show expected model file paths and exit",
    )

    args = parser.parse_args()

    if args.show_paths:
        model_path, voices_path = get_model_paths(args.model_dir)
        print(f"Model: {model_path}")
        print(f"Voices: {voices_path}")
        return 0

    if args.verify_only:
        valid, issues = verify_models(args.model_dir)
        if valid:
            print("✓ All model files verified successfully")
            return 0
        else:
            print(f"✗ Verification failed: {issues}")
            return 1

    files_spec = FALLBACK_FILES if args.fallback else REQUIRED_FILES

    success = download_all_models(
        model_dir=args.model_dir,
        files_spec=files_spec,
        max_workers=args.workers,
        force=args.force,
    )

    if not success and not args.fallback:
        logger.info("Primary download failed, trying fallback...")
        success = download_all_models(
            model_dir=args.model_dir,
            files_spec=FALLBACK_FILES,
            max_workers=args.workers,
            force=True,
        )

    if success:
        print("\n✓ Kokoro-ONNX models ready!")
        model_path, voices_path = get_model_paths(args.model_dir)
        print(f"  Model: {model_path}")
        print(f"  Voices: {voices_path}")
        return 0
    else:
        print("\n✗ Failed to download models")
        return 1


if __name__ == "__main__":
    sys.exit(main())
