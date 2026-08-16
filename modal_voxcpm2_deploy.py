#!/usr/bin/env python3
"""
Modal deployment for VoxCPM2 TTS inference service.

Deploys a FastAPI app on Modal GPU (T4 by default) exposing:
- POST /v1/tts - Synthesize speech with VoxCPM2
- GET /health - Health check
- GET /status/{task_id} - Task status
- GET /result/{task_id} - Task result with audio URL

Usage:
    modal deploy modal_voxcpm2_deploy.py
    # Or for development:
    modal serve modal_voxcpm2_deploy.py

Prerequisites:
    modal secret create voxcpm2-secrets HF_TOKEN=<your_hf_token>
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import modal

# =============================================================================
# Modal App Configuration
# =============================================================================

app = modal.App("voxcpm2-inference")

# GPU: T4 is cost-effective and widely available across providers
# Can be overridden via env var: MODAL_GPU=T4|V100|A10G|H100
GPU_TYPE = os.getenv("MODAL_GPU", "T4").upper()

# Model weights cached in Modal volume (persists across container restarts)
MODEL_VOLUME = modal.Volume.from_name("voxcpm2-model-weights", create_if_missing=True)
MODEL_DIR = Path("/models")

# Secrets: HF token for ModelScope download (via huggingface_hub)
# Create via: modal secret create voxcpm2-secrets HF_TOKEN=xxx
SECRETS = [modal.Secret.from_name("voxcpm2-secrets")]

# Container image with all dependencies
IMAGE = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "ffmpeg", "libsndfile1")
    .pip_install(
        "torch==2.3.0",
        "torchaudio==2.3.0",
        "accelerate==0.30.1",
        "transformers==4.41.1",
        "huggingface_hub==0.23.0",
        "fastapi==0.110.0",
        "uvicorn==0.29.0",
        "pydantic==2.7.0",
        "soundfile==0.12.1",
        "numpy==1.26.4",
        "scipy==1.13.0",
        "safetensors==0.4.3",
        "einops==0.8.0",
        "funasr==1.0.5",
        "modelscope==1.9.5",
    )
    .run_commands(
        "git clone https://github.com/FunAudioLLM/VoxCPM2 /opt/VoxCPM2 2>/dev/null || true",
    )
)

# =============================================================================
# Modal Function: Download Model Weights (runs once at deploy time)
# =============================================================================


@app.function(
    image=IMAGE,
    volumes={str(MODEL_DIR): MODEL_VOLUME},
    secrets=SECRETS,
    timeout=600,
)
def download_model_weights():
    """Download VoxCPM2 weights from ModelScope to Modal volume."""
    import subprocess
    import sys

    target_dir = Path("/models/FunAudioLLM/VoxCPM2")
    target_dir.mkdir(parents=True, exist_ok=True)

    # Check if already downloaded
    if (target_dir / "config.json").exists():
        print(f"Model already exists at {target_dir}")
        return str(target_dir)

    print("Downloading VoxCPM2 from ModelScope (FunAudioLLM/VoxCPM2)...")
    hf_token = os.environ.get("HF_TOKEN", "")
    if hf_token:
        subprocess.run(["huggingface-cli", "login", "--token", hf_token], check=False)

    # Use modelscope to download (HF repo is a placeholder)
    cmd = [
        sys.executable,
        "-m",
        "modelscope.hub.snapshot_download",
        "--repo-id",
        "FunAudioLLM/VoxCPM2",
        "--local-dir",
        str(target_dir),
    ]
    if hf_token:
        cmd.extend(["--token", hf_token])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Download failed: {result.stderr}")
        raise RuntimeError(f"ModelScope download failed: {result.stderr}")

    print(f"Model downloaded to {target_dir}")
    return str(target_dir)


# =============================================================================
# VoxCPM2 Service Class (Internal - called via FastAPI)
# =============================================================================


@app.cls(
    image=IMAGE,
    gpu=GPU_TYPE,
    secrets=SECRETS,
    volumes={str(MODEL_DIR): MODEL_VOLUME},
    scaledown_window=60,  # Keep warm for 60s after last request
    min_containers=0,  # Scale to zero when idle
    max_containers=3,  # Max concurrent containers
    timeout=300,
)
class VoxCPM2Service:
    """VoxCPM2 TTS inference service."""

    def __enter__(self):
        """Initialize model on container start (cold start)."""
        import torch
        from funasr import AutoModel

        model_path = str(MODEL_DIR / "FunAudioLLM" / "VoxCPM2")
        print(f"Loading VoxCPM2 from {model_path}...")

        # Load via FunASR AutoModel (handles VoxCPM2 architecture)
        self.model = AutoModel(
            model=model_path,
            trust_remote_code=True,
            device="cuda",
            disable_update=True,
        )
        print("VoxCPM2 loaded successfully")

        # In-memory task store (MVP; replace with Redis for production)
        self._tasks: dict[str, dict] = {}

    def _make_task_id(self) -> str:
        return f"voxcpm2-{uuid.uuid4().hex[:12]}"

    @modal.method()
    def health(self):
        """Health check endpoint."""
        import torch

        return {
            "healthy": True,
            "model_loaded": hasattr(self, "model"),
            "device": "cuda" if torch.cuda.is_available() else "cpu",
            "pending_count": sum(
                1 for t in self._tasks.values() if t["status"] == "PENDING"
            ),
            "running_count": sum(
                1 for t in self._tasks.values() if t["status"] == "RUNNING"
            ),
            "version": "1.0.0",
        }

    @modal.method()
    def synthesize(self, request: dict):
        """
        Synthesize speech with VoxCPM2.

        Request:
        {
            "task_id": "optional-custom-id",
            "text": "text to synthesize",
            "voice_id": "speaker_id",
            "speaker_name": "optional name",
            "language": "zh",
            "reference_audio_path": "optional path to reference audio",
            "prosody": {"rate": 1.0, "pitch": 0, "volume": 1.0, "emotion": "neutral"},
            "metadata": {}
        }

        Response:
        {
            "task_id": "voxcpm2-xxx",
            "status": "PENDING|RUNNING|DONE|FAILED",
            "message": "Task submitted"
        }
        """
        text = request.get("text", "").strip()
        if not text:
            return {"error": "text is required"}, 400

        voice_id = request.get("voice_id") or request.get("speaker_name", "default")
        task_id = request.get("task_id") or self._make_task_id()

        # Create task record
        self._tasks[task_id] = {
            "status": "PENDING",
            "request": request,
            "progress": 0.0,
            "result": None,
            "error": None,
        }

        # Run synchronously for MVP; Phase 2: use modal.background_task for async
        try:
            self._tasks[task_id]["status"] = "RUNNING"
            self._tasks[task_id]["progress"] = 0.1

            import torchaudio
            import torch

            self._tasks[task_id]["progress"] = 0.3

            # Call FunASR generate method for VoxCPM2
            with torch.no_grad():
                result = self.model.generate(
                    input=text,
                    # VoxCPM2 specific params (may vary by version):
                    # prompt_speech_16k=...,  # for voice cloning if reference_audio provided
                )

            self._tasks[task_id]["progress"] = 0.7

            # Extract audio tensor
            if isinstance(result, dict):
                audio = result.get("audio") or result.get("waveform")
                if audio is None and "audio_path" in result:
                    audio, _ = torchaudio.load(result["audio_path"])
            else:
                audio = result

            if audio is None:
                raise RuntimeError("No audio output from model.generate()")

            # Ensure audio is [channels, samples] on CPU
            if audio.dim() == 1:
                audio = audio.unsqueeze(0)
            audio = audio.cpu()

            self._tasks[task_id]["progress"] = 0.9

            # Save to temp file
            sample_rate = 24000  # VoxCPM2 default
            output_path = f"/tmp/{task_id}.wav"
            torchaudio.save(output_path, audio, sample_rate)

            self._tasks[task_id]["progress"] = 1.0
            self._tasks[task_id]["status"] = "DONE"
            self._tasks[task_id]["result"] = {
                "audio_path": output_path,
                "duration_ms": int(audio.shape[1] / sample_rate * 1000),
                "sample_rate": sample_rate,
            }

        except Exception as e:
            self._tasks[task_id]["status"] = "FAILED"
            self._tasks[task_id]["error"] = str(e)
            print(f"Inference error for task {task_id}: {e}")

        return {
            "task_id": task_id,
            "status": self._tasks[task_id]["status"],
            "message": (
                "Task submitted"
                if self._tasks[task_id]["status"] == "PENDING"
                else "Task completed"
            ),
        }

    @modal.method()
    def status(self, task_id: str):
        """Get task status."""
        task = self._tasks.get(task_id)
        if not task:
            return {"error": "Task not found"}, 404

        return {
            "task_id": task_id,
            "status": task["status"],
            "progress": task["progress"],
            "error_message": task["error"],
        }

    @modal.method()
    def result(self, task_id: str):
        """Get task result with audio URL."""
        task = self._tasks.get(task_id)
        if not task:
            return {"error": "Task not found"}, 404

        if task["status"] not in ("DONE", "FAILED"):
            return {"error": f"Task not complete (status: {task['status']})"}, 400

        if task["status"] == "FAILED":
            return {
                "task_id": task_id,
                "status": "FAILED",
                "error_message": task["error"],
            }

        result = task["result"]
        if not result:
            return {"error": "No result available"}, 500

        return {
            "task_id": task_id,
            "status": "DONE",
            "audio_url": f"file://{result['audio_path']}",
            "audio_path": result["audio_path"],
            "duration_ms": result["duration_ms"],
            "sample_rate": result["sample_rate"],
        }


# =============================================================================
# FastAPI App (exposed via @modal.fastapi_endpoint)
# =============================================================================


@modal.fastapi_endpoint()
def fastapi_app():
    """ASGI app for Modal deployment."""
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel
    from typing import Optional

    fastapi_app = FastAPI(title="VoxCPM2 TTS API", version="1.0.0")

    # Request models
    class TTSRequest(BaseModel):
        task_id: Optional[str] = None
        text: str
        voice_id: Optional[str] = None
        speaker_name: Optional[str] = None
        language: str = "zh"
        reference_audio_path: Optional[str] = None
        prosody: Optional[dict] = None
        metadata: Optional[dict] = None

    # Get service instance
    service = VoxCPM2Service()

    @fastapi_app.get("/health")
    async def health():
        return service.health.remote()

    @fastapi_app.post("/v1/tts")
    async def synthesize(request: TTSRequest):
        req_dict = request.model_dump(exclude_none=True)
        result = service.synthesize.remote(req_dict)
        return result

    @fastapi_app.get("/status/{task_id}")
    async def get_status(task_id: str):
        result = service.status.remote(task_id)
        if isinstance(result, tuple) and result[1] == 404:
            raise HTTPException(status_code=404, detail="Task not found")
        return result

    @fastapi_app.get("/result/{task_id}")
    async def get_result(task_id: str):
        result = service.result.remote(task_id)
        if isinstance(result, tuple):
            if result[1] == 404:
                raise HTTPException(status_code=404, detail="Task not found")
            elif result[1] == 400:
                raise HTTPException(status_code=400, detail=result[0].get("error", "Task not complete"))
            elif result[1] == 500:
                raise HTTPException(status_code=500, detail=result[0].get("error", "No result"))
        return result

    return fastapi_app


# =============================================================================
# Local Entrypoint
# =============================================================================

if __name__ == "__main__":
    print("This script is meant to be deployed via Modal:")
    print("  modal deploy modal_voxcpm2_deploy.py")
    print("  modal serve modal_voxcpm2_deploy.py  # for dev")