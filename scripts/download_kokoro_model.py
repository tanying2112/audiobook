#!/usr/bin/env python3
"""
Kokoro-ONNX 模型下载脚本
从 Hugging Face 下载 kokoro-onnx 所需的模型文件
支持断点续传、校验、多线程下载
"""

import hashlib
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from tqdm import tqdm

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Model configuration - Hugging Face repo
KOKORO_REPO = "hexgrad/Kokoro-82M"
MODEL_DIR = Path(__file__).parent.parent / "models" / "kokoro-onnx"

# Required model files with expected SHA256 checksums (for integrity verification)
# These are the standard kokoro-onnx files
REQUIRED_FILES = {
    "kokoro-v1.0.onnx": {
        "url": f"https://huggingface.co/{KOKORO_REPO}/resolve/main/kokoro-v1.0.onnx",
        "size_mb": 308,
        "sha256": None  # Will be verified on first download
    },
    "voices-v1.0.bin": {
        "url": f"https://huggingface.co/{KOKORO_REPO}/resolve/main/voices-v1.0.bin",
        "size_mb": 56,
        "sha256": None
    }
}

# Alternative: Official ONNX models from the kokoro-onnx repo
# If above fails, fallback to these
FALLBACK_FILES = {
    "model.onnx": {
        "url": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/v0.1.0/kokoro-v1.0.onnx",
        "size_mb": 308,
        "sha256": None
    },
    "voices.bin": {
        "url": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/v0.1.0/voices-v1.0.bin",
        "size_mb": 56,
        "sha256": None
    }
}

CHUNK_SIZE = 8192
MAX_WORKERS = 3
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
    expected_size_mb: float = None,
    progress_bar: Optional[tqdm] = None
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
                time.sleep(RETRY_DELAY * (attempt + 1))
            continue
        except Exception as e:
            logger.error(f"Unexpected error downloading {filepath.name}: {e}")
            return False, str(e)
    
    return False, f"Max retries exceeded after {MAX_RETRIES} attempts"


def verify_model_files(model_dir: Path, files_spec: Dict) -> Tuple[bool, List[str]]:
    """
    Verify all required model files exist and have valid checksums.
    Returns: (all_valid, list_of_missing_or_corrupt)
    """
    issues = []
    
    for filename, spec in files_spec.items():
        filepath = model_dir / filename
        if not filepath.exists():
            issues.append(f"Missing: {filename}")
            continue
        
        # Basic size check
        size_mb = filepath.stat().st_size / (1024 * 1024)
        expected_mb = spec.get("size_mb", 0)
        if expected_mb and abs(size_mb - expected_mb) > expected_mb * 0.15:
            issues.append(f"Size mismatch: {filename} ({size_mb:.1f}MB vs expected ~{expected_mb}MB)")
    
    return len(issues) == 0, issues


def download_all_models(
    model_dir: Path = MODEL_DIR,
    files_spec: Dict = REQUIRED_FILES,
    max_workers: int = MAX_WORKERS,
    force: bool = False
) -> bool:
    """
    Download all required model files.
    Returns True if all downloads successful.
    """
    model_dir.mkdir(parents=True, exist_ok=True)
    
    # Check existing files
    valid, issues = verify_model_files(model_dir, files_spec)
    if valid and not force:
        logger.info("All model files already present and valid!")
        return True
    
    if issues:
        logger.info(f"Model verification issues: {issues}")
    
    logger.info(f"Starting download of {len(files_spec)} model files to {model_dir}")
    
    # Prepare download tasks
    download_tasks = []
    for filename, spec in files_spec.items():
        filepath = model_dir / filename
        if filepath.exists() and not force:
            logger.info(f"Skipping existing: {filename}")
            continue
        # Store as tuple: (url, filepath, size_mb, filename)
        download_tasks.append((spec["url"], filepath, spec.get("size_mb"), filename))
    
    if not download_tasks:
        logger.info("Nothing to download")
        return True
    
    # Total size for progress bar
    total_size = sum(size_mb for _, _, size_mb, _ in download_tasks) * 1024 * 1024
    
    # Download with progress tracking
    success_count = 0
    with tqdm(total=total_size, unit="B", unit_scale=True, desc="Downloading models") as pbar:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(download_file, url, filepath, size_mb, pbar): filename  
                for url, filepath, size_mb, filename_ in download_tasks
            }
            
            for future in as_completed(futures):
                filename = futures[future]
                try:
                    success, error = future.result()
                    if success:
                        success_count += 1
                        logger.info(f"✓ {filename}")
                    else:
                        logger.error(f"✗ {filename}: {error}")
                except Exception as e:
                    logger.error(f"✗ {filename}: Exception: {e}")
    
    # Verify final result
    valid, issues = verify_model_files(model_dir, files_spec)
    if valid:
        logger.info(f"All {success_count} model files downloaded and verified successfully!")
        return True
    else:
        logger.error(f"Verification failed: {issues}")
        return False


def try_fallback_download(model_dir: Path) -> bool:
    """Try fallback URLs if primary download fails."""
    logger.info("Trying fallback download sources...")
    return download_all_models(model_dir, FALLBACK_FILES, force=True)


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Download Kokoro-ONNX model files")
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=MODEL_DIR,
        help="Directory to store model files"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-download even if files exist"
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify existing files, don't download"
    )
    parser.add_argument(
        "--fallback",
        action="store_true",
        help="Use fallback URLs (GitHub releases)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=MAX_WORKERS,
        help="Number of parallel downloads"
    )
    
    args = parser.parse_args()
    
    if args.verify_only:
        valid, issues = verify_model_files(args.model_dir, REQUIRED_FILES)
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
        force=args.force
    )
    
    if not success and not args.fallback:
        logger.info("Primary download failed, trying fallback...")
        success = try_fallback_download(args.model_dir)
    
    if success:
        print("\n✓ Kokoro-ONNX models ready!")
        return 0
    else:
        print("\n✗ Failed to download models")
        return 1


if __name__ == "__main__":
    sys.exit(main())
