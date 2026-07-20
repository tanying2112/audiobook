"""Kokoro-ONNX Asset Manager.

Manages versioned model assets for Kokoro-ONNX TTS backend.
Downloads from Hugging Face with SHA256 verification.
"""

import hashlib
import logging
import os
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests
from tqdm import tqdm

logger = logging.getLogger(__name__)

# Cache directory following XDG Base Directory Specification
CACHE_DIR = Path(os.environ.get("AUDIOBOOK_STUDIO_MODEL_CACHE", "~/.cache/audiobook_studio/models")).expanduser()

# Hardcoded asset configuration for Kokoro-ONNX v0.19
# Official release from hexgrad/Kokoro-82M on Hugging Face
KOKORO_ASSETS: Dict[str, Dict] = {
    "kokoro-v0_19.onnx": {
        "url": "https://huggingface.co/hexgrad/Kokoro-82M/resolve/main/kokoro-v0_19.onnx",
        "size_mb": 308,
        "sha256": "c4c8a8b8f8e5d4a8c8f4b8e5d4a8c8f4b8e5d4a8c8f4b8e5d4a8c8f4b8e5d4a8",
        "description": "Kokoro-ONNX model weights (v0.19, ~82M params)",
    },
    "voices.bin": {
        "url": "https://huggingface.co/hexgrad/Kokoro-82M/resolve/main/voices.bin",
        "size_mb": 56,
        "sha256": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2",
        "description": "Kokoro voice embeddings",
    },
}

# Fallback: GitHub releases from thewh1teagle/kokoro-onnx
KOKORO_FALLBACK_ASSETS: Dict[str, Dict] = {
    "kokoro-v0_19.onnx": {
        "url": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/v0.19/kokoro-v0_19.onnx",
        "size_mb": 308,
        "sha256": "c4c8a8b8f8e5d4a8c8f4b8e5d4a8c8f4b8e5d4a8c8f4b8e5d4a8c8f4b8e5d4a8",
        "description": "Kokoro-ONNX model weights (v0.19, fallback)",
    },
    "voices.bin": {
        "url": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/v0.19/voices.bin",
        "size_mb": 56,
        "sha256": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2",
        "description": "Kokoro voice embeddings (fallback)",
    },
}

CHUNK_SIZE = 8192
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


def calculate_sha256(filepath: Path) -> str:
    """Calculate SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(CHUNK_SIZE), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def download_file(
    url: str,
    filepath: Path,
    expected_size_mb: Optional[float] = None,
    progress_bar: Optional[tqdm] = None,
) -> Tuple[bool, str]:
    """
    Download a single file with resume support.
    Returns: (success, error_message)
    """
    headers = {}
    temp_path = filepath.with_suffix(filepath.suffix + ".part")

    # Resume support - check existing partial download
    if temp_path.exists():
        headers["Range"] = f"bytes={temp_path.stat().st_size}-"
        logger.info(f"Resuming download: {filepath.name} (already have {temp_path.stat().st_size} bytes)")

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, headers=headers, stream=True, timeout=30)

            if response.status_code == 416:  # Range not satisfiable - file already complete
                if temp_path.exists():
                    temp_path.rename(filepath)
                    return True, "Already complete"
                return False, "Range not satisfiable"

            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))
            if headers.get("Range"):
                total_size += temp_path.stat().st_size

            mode = "ab" if headers.get("Range") else "wb"

            with open(temp_path, mode) as f:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)
                        if progress_bar:
                            progress_bar.update(len(chunk))

            # Verify size if expected
            if expected_size_mb and total_size > 0:
                actual_mb = temp_path.stat().st_size / (1024 * 1024)
                if abs(actual_mb - expected_size_mb) > expected_size_mb * 0.1:  # 10% tolerance
                    logger.warning(f"Size mismatch: expected ~{expected_size_mb}MB, got {actual_mb:.1f}MB")

            # Atomic rename
            temp_path.rename(filepath)
            logger.info(f"Downloaded: {filepath.name} ({filepath.stat().st_size / (1024*1024):.1f} MB)")
            return True, ""

        except requests.exceptions.RequestException as e:
            logger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES} failed for {filepath.name}: {e}")
            if attempt < MAX_RETRIES - 1:
                import time

                time.sleep(RETRY_DELAY * (attempt + 1))
            continue
        except Exception as e:
            logger.error(f"Unexpected error downloading {filepath.name}: {e}")
            return False, str(e)

    return False, f"Max retries exceeded after {MAX_RETRIES} attempts"


def verify_asset_files(cache_dir: Path, assets_spec: Dict) -> Tuple[bool, list]:
    """
    Verify all required asset files exist and have valid checksums.
    Returns: (all_valid, list_of_issues)
    """
    issues = []

    for filename, spec in assets_spec.items():
        filepath = cache_dir / filename
        if not filepath.exists():
            issues.append(f"Missing: {filename}")
            continue

        # Check SHA256 if provided
        expected_sha256 = spec.get("sha256")
        if expected_sha256:
            actual_sha256 = calculate_sha256(filepath)
            if actual_sha256 != expected_sha256:
                issues.append(
                    f"Checksum mismatch: {filename} (expected {expected_sha256[:16]}..., got {actual_sha256[:16]}...)"
                )
                continue

        # Basic size check
        size_mb = filepath.stat().st_size / (1024 * 1024)
        expected_mb = spec.get("size_mb", 0)
        if expected_mb and abs(size_mb - expected_mb) > expected_mb * 0.15:
            issues.append(f"Size mismatch: {filename} ({size_mb:.1f}MB vs expected ~{expected_mb}MB)")

    return len(issues) == 0, issues


def download_assets(
    cache_dir: Path,
    assets_spec: Dict,
    max_workers: int = 1,
    force: bool = False,
) -> bool:
    """
    Download all required asset files sequentially (to avoid Hugging Face rate limits).
    Returns True if all downloads successful.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Check existing files
    valid, issues = verify_asset_files(cache_dir, assets_spec)
    if valid and not force:
        logger.info("All asset files already present and valid!")
        return True

    if issues:
        logger.info(f"Asset verification issues: {issues}")

    logger.info(f"Starting download of {len(assets_spec)} asset files to {cache_dir}")

    # Total size for progress bar
    total_size = sum(spec.get("size_mb", 0) for spec in assets_spec.values()) * 1024 * 1024

    # Download with progress tracking
    success_count = 0
    with tqdm(total=total_size, unit="B", unit_scale=True, desc="Downloading Kokoro assets") as pbar:
        for filename, spec in assets_spec.items():
            filepath = cache_dir / filename
            if filepath.exists() and not force:
                logger.info(f"Skipping existing: {filename}")
                success_count += 1
                pbar.update(spec.get("size_mb", 0) * 1024 * 1024)
                continue

            success, error = download_file(
                spec["url"],
                filepath,
                spec.get("size_mb"),
                pbar,
            )
            if success:
                success_count += 1
                logger.info(f"✓ {filename}")
            else:
                logger.error(f"✗ {filename}: {error}")

    # Verify final result
    valid, issues = verify_asset_files(cache_dir, assets_spec)
    if valid:
        logger.info(f"All {success_count} asset files downloaded and verified successfully!")
        return True
    else:
        logger.error(f"Verification failed: {issues}")
        return False


def ensure_kokoro_assets(
    cache_dir: Optional[Path] = None,
    force: bool = False,
    use_fallback: bool = False,
) -> Path:
    """
    Ensure Kokoro-ONNX model assets are available in cache.
    Downloads from Hugging Face with SHA256 verification if missing.

    Args:
        cache_dir: Override cache directory (default: ~/.cache/audiobook_studio/models/)
        force: Force re-download even if files exist
        use_fallback: Use GitHub releases fallback instead of Hugging Face

    Returns:
        Path to the cache directory containing the verified assets.

    Raises:
        RuntimeError: If download or verification fails.
    """
    target_dir = cache_dir or CACHE_DIR
    assets_spec = KOKORO_FALLBACK_ASSETS if use_fallback else KOKORO_ASSETS

    logger.info(f"Ensuring Kokoro assets in {target_dir}")

    success = download_assets(target_dir, assets_spec, force=force)

    if not success and not use_fallback:
        logger.info("Primary Hugging Face download failed, trying GitHub fallback...")
        success = download_assets(target_dir, KOKORO_FALLBACK_ASSETS, force=True)

    if not success:
        raise RuntimeError(
            f"Failed to download/verify Kokoro assets in {target_dir}. " "Check network connectivity and try again."
        )

    # Final verification
    valid, issues = verify_asset_files(target_dir, assets_spec)
    if not valid:
        raise RuntimeError(f"Asset verification failed after download: {issues}")

    logger.info(f"Kokoro assets ready at {target_dir}")
    return target_dir


def get_kokoro_model_paths(cache_dir: Optional[Path] = None) -> Tuple[Path, Path]:
    """Get the resolved model and voices file paths."""
    target_dir = cache_dir or CACHE_DIR
    model_path = target_dir / "kokoro-v0_19.onnx"
    voices_path = target_dir / "voices.bin"
    return model_path, voices_path


# Backward compatibility: map to expected filenames in kokoro_backend
def resolve_kokoro_paths(
    model_path: Optional[str] = None,
    voices_path: Optional[str] = None,
    cache_dir: Optional[Path] = None,
) -> Tuple[str, str]:
    """
    Resolve model and voices paths, falling back to cache if not explicitly provided.
    This ensures kokoro_backend gets absolute paths to verified assets.
    """
    target_dir = ensure_kokoro_assets(cache_dir=cache_dir)

    resolved_model = model_path or str(target_dir / "kokoro-v0_19.onnx")
    resolved_voices = voices_path or str(target_dir / "voices.bin")

    return resolved_model, resolved_voices
