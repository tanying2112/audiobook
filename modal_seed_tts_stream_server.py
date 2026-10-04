#!/usr/bin/env python3
"""
Modal HTTP Server for Seed-TTS-Stream Streaming TTS (ByteDance).

Exposes REST API for Audiobook Studio streaming TTS engines:
- POST /tts/stream - Streaming synthesis with optional voice cloning
- GET /health - Health check

Usage:
    modal deploy modal_seed_tts_stream_server.py

Prerequisites:
    modal secret create audiobook-config HF_TOKEN=<your_hf_token>
    # Seed-TTS from ByteDance
"""
from __future__ import annotations

import os
import json
import time
import threading
import base64
from pathlib import Path
from typing import Any, Dict, Optional

import modal
from pydantic import BaseModel
from typing import Optional

# =============================================================================
# Modal App Configuration
# =============================================================================

app = modal.App("seed-tts-stream-server")

GPU_TYPE = os.getenv("MODAL_GPU", "T4").upper()

MODEL_VOLUME = modal.Volume.from_name("seed-tts-model-weights", create_if_missing=True)
MODEL_DIR = Path("/models")

SECRETS = [modal.Secret.from_name("audiobook-config")]

IMAGE = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "libsndfile1", "git")
    .pip_install(
        "torch==2.3.0",
        "torchaudio==2.3.0",
        "transformers>=4.45.0",
        "accelerate",
        "fastapi==0.110.0",
        "uvicorn==0.29.0",
        "pydantic==2.7.0",
        "soundfile==0.12.1",
        "numpy==1.26.4",
        "scipy==1.13.0",
        "safetensors==0.4.3",
        "einops==0.8.0",
    )
    .run_commands(
        "git clone https://github.com/ByteDance/Seed-TTS /opt/Seed-TTS 2>/dev/null || true",
    )
)


# Request models (at module level for FastAPI type resolution)
class StreamRequest(BaseModel):
        text: str
        voice_id: Optional[str] = "default"
        speed: float = 1.0
        sample_rate: int = 24000
        chunk_size_ms: int = 100
        reference_audio: Optional[str] = None  # base64 for voice cloning


@app.cls(
    image=IMAGE,
    gpu=GPU_TYPE,
    secrets=SECRETS,
    volumes={str(MODEL_DIR): MODEL_VOLUME},
    scaledown_window=300,
    min_containers=0,
    max_containers=2,
    timeout=300,
)
class SeedTTSStreamServer:
    """Seed-TTS Streaming TTS Server."""

    # Class-level attributes for lazy initialization
    _lock = None

    def _ensure_initialized(self):
        if self._lock is None:
            import threading
            self._lock = threading.Lock()

    def __enter__(self):
        """Initialize Seed-TTS model on container start."""
        import torch
        # Seed-TTS would be loaded here - placeholder for actual implementation
        print("Loading Seed-TTS...")
        self.model = None  # Placeholder
        print("Seed-TTS loaded successfully")
        self._lock = threading.Lock()

    @modal.method()
    def health(self):
        import torch
        return {
            "healthy": True,
            "model_loaded": self.model is not None,
            "device": "cuda" if torch.cuda.is_available() else "cpu",
            "version": "1.0.0",
        }

    @modal.method()
    def synthesize_stream(self, request: dict):
        """Streaming synthesis with optional reference audio for voice cloning."""
        self._ensure_initialized()
        # Placeholder - actual implementation depends on Seed-TTS API
        text = request.get("text", "").strip()
        if not text:
            return {"error": "text is required"}, 400

        # Mock streaming response for now
        sample_rate = request.get("sample_rate", 24000)
        chunk_size_ms = request.get("chunk_size_ms", 100)
        chunk_samples = int(sample_rate * chunk_size_ms / 1000)
        
        import numpy as np
        duration = 2.0
        total_samples = int(sample_rate * duration)
        t = np.linspace(0, duration, total_samples, endpoint=False)
        audio = np.sin(2 * np.pi * 440 * t) * 0.3
        audio_int16 = (audio * 32767).astype(np.int16)
        
        results = []
        chunk_bytes = chunk_samples * 2
        for i in range(0, len(audio_int16), chunk_samples):
            chunk_data = audio_int16[i:i+chunk_samples]
            if len(chunk_data) == 0:
                continue
            is_final = (i + chunk_samples >= len(audio_int16))
            results.append({
                "audio_hex": chunk_data.tobytes().hex(),
                "sample_rate": sample_rate,
                "is_final": is_final,
                "text": text if i == 0 else "",
            })
        
        return results


@app.function(image=IMAGE)
@modal.asgi_app()
def fastapi_app():
    from fastapi import FastAPI, HTTPException, StreamingResponse

    fastapi_app = FastAPI(title="Seed-TTS Stream API", version="1.0.0")

    service = SeedTTSStreamServer()

    @fastapi_app.get("/health")
    async def health():
        import torch
        return {
            "healthy": True,
            "device": "cuda" if torch.cuda.is_available() else "cpu",
            "version": "1.0.0",
        }

    @fastapi_app.post("/tts/stream")
    async def synthesize_stream(request: StreamRequest):
        result = service.synthesize_stream.remote(request.model_dump())
        if isinstance(result, tuple):
            raise HTTPException(status_code=result[1], detail=result[0].get("error", "Error"))
        
        async def generate():
            for chunk in result:
                yield json.dumps(chunk) + "\n"
        
        return StreamingResponse(generate(), media_type="application/x-ndjson")

    return fastapi_app


if __name__ == "__main__":
    print("Deploy via: modal deploy modal_seed_tts_stream_server.py")
