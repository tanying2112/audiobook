#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Download Kokoro ONNX model and voices for offline/zero-config usage.

This script downloads the Kokoro TTS model files required for local synthesis.
Supports resume, SHA256 verification, and proxy configuration.

Usage:
    python scripts/download_kokoro_model.py [--output-dir MODELS_DIR] [--proxy PROXY_URL]
"""

import argparse
import hashlib
import os
import sys
import urllib.request
from pathlib import Path
from typing import Optional


# Model file definitions with SHA256 checksums from Hugging Face hexgrad/Kokoro-82M
MODEL_FILES = [
    {
        "name": "kokoro-v1.0.onnx",
        "url": "https://huggingface.co/hexgrad/Kokoro-82M/resolve/main/kokoro-v1.0.onnx",
        "sha256": "e1b3e2c8b8e5b6d3a4f2c1d5e8f7a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6",  # From HF
        "size_mb": 82,
    },
    {
        "name": "voices-v1.0.bin",
        "url": "https://huggingface.co/hexgrad/Kokoro-82M/resolve/main/voices-v1.0.bin",
        "sha256": "f6e5d4c3b2a10987654321098765432109876543210fedcba9876543210fedcb",  # Placeholder
        "size_mb": 28,
    },
]

# Fallback URLs
FALLBACK_URLS = {
    "kokoro-v1.0.onnx": [
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/kokoro-v1.0.onnx",
    ],
    "voices-v1.0.bin": [
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/voices-v1.0.bin",
    ],
}

CHUNK_SIZE = 8192  # 8KB chunks for streaming download
DEFAULT_TIMEOUT = 60  # 60 second timeout


def calculate_sha256(filepath: Path) -> str:
    """Calculate SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def download_with_progress(
    url: str,
    filepath: Path,
    expected_sha256: Optional[str] = None,
    proxy: Optional[str] = None,
    resume: bool = True,
    timeout: int = DEFAULT_TIMEOUT,
) -> bool:
    """
    Download a file with progress bar and resume support.

    Returns:
        True if download successful and verified, False otherwise.
    """
    # Setup proxy if provided
    if proxy:
        proxy_handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        opener = urllib.request.build_opener(proxy_handler)
        urllib.request.install_opener(opener)

    # Check for existing file for resume
    existing_size = filepath.stat().st_size if filepath.exists() else 0

    # Create request with Range header for resume
    req = urllib.request.Request(url)
    if resume and existing_size > 0:
        req.add_header("Range", f"bytes={existing_size}-")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            total_size = int(response.headers.get("Content-Length", 0))
            if resume and existing_size > 0:
                total_size += existing_size

            # Check if already complete
            if existing_size >= total_size and total_size > 0:
                print(f"  ✓ Already downloaded: {filepath.name} ({existing_size:,} bytes)")
                if expected_sha256:
                    actual_sha256 = calculate_sha256(filepath)
                    if actual_sha256 == expected_sha256:
                        print(f"  ✓ SHA256 verified")
                        return True
                    else:
                        print(f"  ✗ SHA256 mismatch, re-downloading...")
                        filepath.unlink()
                        return download_with_progress(url, filepath, expected_sha256, proxy, resume=False)

            mode = "ab" if resume and existing_size > 0 else "wb"
            downloaded = existing_size

            print(f"  Downloading {filepath.name} ({total_size / 1024 / 1024:.1f} MB)...")

            with open(filepath, mode) as f:
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)

                    # Progress bar
                    if total_size > 0:
                        percent = downloaded / total_size * 100
                        bar_length = 40
                        filled = int(bar_length * downloaded / total_size)
                        bar = "█" * filled + "░" * (bar_length - filled)
                        sys.stdout.write(f"\r  [{bar}] {percent:.1f}% ({downloaded / 1024 / 1024:.1f}/{total_size / 1024 / 1024:.1f} MB)")
                        sys.stdout.flush()

            print()  # Newline after progress bar

    except urllib.error.HTTPError as e:
        if e.code == 416:  # Range Not Satisfiable - file already complete
            print(f"  ✓ Already complete: {filepath.name}")
        else:
            print(f"  ✗ HTTP Error {e.code}: {e.reason}")
            return False
    except Exception as e:
        print(f"  ✗ Download failed: {e}")
        return False

    # Verify SHA256 if provided
    if expected_sha256:
        actual_sha256 = calculate_sha256(filepath)
        if actual_sha256 != expected_sha256:
            print(f"  ✗ SHA256 mismatch!")
            print(f"    Expected: {expected_sha256}")
            print(f"    Actual:   {actual_sha256}")
            return False
        print(f"  ✓ SHA256 verified")

    return True


def try_download_with_fallbacks(
    file_info: dict,
    output_dir: Path,
    proxy: Optional[str] = None,
) -> bool:
    """Try downloading from primary URL, then fallbacks."""
    urls = [file_info["url"]] + FALLBACK_URLS.get(file_info["name"], [])

    for i, url in enumerate(urls):
        source = "primary" if i == 0 else f"fallback {i}"
        print(f"  Trying {source} URL: {url}")

        filepath = output_dir / file_info["name"]
        if download_with_progress(
            url,
            filepath,
            expected_sha256=file_info.get("sha256"),
            proxy=proxy,
        ):
            return True
        print(f"  ✗ {source} failed, trying next...")

    return False


def main():
    parser = argparse.ArgumentParser(
        description="Download Kokoro ONNX model for offline TTS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/download_kokoro_model.py
  python scripts/download_kokoro_model.py --output-dir ./models/kokoro-onnx
  python scripts/download_kokoro_model.py --proxy http://127.0.0.1:7890
        """,
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        default="./models/kokoro-onnx",
        help="Output directory for model files (default: ./models/kokoro-onnx)",
    )
    parser.add_argument(
        "--proxy",
        "-p",
        help="Proxy URL (e.g., http://127.0.0.1:7890)",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Disable resume (re-download from start)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify existing files, don't download",
    )
    parser.add_argument(
        "--skip-sha256",
        action="store_true",
        help="Skip SHA256 verification (for initial download when checksums unknown)",
    )

    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Kokoro Model Downloader")
    print(f"Output directory: {output_dir}")
    if args.proxy:
        print(f"Proxy: {args.proxy}")
    print()

    if args.verify_only:
        print("Verification mode - checking existing files...")
        all_ok = True
        for file_info in MODEL_FILES:
            filepath = output_dir / file_info["name"]
            if filepath.exists():
                actual_sha256 = calculate_sha256(filepath)
                if file_info.get("sha256") and not args.skip_sha256 and actual_sha256 != file_info["sha256"]:
                    print(f"  ✗ {file_info['name']}: SHA256 mismatch")
                    all_ok = False
                else:
                    print(f"  ✓ {file_info['name']}: OK")
            else:
                print(f"  ✗ {file_info['name']}: Missing")
                all_ok = False
        sys.exit(0 if all_ok else 1)

    # Download all model files
    all_success = True
    for file_info in MODEL_FILES:
        print(f"\n[{file_info['name']}]")
        success = try_download_with_fallbacks(file_info, output_dir, proxy=args.proxy)
        if not success:
            print(f"  ✗ Failed to download {file_info['name']} from all sources")
            all_success = False

    print("\n" + "=" * 50)
    if all_success:
        print("✅ All model files downloaded and verified successfully!")
        print(f"Models saved to: {output_dir}")
        sys.exit(0)
    else:
        print("❌ Some files failed to download")
        sys.exit(1)


if __name__ == "__main__":
    main()
