#!/usr/bin/env python3
"""
Download VoxCPM2 model to Modal volume for persistent storage.
Run once before deploying workers: `modal run worker/download_model.py`

Note: This just downloads the raw model files. The actual model loading
is done by the custom VoxCPM2Engine in modal_worker.py which uses
the voxcpm module's custom implementation.
"""

import modal

# Model repo - official VoxCPM2 from OpenBMB
MODEL_REPO = "openbmb/VoxCPM2"

# Use the same volume as the worker
model_vol = modal.Volume.from_name("voxcpm2-model-vol", create_if_missing=True)

# Image with necessary dependencies
download_image = modal.Image.debian_slim(python_version="3.12").pip_install(
    "huggingface_hub",
    "hf_transfer",
)

app = modal.App("voxcpm2-model-downloader")


@app.function(
    image=download_image,
    volumes={"/models": model_vol},
    timeout=3600,  # 1 hour for download
    secrets=[modal.Secret.from_name("audiobook-config")],  # For HF token if needed
)
def download_model():
    """Download VoxCPM2 model to the persistent volume."""
    import os
    import json

    from huggingface_hub import snapshot_download

    # Modal worker expects model at /models/voxcpm2-cache
    model_path = "/models/voxcpm2-cache"
    repo_id = os.getenv("VOXCPM2_MODEL_REPO", "openbmb/VoxCPM2")

    print(f"📥 Downloading {repo_id} to {model_path}...")

    # Use hf_transfer for faster downloads
    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

    # Download model snapshot
    snapshot_download(
        repo_id=repo_id,
        local_dir=model_path,
        local_dir_use_symlinks=False,
        resume_download=True,
        max_workers=8,
    )

    print(f"✅ Model downloaded to {model_path}")

    # Fix config.json - add model_type for future reference
    config_path = os.path.join(model_path, "config.json")
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            config = json.load(f)
        if config.get("model_type") != "voxcpm2":
            config["model_type"] = "voxcpm2"
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)
            print("🔧 Added model_type to config.json")

    # Commit volume changes
    model_vol.commit()
    print("💾 Volume committed")


@app.function(
    image=download_image,
    volumes={"/models": model_vol},
    timeout=60,
)
def read_config():
    """Read model config for debugging."""
    import json
    config_path = "/models/voxcpm2-cache/config.json"
    with open(config_path) as f:
        config = json.load(f)
    print(json.dumps(config, indent=2))
    return config


@app.function(
    image=download_image,
    volumes={"/models": model_vol},
    timeout=60,
)
def check_voxcpm_version():
    """Check voxcpm version and location."""
    import voxcpm
    print(f"voxcpm location: {voxcpm.__file__}")
    print(f"voxcpm version: {getattr(voxcpm, '__version__', 'unknown')}")
    try:
        import voxcpm.model.voxcpm2 as v2
        print(f"voxcpm2 module: {v2.__file__}")
    except Exception as e:
        print(f"voxcpm2 import error: {e}")


@app.local_entrypoint()
def main():
    download_model.remote()


if __name__ == "__main__":
    main()
