#!/usr/bin/env python3
"""
CosyVoice 2 HTTP Server for Local GPU Deployment.
Exposes REST API for streaming TTS, zero-shot voice cloning, cross-lingual TTS.

Usage:
    python cosyvoice_server.py

Environment:
    PORT=5020
    MODEL_ID=FunAudioLLM/CosyVoice2-0.5B
    DEVICE=cuda
    MODEL_CACHE_DIR=/app/models/cosyvoice
    MAX_CONCURRENT=2
    ENABLE_VOICE_CLONING=true
    ENABLE_STREAMING=true
    SAMPLE_RATE=24000
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Optional

import torch
import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

PORT = int(os.getenv("PORT", "5020"))
MODEL_ID = os.getenv("MODEL_ID", "FunAudioLLM/CosyVoice2-0.5B")
DEVICE = os.getenv("DEVICE", "cuda")
MODEL_CACHE_DIR = Path(os.getenv("MODEL_CACHE_DIR", "/app/models/cosyvoice"))
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "2"))
ENABLE_VOICE_CLONING = os.getenv("ENABLE_VOICE_CLONING", "true").lower() == "true"
ENABLE_STREAMING = os.getenv("ENABLE_STREAMING", "true").lower() == "true"
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
    reference_audio_bytes: Optional[str] = None  # base64 encoded
    prosody: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    task_id: Optional[str] = None
    stream: bool = False


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
    return f"cosyvoice-{uuid.uuid4().hex[:12]}"


# =============================================================================
# CosyVoice Model Wrapper
# =============================================================================


class CosyVoiceModel:
    """Wrapper for CosyVoice 2 model with thread-safe inference."""

    def __init__(self):
        self.model = None
        self.tokenizer = None
        self._loaded = False
        self._load_lock = threading.Lock()

    def load(self):
        """Load model (thread-safe, called once)."""
        with self._load_lock:
            if self._loaded:
                return
            logger.info(f"Loading CosyVoice2 from {MODEL_ID} on {DEVICE}...")

            # Try to load from ModelScope (Chinese models often hosted there)
            try:
                from modelscope import snapshot_download

                model_dir = MODEL_CACHE_DIR / MODEL_ID.split("/")[-1]
                if not model_dir.exists():
                    logger.info(f"Downloading CosyVoice2 from ModelScope...")
                    snapshot_download(MODEL_ID, cache_dir=str(MODEL_CACHE_DIR))
                model_path = str(model_dir)
            except Exception:
                # Fallback to HF
                model_path = MODEL_ID

            # Import CosyVoice - the actual import path depends on repo structure
            try:
                # CosyVoice2 structure
                from cosyvoice.cli.cosyvoice import CosyVoice2

                self.model = CosyVoice2(
                    model_path,
                    device=DEVICE,
                    load_jit=False,
                    load_onnx=False,
                )
            except ImportError:
                # Try alternative import
                try:
                    from cosyvoice.utils.file_utils import load_model

                    self.model = load_model(model_path, DEVICE)
                except ImportError:
                    logger.error("Could not import CosyVoice. Ensure cosyvoice package is installed.")
                    raise

            self._loaded = True
            logger.info("CosyVoice2 loaded successfully")

    def synthesize(
        self,
        text: str,
        voice_id: str = "default",
        language: str = "zh",
        reference_audio_path: Optional[str] = None,
        prosody: Optional[Dict[str, Any]] = None,
        stream: bool = False,
    ) -> torch.Tensor:
        """Synthesize speech and return audio tensor [channels, samples]."""
        self.load()

        prosody = prosody or {}
        speed = prosody.get("rate", 1.0)
        pitch = prosody.get("pitch", 0)
        volume = prosody.get("volume", 1.0)
        emotion = prosody.get("emotion", "neutral")

        with torch.no_grad():
            # CosyVoice2 inference (pseudo-code - adapt to actual API)
            # The actual CosyVoice2 API may differ
            if hasattr(self.model, "inference_zero_shot"):
                # Zero-shot voice cloning
                if reference_audio_path and ENABLE_VOICE_CLONING:
                    audio = self.model.inference_zero_shot(
                        text=text,
                        prompt_speech_16k=reference_audio_path,
                        prompt_text="",  # optional
                        speed=speed,
                    )
                else:
                    # Pre-trained voice
                    audio = self.model.inference_sft(
                        text=text,
                        spk_id=voice_id,
                        speed=speed,
                    )
            elif hasattr(self.model, "inference"):
                audio = self.model.inference(
                    text=text,
                    prompt_speech_16k=reference_audio_path,
                    speed=speed,
                )
            else:
                # Fallback
                audio = self.model.generate(text=text, speed=speed)

        # Ensure audio is [channels, samples] on CPU
        if isinstance(audio, torch.Tensor):
            if audio.dim() == 1:
                audio = audio.unsqueeze(0)
            audio = audio.cpu()
        else:
            # Convert numpy to tensor
            audio = torch.from_numpy(audio).float()
            if audio.dim() == 1:
                audio = audio.unsqueeze(0)

        return audio

    async def synthesize_stream(
        self,
        text: str,
        voice_id: str = "default",
        language: str = "zh",
        reference_audio_path: Optional[str] = None,
        prosody: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[bytes, None]:
        """Stream synthesized audio chunks."""
        self.load()

        prosody = prosody or {}
        speed = prosody.get("rate", 1.0)

        # CosyVoice streaming (pseudo-code - adapt to actual API)
        if hasattr(self.model, "inference_stream"):
            async for chunk in self.model.inference_stream(
                text=text,
                prompt_speech_16k=reference_audio_path if ENABLE_VOICE_CLONING else None,
                spk_id=voice_id if not reference_audio_path else None,
                speed=speed,
            ):
                # Convert chunk to bytes
                if isinstance(chunk, torch.Tensor):
                    chunk = chunk.cpu().numpy()
                yield chunk.tobytes()
        else:
            # Non-streaming fallback: yield single chunk
            audio = self.synthesize(text, voice_id, language, reference_audio_path, prosody)
            yield audio.cpu().numpy().tobytes()


_model = CosyVoiceModel()


# =============================================================================
# FastAPI App
# =============================================================================

app = FastAPI(title="CosyVoice 2 TTS Server", description="Streaming zero-shot voice cloning TTS API", version="1.0.0")


@app.on_event("startup")
async def startup_event():
    logger.info("CosyVoice server started (model will load on first request)")


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

    if request.stream and ENABLE_STREAMING:
        # For streaming, return immediately with task_id
        # Client will connect to /stream/{task_id}
        with _tasks_lock:
            _tasks[task_id]["status"] = TaskStatus.RUNNING
        background_tasks.add_task(run_streaming, task_id, request)
    else:
        background_tasks.add_task(run_synthesis, task_id, request)

    return SynthesizeResponse(
        task_id=task_id,
        status=TaskStatus.PENDING if not request.stream else TaskStatus.RUNNING,
        message="Task submitted",
    )


@app.get("/stream/{task_id}")
async def stream_audio(task_id: str):
    """Stream audio chunks for a synthesis task."""

    async def generate():
        with _tasks_lock:
            if task_id not in _tasks:
                yield b"ERROR: Task not found"
                return
            task = _tasks[task_id]
            request_data = task["request"]

        try:
            async for chunk in _model.synthesize_stream(
                text=request_data["text"],
                voice_id=request_data.get("voice_id", "default"),
                language=request_data.get("language", "zh"),
                reference_audio_path=request_data.get("reference_audio_path"),
                prosody=request_data.get("prosody", {}),
            ):
                yield chunk
        except Exception as e:
            logger.error(f"Streaming failed for {task_id}: {e}")
            yield f"ERROR: {e}".encode()

    return StreamingResponse(
        generate(),
        media_type="audio/wav",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


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
# Background Synthesis Tasks
# =============================================================================


def run_synthesis(task_id: str, request: SynthesizeRequest):
    """Run synthesis in background thread."""
    output_dir = Path("/app/output") / "cosyvoice"
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


async def run_streaming(task_id: str, request: SynthesizeRequest):
    """Run streaming synthesis (updates task status as chunks are generated)."""
    # For streaming, we just mark as running; actual streaming happens in /stream/{task_id}
    # This background task just ensures the task record exists and is marked RUNNING
    with _tasks_lock:
        _tasks[task_id]["status"] = TaskStatus.RUNNING
        _tasks[task_id]["progress"] = 0.0


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "cosyvoice_server:app",
        host="0.0.0.0",
        port=PORT,
        workers=1,
        log_level="info",
    )
