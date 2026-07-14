#!/usr/bin/env python3
"""
Modal Serverless Worker for VoxCPM2 TTS (Spiky Demand - 40h/month T4).

Hermes-AgentMesh Core Architecture Integration:
- Inherits BaseWorker contract (heartbeat, graceful shutdown, retry, R2 upload)
- Polls Upstash Redis queue "tts:tasks" → synthesizes on T4 → pushes audio to Cloudflare R2
- Downloads model from Hugging Face Hub at runtime, caches to Modal Volume for fast cold start
- Requires Modal Secret "audiobook-config" with: REDIS_HOST, REDIS_PORT, REDIS_AUTH, R2_*, WORKER_ID, VOXCPM2_HF_REPO (optional)
"""

import json
import os
import sys
import io
from pathlib import Path
import modal

# Ensure src is on path for BaseWorker import
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

PROJECT_ROOT = Path(__file__).parent.parent

# ==========================================
# Safe torch import for local development
# ==========================================
try:
    import torch
except ImportError:
    class MockTorch:
        def inference_mode(self, *args, **kwargs):
            return lambda func: func
    torch = MockTorch()
    print("⚠️  Local env missing torch, mock active (cloud deployment unaffected).")

from src.worker_base import BaseWorker

# ==========================================
# 1. Modal Image Definition (pre-baked deps)
# ==========================================
worker_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg")
    .pip_install(
        "torch",
        "torchaudio",
        "transformers>=4.45.0",
        "sentencepiece",
        "protobuf",
        "tiktoken",
        "accelerate",
        "scipy",
        "soundfile",
        "redis",
        "boto3",
        "einops",
        "librosa",
        "safetensors",
        "pydantic",
        "tqdm",
        "huggingface_hub",  # NEW: for runtime model download
    )
    .add_local_dir(str(PROJECT_ROOT / "src"), remote_path="/src")
)

# Persistent volume for model cache (survives container recycle)
model_vol = modal.Volume.from_name("voxcpm2-model-vol", create_if_missing=True)

app = modal.App("dark-night-audio-factory-worker")


# ==========================================
# 2. Engine & Worker Classes
# ==========================================
class VoxCPM2Engine:
    """
    PyTorch VoxCPM2 inference engine for Modal using custom VoxCPM2 model.
    Downloads from HF Hub on first run, caches to Modal Volume.
    """

    HF_REPO_ID = os.getenv("VOXCPM2_HF_REPO", "openbmb/VoxCPM2")
    # Cache in Modal Volume for persistence across cold starts
    CACHE_DIR = "/models/voxcpm2-cache"

    def __init__(self, model_path: str = None):
        import torch
        self.model_path = model_path or self.CACHE_DIR
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = None
        self.tokenizer = None
        self._load_model()

    def _load_model(self) -> None:
        import torch
        from transformers import LlamaTokenizerFast
        from huggingface_hub import snapshot_download
        import sys
        sys.path.insert(0, "/src")

        from voxcpm.model.voxcpm2 import VoxCPM2Model

        # Ensure cache directory exists
        os.makedirs(self.CACHE_DIR, exist_ok=True)

        # Download from HF Hub if not cached
        config_path = Path(self.CACHE_DIR) / "config.json"
        if not config_path.exists():
            print(f"📡 Model not found in volume, downloading from HF: {self.HF_REPO_ID} -> {self.CACHE_DIR}...")
            snapshot_download(
                repo_id=self.HF_REPO_ID,
                local_dir=self.CACHE_DIR,
                local_dir_use_symlinks=False,
                resume_download=True,
            )
            print("✅ Model downloaded and cached to Modal Volume!")
        else:
            print(f"📦 Using cached model from Modal Volume: {self.CACHE_DIR}")

        self.model_path = self.CACHE_DIR
        print(f"Loading VoxCPM2 from {self.model_path} on {self.device}...")

        # Load tokenizer
        self.tokenizer = LlamaTokenizerFast.from_pretrained(self.model_path, use_fast=False)
        print(f"✅ Tokenizer loaded: {self.tokenizer.__class__.__name__}")

        # Load VoxCPM2 model using from_local class method
        self.model = VoxCPM2Model.from_local(
            self.model_path,
            device=self.device,
            optimize=False,
        )
        self.model.eval()
        print(f"✅ VoxCPM2 model loaded: {self.model.__class__.__name__}")

    @torch.inference_mode()
    def synthesize(
        self,
        text: str,
        voice_id: str,
        prosody: dict,
        reference_audio: str = None,
    ) -> bytes:
        reference_wav = reference_audio if reference_audio and Path(reference_audio).exists() else ""

        generator = self.model.generate(
            target_text=text,
            reference_wav_path=reference_wav,
            inference_timesteps=prosody.get("inference_timesteps", 10),
            cfg_value=prosody.get("cfg_value", 2.0),
            seed=prosody.get("seed", None),
        )

        audio_chunks = []
        for chunk in generator:
            audio_chunks.append(chunk)

        if not audio_chunks:
            raise ValueError("No audio generated")

        waveform = torch.cat(audio_chunks, dim=-1)

        import soundfile as sf
        import numpy as np
        buffer = io.BytesIO()
        sample_rate = getattr(self.model, 'sample_rate', 24000)
        sf.write(buffer, waveform.cpu().numpy().T, sample_rate, format="WAV")
        return buffer.getvalue()


class ModalWorker(BaseWorker):
    """Modal serverless worker implementation."""

    def __init__(self):
        super().__init__(platform_prefix="modal")

    def _init_engine(self):
        return VoxCPM2Engine()

    def _execute_smoke_test(self) -> None:
        print(f"🧪 [{self.worker_id}] Running smoke test...")
        test_audio = self.engine.synthesize("测试", "zh_female_1", {})
        print(f"✅ Smoke test passed: {len(test_audio)} bytes generated")

    def _synthesize(
        self,
        text: str,
        voice_id: str,
        prosody: dict,
        reference_audio: str = None,
    ) -> bytes:
        return self.engine.synthesize(text, voice_id, prosody, reference_audio)

    def _get_platform_gpu_metrics(self) -> dict:
        import torch
        return {
            "gpu_mem_used_mb": torch.cuda.memory_allocated() // (1024 * 1024) if torch.cuda.is_available() else 0,
            "gpu_mem_total_mb": torch.cuda.get_device_properties(0).total_memory // (1024 * 1024) if torch.cuda.is_available() else 0,
            "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU",
        }


# ==========================================
# 3. Modal Serverless Function
# ==========================================
@app.function(
    image=worker_image,
    gpu="T4",
    max_containers=2,
    volumes={"/models": model_vol},  # Persistent cache
    timeout=32400,
    secrets=[
        modal.Secret.from_name("audiobook-config"),
    ],
)
def run_modal_consumer() -> None:
    """Modal Serverless entry point running BaseWorker in ephemeral container."""
    import uuid
    os.environ["WORKER_ID"] = os.getenv("WORKER_ID", f"modal-t4-{uuid.uuid4().hex[:8]}")
    os.environ["IDLE_TIMEOUT_SECONDS"] = "900"
    os.environ["MAX_EMPTY_POLLS"] = "2"
    os.environ["VOXCPM2_MODEL_PATH"] = "/models"  # Model path in Modal volume

    worker = ModalWorker()
    worker.run()


# ==========================================
# 4. Local Entrypoint
# ==========================================
@app.local_entrypoint()
def main():
    print("🚀 Deploying to Modal cloud, allocating T4 node...")
    run_modal_consumer.remote()
    print("✅ Dispatched! Check Modal dashboard for logs.")


if __name__ == "__main__":
    print("Usage: modal run worker/modal_worker.py")
    print("Direct python execution won't trigger cloud compute.")