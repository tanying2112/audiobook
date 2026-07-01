#!/usr/bin/env python3
"""Download VoxCPM2 model from Hugging Face.

Usage:
    python scripts/download_voxcpm2.py
    python scripts/download_voxcpm2.py --model-dir models/VoxCPM2
    python scripts/download_voxcpm2.py --repo-id OpenBMB/VoxCPM2
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def download_model(
    repo_id: str = "OpenBMB/VoxCPM2",
    model_dir: str = "models/VoxCPM2",
    revision: str = "main",
    token: Optional[str] = None,
) -> bool:
    """Download VoxCPM2 model from Hugging Face Hub.

    Args:
        repo_id: Hugging Face repository ID
        model_dir: Local directory to save model
        revision: Git revision/branch to download
        token: HF token for private/gated models

    Returns:
        True if successful, False otherwise
    """
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        logger.error("huggingface_hub not installed. Run: pip install huggingface_hub")
        return False

    model_path = Path(model_dir).absolute()

    if model_path.exists() and any(model_path.iterdir()):
        logger.info(f"Model directory {model_path} already exists and is not empty")
        response = input("Overwrite? (y/N): ").strip().lower()
        if response != "y":
            logger.info("Download cancelled")
            return False

    logger.info(f"Downloading {repo_id} (rev: {revision}) to {model_path}...")

    try:
        snapshot_download(
            repo_id=repo_id,
            local_dir=model_path,
            revision=revision,
            token=token,
            local_dir_use_symlinks=False,
            resume_download=True,
        )
        logger.info(f"Successfully downloaded to {repo_id} downloaded to {model_path}")
        return True

    except Exception as e:
        logger.error(f"Download failed: {e}")
        return False


def verify_model(model_dir: str = "models/VoxCPM2") -> bool:
    """Verify downloaded model has required files."""
    model_path = Path(model_dir)

    required_files = [
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
    ]

    optional_files = [
        "voice_embeddings.pt",
        "codec/",
        "flow_matching/",
        "speaker_encoder/",
    ]

    logger.info(f"Verifying model at {model_path}...")

    # Check required files
    missing = []
    for f in required_files:
        if not (model_path / f).exists():
            missing.append(f)

    if missing:
        logger.warning(f"Missing required files: {missing}")
        return False

    # Check optional directories
    for f in optional_files:
        if (model_path / f).exists():
            logger.info(f" Found: {f}")
        else:
            logger.info(f" Optional not found (will use fallback): {f}")

    logger.info("Model verification passed!")
    return True


def main():
    parser = argparse.ArgumentParser(description="Download VoxCPM2 model")
    parser.add_argument(
        "--repo-id",
        default="OpenBMB/VoxCPM2",
        help="Hugging Face repository ID (default: OpenBMB/VoxCPM2)",
    )
    parser.add_argument(
        "--model-dir",
        default="models/VoxCPM2",
        help="Local model directory (default: models/VoxCPM2)",
    )
    parser.add_argument(
        "--revision", default="main", help="Git revision/branch (default: main)"
    )
    parser.add_argument(
        "--token", default=None, help="HF token for private/gated models"
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify existing model, don't download",
    )
    parser.add_argument(
        "--hf-mirror",
        default=None,
        help="HF mirror endpoint (e.g., https://hf-mirror.com for China)",
    )

    args = parser.parse_args()

    # Set HF mirror if provided
    if args.hf_mirror:
        os.environ["HF_ENDPOINT"] = args.hf_mirror
        logger.info(f"Using HF mirror: {args.hf_mirror}")

    if args.verify_only:
        success = verify_model(args.model_dir)
    else:
        success = download_model(
            repo_id=args.repo_id,
            model_dir=args.model_dir,
            revision=args.revision,
            token=args.token,
        )
        if success:
            success = verify_model(args.model_dir)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()