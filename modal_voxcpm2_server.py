#!/usr/bin/env python3
"""
Modal HTTP Server for VoxCPM2 TTS - Exposes REST API for Audiobook Studio.

Deploys a FastAPI app on Modal GPU (T4) exposing:
- POST /synthesize - Submit TTS task
- GET /status/{task_id} - Check task status  
- GET /result/{task_id} - Get result with audio URL
- POST /cancel/{task_id} - Cancel task
- GET /health - Health check

This implements the API contract expected by remote_voxcpm2_port.py

Usage:
    modal deploy modal_voxcpm2_server.py
    # Or for development:
    modal serve modal_voxcpm2_server.py

Prerequisites:
    modal secret create audiobook-config HF_TOKEN=<your_hf_token>
    modal secret create audiobook-config REDIS_HOST=... REDIS_PORT=... REDIS_AUTH=... R2_*=...
"""
from __future__ import annotations

import os
import uuid
import time
import threading
from pathlib import Path
from typing import Any, Dict, Optional
from dataclasses import dataclass, field
from enum import Enum

import modal

# =============================================================================
# Modal App Configuration
# =============================================================================

app = modal.App("voxcpm2-tts-server")

# GPU: T4 is cost-effective and widely available across providers
GPU_TYPE = os.getenv("MODAL_GPU", "T4").upper()

# Model weights cached in Modal volume (persists across container restarts)
MODEL_VOLUME = modal.Volume.from_name("voxcpm2-model-weights", create_if_missing=True)
MODEL_DIR = Path("/models")

# Secrets: HF token for ModelScope download (via huggingface_hub)
# Create via: modal secret create audiobook-config HF_TOKEN=xxx REDIS_HOST=xxx ...
SECRETS = [modal.Secret.from_name("audiobook-config")]

# Container image with all dependencies
IMAGE = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg", "libsndfile1", "git")
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
# Data Models (matching remote_voxcpm2_port.py contract)
# =============================================================================


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


# =============================================================================
# Modal Class: VoxCPM2 HTTP Server
# =============================================================================


@app.cls(
    image=IMAGE,
    gpu=GPU_TYPE,
    secrets=SECRETS,
    volumes={str(MODEL_DIR): MODEL_VOLUME},
    scaledown_window=300,  # Keep warm for 5 min after last request
    min_containers=0,  # Scale to zero when idle (free tier friendly)
    max_containers=2,  # Max concurrent containers
    timeout=300,
    concurrency_limit=10,
)
class VoxCPM2Server:
    """VoxCPM2 TTS HTTP Server."""

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

        # In-memory task store
        self._tasks: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _make_task_id(self) -> str:
        return f"voxcpm2-{uuid.uuid4().hex[:12]}"

    @modal.method()
    def health(self):
        """Health check endpoint."""
        import torch

        with self._lock:
            pending = sum(1 for t in self._tasks.values() if t["status"] == TaskStatus.PENDING)
            running = sum(1 for t in self._tasks.values() if t["status"] == TaskStatus.RUNNING)

        return {
            "healthy": True,
            "model_loaded": hasattr(self, "model"),
            "device": "cuda" if torch.cuda.is_available() else "cpu",
            "pending_count": pending,
            "running_count": running,
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
            "prosody": {"rate": 1.0, "pitch": 0, "volume": 1.0, "emotion": "neutral", "cfg_value": 2.0, "inference_timesteps": 10},
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
        with self._lock:
            if task_id in self._tasks:
                return {"error": "Task already exists"}, 409

            self._tasks[task_id] = {
                "status": TaskStatus.PENDING,
                "request": request,
                "progress": 0.0,
                "result": None,
                "error": None,
                "started_at": time.time(),
            }

        # Run synchronously for MVP; can be made async with modal.background_task
        try:
            with self._lock:
                self._tasks[task_id]["status"] = TaskStatus.RUNNING
                self._tasks[task_id]["progress"] = 0.1

            import torchaudio
            import torch

            with self._lock:
                self._tasks[task_id]["progress"] = 0.3

            prosody = request.get("prosody", {})
            cfg_value = prosody.get("cfg_value", 2.0)
            inference_timesteps = prosody.get("inference_timesteps", 10)

            with self._lock:
                self._tasks[task_id]["progress"] = 0.5

            # Call FunASR generate method for VoxCPM2
            with torch.no_grad():
                result = self.model.generate(
                    input=text,
                    # VoxCPM2 specific params:
                    # prompt_speech_16k=...,  # for voice cloning if reference_audio provided
                )

            with self._lock:
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

            with self._lock:
                self._tasks[task_id]["progress"] = 0.9

            # Save to temp file
            sample_rate = 24000  # VoxCPM2 default
            output_path = f"/tmp/{task_id}.wav"
            torchaudio.save(output_path, audio, sample_rate)

            with self._lock:
                self._tasks[task_id]["progress"] = 1.0
                self._tasks[task_id]["status"] = TaskStatus.DONE
                self._tasks[task_id]["result"] = {
                    "audio_path": output_path,
                    "duration_ms": int(audio.shape[1] / sample_rate * 1000),
                    "sample_rate": sample_rate,
                }
                self._tasks[task_id]["completed_at"] = time.time()

        except Exception as e:
            with self._lock:
                self._tasks[task_id]["status"] = TaskStatus.FAILED
                self._tasks[task_id]["error"] = str(e)
                print(f"Inference error for task {task_id}: {e}")

        with self._lock:
            task = self._tasks[task_id]

        return {
            "task_id": task_id,
            "status": task["status"],
            "message": "Task submitted" if task["status"] == TaskStatus.PENDING else "Task completed",
        }

    @modal.method()
    def status(self, task_id: str):
        """Get task status."""
        with self._lock:
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
        with self._lock:
            task = self._tasks.get(task_id)

        if not task:
            return {"error": "Task not found"}, 404

        if task["status"] not in (TaskStatus.DONE, TaskStatus.FAILED):
            return {"error": f"Task not complete (status: {task['status']})"}, 400

        if task["status"] == TaskStatus.FAILED:
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

    @modal.method()
    def cancel(self, task_id: str):
        """Request cancellation of a pending/running task."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return {"task_id": task_id, "cancelled": False, "message": "Not found"}
            if task["status"] in (TaskStatus.DONE, TaskStatus.FAILED):
                return {"task_id": task_id, "cancelled": False, "message": "Already terminal"}
            task["status"] = TaskStatus.FAILED
            task["error"] = "Cancelled"

        return {"task_id": task_id, "cancelled": True, "message": "Cancellation requested"}


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
    service = VoxCPM2Server()

    @fastapi_app.get("/health")
    async def health():
        return service.health.remote()

    @fastapi_app.post("/synthesize")
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

    @fastapi_app.post("/cancel/{task_id}")
    async def cancel_task(task_id: str):
        result = service.cancel.remote(task_id)
        return result

    return fastapi_app


# =============================================================================
# Local Entrypoint
# =============================================================================

if __name__ == "__main__":
    print("This script is meant to be deployed via Modal:")
    print("  modal deploy modal_voxcpm2_server.py")
    print("  modal serve modal_voxcpm2_server.py  # for dev")
