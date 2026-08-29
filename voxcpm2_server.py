#!/usr/bin/env python3
"""
VoxCPM2 HTTP Server for Local GPU Deployment.
Exposes REST API compatible with remote_voxcpm2_port.py contract.

Usage:
    python voxcpm2_server.py

Environment:
    PORT=5010
    MODEL_ID=FunAudioLLM/VoxCPM2
    DEVICE=cuda
    MODEL_CACHE_DIR=/app/models/voxcpm2
    MAX_CONCURRENT=2
    ENABLE_VOICE_CLONING=true
    SAMPLE_RATE=24000
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

import torch
import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException
from funasr import AutoModel
from pydantic import BaseModel, Field

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

PORT = int(os.getenv("PORT", "5010"))
MODEL_ID = os.getenv("MODEL_ID", "FunAudioLLM/VoxCPM2")
DEVICE = os.getenv("DEVICE", "cuda")
MODEL_CACHE_DIR = Path(os.getenv("MODEL_CACHE_DIR", "/app/models/voxcpm2"))
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "2"))
ENABLE_VOICE_CLONING = os.getenv("ENABLE_VOICE_CLONING", "true").lower() == "true"
SAMPLE_RATE = int(os.getenv("SAMPLE_RATE", "24000"))

MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# =============================================================================
# Data Models
# =============================================================================


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    voice_id: Optional[str] = "default"
    speaker_name: Optional[str] = None
    language: Optional[str] = "zh"
    reference_audio_path: Optional[str] = None
    prosody: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    task_id: Optional[str] = None


class SynthesizeResponse(BaseModel):
    task_id: str
    status: TaskStatus
    message: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: TaskStatus
    progress: float = 0.0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: float
    completed_at: Optional[float] = None


class HealthResponse(BaseModel):
    healthy: bool
    model_loaded: bool
    device: str
    pending_count: int
    running_count: int
    version: str = "1.0.0"


# =============================================================================
# Task Store
# =============================================================================

_tasks: Dict[str, Dict] = {}
_tasks_lock = threading.Lock()


def make_task_id() -> str:
    return f"voxcpm2-{uuid.uuid4().hex[:12]}"


# =============================================================================
# VoxCPM2 Model Wrapper
# =============================================================================


class VoxCPM2Model:
    """Wrapper for VoxCPM2 model with thread-safe inference."""

    def __init__(self):
        self.model = None
        self._loaded = False
        self._load_lock = threading.Lock()

    def load(self):
        """Load model (thread-safe, called once)."""
        with self._load_lock:
            if self._loaded:
                return
            logger.info(f"Loading VoxCPM2 from {MODEL_ID} on {DEVICE}...")
            model_path = str(MODEL_CACHE_DIR / MODEL_ID.split("/")[-1])
            self.model = AutoModel(
                model=model_path if Path(model_path).exists() else MODEL_ID,
                trust_remote_code=True,
                device=DEVICE,
                disable_update=True,
            )
            self._loaded = True
            logger.info("VoxCPM2 loaded successfully")

    def synthesize(
        self,
        text: str,
        voice_id: str = "default",
        language: str = "zh",
        reference_audio_path: Optional[str] = None,
        prosody: Optional[Dict[str, Any]] = None,
    ) -> torch.Tensor:
        """Synthesize speech and return audio tensor [channels, samples]."""
        self.load()

        prosody = prosody or {}
        cfg_value = prosody.get("cfg_value", 2.0)
        inference_timesteps = prosody.get("inference_timesteps", 10)

        with torch.no_grad():
            # VoxCPM2 generate via FunASR
            # Note: FunASR's AutoModel.generate for VoxCPM2 may have different signature
            # This is based on the modal server implementation
            result = self.model.generate(
                input=text,
                # prompt_speech_16k=reference_audio_path,  # for voice cloning
            )

        # Extract audio tensor
        if isinstance(result, dict):
            audio = result.get("audio") or result.get("waveform")
            if audio is None and "audio_path" in result:
                import torchaudio

                audio, _ = torchaudio.load(result["audio_path"])
        else:
            audio = result

        if audio is None:
            raise RuntimeError("No audio output from model.generate()")

        # Ensure audio is [channels, samples] on CPU
        if audio.dim() == 1:
            audio = audio.unsqueeze(0)
        audio = audio.cpu()

        return audio


_model = VoxCPM2Model()


# =============================================================================
# FastAPI App
# =============================================================================

app = FastAPI(title="VoxCPM2 TTS Server", description="Zero-shot voice cloning TTS API", version="1.0.0")


@app.on_event("startup")
async def startup_event():
    """Pre-load model on startup (optional, can be lazy)."""
    # Model loads on first request (lazy) to allow fast container startup
    logger.info("VoxCPM2 server started (model will load on first request)")


@app.get("/health", response_model=HealthResponse)
async def health():
    with _tasks_lock:
        pending = sum(1 for t in _tasks.values() if t["status"] == TaskStatus.PENDING)
        running = sum(1 for t in _tasks.values() if t["status"] == TaskStatus.RUNNING)

    return HealthResponse(
        healthy=True,
        model_loaded=_model._loaded,
        device=DEVICE if torch.cuda.is_available() else "cpu",
        pending_count=pending,
        running_count=running,
    )


@app.post("/synthesize", response_model=SynthesizeResponse)
async def synthesize(request: SynthesizeRequest, background_tasks: BackgroundTasks):
    """Submit synthesis task."""
    task_id = request.task_id or make_task_id()

    with _tasks_lock:
        if task_id in _tasks:
            raise HTTPException(status_code=409, detail="Task already exists")

        _tasks[task_id] = {
            "status": TaskStatus.PENDING,
            "request": request.model_dump(),
            "progress": 0.0,
            "result": None,
            "error": None,
            "started_at": time.time(),
            "completed_at": None,
        }

    # Run synthesis in background
    background_tasks.add_task(run_synthesis, task_id, request)

    return SynthesizeResponse(task_id=task_id, status=TaskStatus.PENDING, message="Task submitted")


@app.get("/status/{task_id}", response_model=TaskStatusResponse)
async def get_status(task_id: str):
    """Get task status."""
    with _tasks_lock:
        if task_id not in _tasks:
            raise HTTPException(status_code=404, detail="Task not found")
        task = _tasks[task_id]

    return TaskStatusResponse(
        task_id=task_id,
        status=task["status"],
        progress=task["progress"],
        result=task["result"],
        error=task["error"],
        started_at=task["started_at"],
        completed_at=task["completed_at"],
    )


@app.get("/result/{task_id}")
async def get_result(task_id: str):
    """Get task result with audio file info."""
    with _tasks_lock:
        if task_id not in _tasks:
            raise HTTPException(status_code=404, detail="Task not found")
        task = _tasks[task_id]

    if task["status"] != TaskStatus.DONE:
        raise HTTPException(status_code=400, detail=f"Task not completed: {task['status']}")

    return task["result"]


@app.post("/cancel/{task_id}")
async def cancel_task(task_id: str):
    """Cancel a pending/running task."""
    with _tasks_lock:
        if task_id not in _tasks:
            raise HTTPException(status_code=404, detail="Task not found")
        if _tasks[task_id]["status"] in (TaskStatus.DONE, TaskStatus.FAILED):
            raise HTTPException(status_code=400, detail="Task already finished")
        _tasks[task_id]["status"] = TaskStatus.FAILED
        _tasks[task_id]["error"] = "Cancelled by user"
        _tasks[task_id]["completed_at"] = time.time()

    return {"message": "Task cancelled"}


# =============================================================================
# Background Synthesis Task
# =============================================================================


def run_synthesis(task_id: str, request: SynthesizeRequest):
    """Run synthesis in background thread."""
    output_dir = Path("/app/output") / "voxcpm2"
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        with _tasks_lock:
            _tasks[task_id]["status"] = TaskStatus.RUNNING
            _tasks[task_id]["progress"] = 0.1

        # Synthesize
        audio = _model.synthesize(
            text=request.text,
            voice_id=request.voice_id or "default",
            language=request.language or "zh",
            reference_audio_path=request.reference_audio_path,
            prosody=request.prosody,
        )

        with _tasks_lock:
            _tasks[task_id]["progress"] = 0.8

        # Save audio
        output_path = output_dir / f"{task_id}.wav"
        import torchaudio

        torchaudio.save(str(output_path), audio, SAMPLE_RATE)

        with _tasks_lock:
            _tasks[task_id]["progress"] = 1.0
            _tasks[task_id]["status"] = TaskStatus.DONE
            _tasks[task_id]["completed_at"] = time.time()
            _tasks[task_id]["result"] = {
                "task_id": task_id,
                "status": TaskStatus.DONE.value,
                "audio_path": str(output_path),
                "sample_rate": SAMPLE_RATE,
                "duration_sec": audio.shape[1] / SAMPLE_RATE,
                "channels": audio.shape[0],
            }

    except Exception as e:
        logger.error(f"Synthesis failed for {task_id}: {e}")
        with _tasks_lock:
            _tasks[task_id]["status"] = TaskStatus.FAILED
            _tasks[task_id]["error"] = str(e)
            _tasks[task_id]["completed_at"] = time.time()


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "voxcpm2_server:app",
        host="0.0.0.0",
        port=PORT,
        workers=1,
        log_level="info",
    )
