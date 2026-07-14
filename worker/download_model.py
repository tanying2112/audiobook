#!/usr/bin/env python3
"""
Download VoxCPM2 model to Modal volume for persistent storage.
Run once before deploying workers: `modal run worker/download_model.py`
"""

import modal

# Model repo - official VoxCPM2 from OpenBMB
MODEL_REPO = "openbmb/VoxCPM2"

# Use the same volume as the worker
model_vol = modal.Volume.from_name("voxcpm2-model-vol", create_if_missing=True)

# Image with necessary dependencies
download_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "huggingface_hub",
        "transformers",
        "sentencepiece",
        "protobuf",
        "tiktoken",
        "torch",
        "torchaudio",
        "accelerate",
    )
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
    from huggingface_hub import snapshot_download
    from transformers import AutoTokenizer, AutoModelForCausalLM

    model_path = "/models"
    repo_id = os.getenv("VOXCPM2_MODEL_REPO", "openbmb/VoxCPM2")

    print(f"📥 Downloading {repo_id} to {model_path}...")

    # Download model snapshot
    snapshot_download(
        repo_id=repo_id,
        local_dir=model_path,
        local_dir_use_symlinks=False,
        resume_download=True,
    )

    print(f"✅ Model downloaded to {model_path}")

    # Fix config.json - add model_type for transformers auto-detection
    import json
    config_path = os.path.join(model_path, "config.json")
    with open(config_path, "r") as f:
        config = json.load(f)
    config["model_type"] = "voxcpm2"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    print("🔧 Added model_type to config.json")

    # Verify tokenizer loads
    print("🔍 Verifying tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True, use_fast=False)
    print(f"✅ Tokenizer loaded: {tokenizer.__class__.__name__}")

    # Verify model loads
    print("🔍 Verifying model...")
    import torch
    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        torch_dtype=torch.float16,
        device_map="auto",
        trust_remote_code=True,
    )
    model.eval()
    print(f"✅ Model loaded: {model.__class__.__name__}")

    # Test inference
    print("🧪 Running test inference...")
    inputs = tokenizer("测试语音合成。", return_tensors="pt").to("cuda" if torch.cuda.is_available() else "cpu")
    with torch.inference_mode():
        outputs = model.generate(**inputs, max_new_tokens=10)
    print(f"✅ Test inference successful: {outputs.shape}")

    # Commit volume changes
    model_vol.commit()
    print("💾 Volume committed")


@app.local_entrypoint()
def main():
    download_model.remote()


if __name__ == "__main__":
    main()