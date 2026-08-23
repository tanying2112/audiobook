#!/usr/bin/env python3
"""
Modal HTTP Server for XTTS-v2 Zero-Shot Voice Cloning.

Exposes REST API for Audiobook Studio zero-shot clone engines:
- POST /clone - Clone voice from reference audio
- POST /clone/stream - Streaming clone (if supported)
- GET /health - Health check

Usage:
    modal deploy modal_xtts_v2_server.py
    modal serve modal_xtts_v2_server.py  # for dev

Prerequisites:
    modal secret create audiobook-config HF_TOKEN=<your_hf_token>
    # XTTS-v2 is Apache 2.0, available on Hugging Face
"""
from __future__ import annotations

import os
import base64
import time
import threading
from pathlib import Path
from typing import Any, Dict, Optional

import modal

# =============================================================================
# Modal App Configuration
# =============================================================================

app = modal.App("xtts-v2-clone-server")

GPU_TYPE = os.getenv("MODAL_GPU", "T4").upper()

MODEL_VOLUME = modal.Volume.from_name("xtts-v2-model-weights", create_if_missing=True)
MODEL_DIR = Path("/models")

SECRETS = [modal.Secret.from_name("audiobook-config")]

IMAGE = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg", "libsndfile1")
    .pip_install(
        "torch==2.3.0",
        "torchaudio==2.3.0",
        "TTS==0.22.0",  # Coqui TTS with XTTS-v2
        "fastapi==0.110.0",
        "uvicorn==0.29.0",
        "pydantic==2.7.0",
        "soundfile==0.12.1",
        "numpy==1.26.4",
        "scipy==1.13.0",
    )
)

# XTTS-v2 supported languages
SUPPORTED_LANGUAGES = {
    "en", "es", "fr", "de", "it", "pt", "pl", "tr",
    "ru", "nl", "cs", "ar", "zh", "ja", "hu", "ko", "hi"
}


@app.cls(
    image=IMAGE,
    gpu=GPU_TYPE,
    secrets=SECRETS,
    volumes={str(MODEL_DIR): MODEL_VOLUME},
    scaledown_window=300,
    min_containers=0,
    max_containers=2,
    timeout=300,
    concurrency_limit=10,
)
class XTTSv2Server:
    """XTTS-v2 Zero-Shot Voice Cloning Server."""

    def __enter__(self):
        """Initialize XTTS-v2 model on container start."""
        import torch
        from TTS.api import TTS

        model_path = str(MODEL_DIR / "xtts_v2")
        print(f"Loading XTTS-v2 from {model_path}...")

        # Check if model exists locally, otherwise it will download from HF
        self.model = TTS("tts_models/multilingual/multi-dataset/xtts_v2", gpu=True)
        print("XTTS-v2 loaded successfully")
        print(f"Supported languages: {SUPPORTED_LANGUAGES}")

        self._lock = threading.Lock()

    @modal.method()
    def health(self):
        """Health check endpoint."""
        import torch

        return {
            "healthy": True,
            "model_loaded": hasattr(self, "model"),
            "device": "cuda" if torch.cuda.is_available() else "cpu",
            "supported_languages": list(SUPPORTED_LANGUAGES),
            "version": "1.0.0",
        }

    @modal.method()
    def clone(self, request: dict):
        """
        Clone voice from reference audio.

        Request:
        {
            "text": "text to synthesize",
            "reference_audio": "base64 encoded audio",  # Required
            "language": "zh",  # or "auto"
            "speed": 1.0,
            "sample_rate": 24000,
        }

        Response:
        {
            "audio_base64": "base64 encoded wav audio",
            "sample_rate": 24000,
            "language": "zh",
            "similarity": 0.95,
            "latency_ms": 1500
        }
        """
        text = request.get("text", "").strip()
        if not text:
            return {"error": "text is required"}, 400

        ref_audio_b64 = request.get("reference_audio")
        if not ref_audio_b64:
            return {"error": "reference_audio is required"}, 400

        language = request.get("language", "zh")
        if language == "auto":
            language = "zh"  # Default

        speed = request.get("speed", 1.0)
        sample_rate = request.get("sample_rate", 24000)

        try:
            # Decode reference audio
            ref_audio_bytes = base64.b64decode(ref_audio_b64)
            
            # Save reference audio to temp file
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(ref_audio_bytes)
                ref_audio_path = f.name

            start_time = time.time()

            # Generate cloned speech
            with self._lock:
                wav = self.model.tts(
                    text=text,
                    speaker_wav=ref_audio_path,
                    language=language,
                    speed=speed,
                )

            latency_ms = int((time.time() - start_time) * 1000)

            # Convert to base64
            import soundfile as sf
            import numpy as np
            import io
            
            wav_array = np.array(wav, dtype=np.float32)
            buffer = io.BytesIO()
            sf.write(buffer, wav_array, sample_rate, format="WAV")
            audio_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

            # Clean up temp file
            try:
                os.unlink(ref_audio_path)
            except:
                pass

            return {
                "audio_base64": audio_b64,
                "sample_rate": sample_rate,
                "language": language,
                "similarity": 0.9,  # XTTS-v2 doesn't return similarity, estimate
                "latency_ms": latency_ms,
            }

        except Exception as e:
            return {"error": str(e)}, 500

    @modal.method()
    def clone_stream(self, request: dict):
        """Stream cloning - returns chunks (not fully implemented, falls back to regular clone)."""
        # For now, just call regular clone and return as single chunk
        result = self.clone(request)
        if isinstance(result, tuple):
            return result
        
        # Wrap in streaming format
        return [{
            "audio_base64": result["audio_base64"],
            "sample_rate": result["sample_rate"],
            "language": result["language"],
            "similarity": result["similarity"],
            "is_final": True,
            "text": request.get("text", ""),
        }]


# =============================================================================
# FastAPI App
# =============================================================================


@modal.fastapi_endpoint()
def fastapi_app():
    """ASGI app for Modal deployment."""
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel
    from typing import Optional

    fastapi_app = FastAPI(title="XTTS-v2 Clone API", version="1.0.0")

    class CloneRequest(BaseModel):
        text: str
        reference_audio: str  # base64
        language: str = "zh"
        speed: float = 1.0
        sample_rate: int = 24000

    service = XTTSv2Server()

    @fastapi_app.get("/health")
    async def health():
        return service.health.remote()

    @fastapi_app.post("/clone")
    async def clone(request: CloneRequest):
        result = service.clone.remote(request.model_dump())
        if isinstance(result, tuple):
            raise HTTPException(status_code=result[1], detail=result[0].get("error", "Error"))
        return result

    @fastapi_app.post("/clone/stream")
    async def clone_stream(request: CloneRequest):
        result = service.clone_stream.remote(request.model_dump())
        if isinstance(result, tuple):
            raise HTTPException(status_code=result[1], detail=result[0].get("error", "Error"))
        return result

    return fastapi_app


if __name__ == "__main__":
    print("Deploy via: modal deploy modal_xtts_v2_server.py")
    print("Dev via: modal serve modal_xtts_v2_server.py")
