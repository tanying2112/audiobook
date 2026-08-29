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
    CLONE_PROMPT_KWARG=          # escape hatch: reference-sample parameter name for
                                 # a build whose signature we cannot introspect
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

import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from gpu_tts_common import (
    CloneNotSupportedError,
    normalize_audio_result,
    read_audio_mono,
    resolve_clone_invocation,
    write_wav,
)
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
# Operator escape hatch for builds whose cloning parameter we cannot detect by
# signature (see gpu_tts_common.resolve_clone_invocation).
CLONE_PROMPT_KWARG = os.getenv("CLONE_PROMPT_KWARG", "").strip() or None
CLONE_METHOD = os.getenv("CLONE_METHOD", "").strip() or None

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
    # Transcript of the reference sample: CosyVoice2's inference_zero_shot takes a
    # prompt_text and similarity degrades noticeably without it.
    reference_text: Optional[str] = None
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
                    logger.info("Downloading CosyVoice2 from ModelScope...")
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

    @staticmethod
    def load_prompt_waveform(path: str):
        """Decode the reference sample into CosyVoice's 16 kHz ``[1, N]`` tensor.

        CosyVoice's own ``load_wav`` helper returns exactly this; passing the *path*
        (as this server previously did) raises inside the model, so cloning could
        never have worked.
        """
        import torch

        mono, _ = read_audio_mono(path, target_sr=16000)
        return torch.from_numpy(mono).unsqueeze(0)

    def synthesize(
        self,
        text: str,
        voice_id: str = "default",
        language: str = "zh",
        reference_audio_path: Optional[str] = None,
        reference_text: Optional[str] = None,
        prosody: Optional[Dict[str, Any]] = None,
        stream: bool = False,
    ):
        """Synthesize speech, returning float32 audio shaped ``[channels, samples]``.

        With a reference sample this performs a real zero-shot clone: the decoded 16 kHz
        prompt waveform (plus the prompt transcript when the build accepts one) is handed
        to the model. If the build exposes no cloning entry point the call raises
        :class:`CloneNotSupportedError` instead of silently rendering a preset voice.
        """
        import torch

        self.load()

        prosody = prosody or {}
        speed = float(prosody.get("rate", 1.0) or 1.0)

        with torch.no_grad():
            if reference_audio_path and ENABLE_VOICE_CLONING:
                invocation = resolve_clone_invocation(
                    self.model,
                    text=text,
                    reference_audio_path=reference_audio_path,
                    reference_text=reference_text,
                    speed=speed,
                    load_prompt=self.load_prompt_waveform,
                    override_kwarg=CLONE_PROMPT_KWARG,
                    override_method=CLONE_METHOD,
                )
                logger.info(
                    "Zero-shot clone: %s(%s=<%s>) ref=%s prompt_text=%s",
                    invocation.method_name,
                    invocation.prompt_kwarg,
                    "waveform" if invocation.prompt_is_tensor else "path",
                    reference_audio_path,
                    bool(reference_text),
                )
                audio = invocation.call(self.model)
            elif reference_audio_path and not ENABLE_VOICE_CLONING:
                raise CloneNotSupportedError(
                    "Clone requested but ENABLE_VOICE_CLONING=false on this server; "
                    "refusing to return a preset-voice rendition as a clone."
                )
            elif hasattr(self.model, "inference_sft"):
                audio = self.model.inference_sft(tts_text=text, spk_id=voice_id, speed=speed)
            else:
                audio = self.model.generate(text=text, speed=speed)

        return normalize_audio_result(audio)

    async def synthesize_stream(
        self,
        text: str,
        voice_id: str = "default",
        language: str = "zh",
        reference_audio_path: Optional[str] = None,
        reference_text: Optional[str] = None,
        prosody: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[bytes, None]:
        """Stream synthesized audio chunks."""
        import torch

        self.load()

        prosody = prosody or {}
        speed = prosody.get("rate", 1.0)

        if hasattr(self.model, "inference_stream"):
            stream_kwargs: Dict[str, Any] = {"text": text, "speed": speed}
            if reference_audio_path and ENABLE_VOICE_CLONING:
                stream_kwargs["prompt_speech_16k"] = self.load_prompt_waveform(reference_audio_path)
                if reference_text:
                    stream_kwargs["prompt_text"] = reference_text
            else:
                stream_kwargs["spk_id"] = voice_id
            async for chunk in self.model.inference_stream(**stream_kwargs):
                if isinstance(chunk, torch.Tensor):
                    chunk = chunk.cpu().numpy()
                yield chunk.tobytes()
        else:
            # Non-streaming fallback: yield a single chunk (still a real clone when a
            # reference sample was supplied — synthesize() refuses to fake one).
            audio = self.synthesize(text, voice_id, language, reference_audio_path, reference_text, prosody)
            yield audio.tobytes()


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
    import torch

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
                reference_text=request_data.get("reference_text"),
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
    output_dir = Path(os.getenv("AUDIO_OUTPUT_DIR", "/app/output")) / "cosyvoice"
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
            reference_text=request.reference_text,
            prosody=request.prosody,
        )

        with _tasks_lock:
            _tasks[task_id]["progress"] = 0.8

        # Save audio
        output_path = output_dir / f"{task_id}.wav"
        write_wav(str(output_path), audio, SAMPLE_RATE)

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
                # Honest capability report: True only when the reference sample was
                # actually handed to the model for this task.
                "cloned": bool(request.reference_audio_path) and ENABLE_VOICE_CLONING,
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
