#!/usr/bin/env python3
"""
Modal HTTP Server for CosyVoice-Stream Streaming TTS.

Exposes REST API for Audiobook Studio streaming TTS engines:
- POST /tts/stream - Streaming synthesis
- GET /health - Health check

Expected response format (JSON lines):
{"audio_hex": "deadbeef...", "sample_rate": 24000, "is_final": false, "text": "partial text"}

Usage:
    modal deploy modal_cosyvoice_stream_server.py
    modal serve modal_cosyvoice_stream_server.py

Prerequisites:
    modal secret create audiobook-config HF_TOKEN=<your_hf_token>
    # CosyVoice from FunAudioLLM
"""
from __future__ import annotations

import os
import json
import time
import threading
from pathlib import Path
from typing import Any, Dict, Optional, AsyncGenerator

import modal
from pydantic import BaseModel
from typing import Optional

# =============================================================================
# Modal App Configuration
# =============================================================================

app = modal.App("cosyvoice-stream-server")

GPU_TYPE = os.getenv("MODAL_GPU", "T4").upper()

MODEL_VOLUME = modal.Volume.from_name("cosyvoice-model-weights", create_if_missing=True)
MODEL_DIR = Path("/models")

SECRETS = [modal.Secret.from_name("audiobook-config")]

IMAGE = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "libsndfile1", "git")
    .pip_install(
        "torch==2.3.0",
        "torchaudio==2.3.0",
        "transformers>=4.45.0",
        "sentencepiece",
        "protobuf",
        "accelerate",
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
        "git clone https://github.com/FunAudioLLM/CosyVoice /opt/CosyVoice 2>/dev/null || true",
    )
)


# Request models (at module level for FastAPI type resolution)
class StreamRequest(BaseModel):
        text: str
        voice_id: Optional[str] = "default"
        speed: float = 1.0
        sample_rate: int = 24000
        chunk_size_ms: int = 100


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
class CosyVoiceStreamServer:
    """CosyVoice Streaming TTS Server."""

    # Class-level attributes for lazy initialization
    _lock = None

    def _ensure_initialized(self):
        if self._lock is None:
            import threading
            self._lock = threading.Lock()

    def __enter__(self):
        """Initialize CosyVoice model on container start."""
        import torch
        from funasr import AutoModel

        model_path = str(MODEL_DIR / "FunAudioLLM" / "CosyVoice")
        print(f"Loading CosyVoice from {model_path}...")

        self.model = AutoModel(
            model=model_path,
            trust_remote_code=True,
            device="cuda",
            disable_update=True,
        )
        print("CosyVoice loaded successfully")

        self._lock = threading.Lock()

    @modal.method()
    def health(self):
        """Health check endpoint."""
        import torch

        return {
            "healthy": True,
            "model_loaded": hasattr(self, "model"),
            "device": "cuda" if torch.cuda.is_available() else "cpu",
            "version": "1.0.0",
        }

    @modal.method()
    def synthesize_stream(self, request: dict):
        """
        Streaming synthesis.

        Request:
        {
            "text": "text to synthesize",
            "voice_id": "default",
            "speed": 1.0,
            "sample_rate": 24000,
            "chunk_size_ms": 100,
        }

        Response: Generator of JSON lines
        """
        self._ensure_initialized()
        text = request.get("text", "").strip()
        if not text:
            return {"error": "text is required"}, 400

        voice_id = request.get("voice_id", "default")
        speed = request.get("speed", 1.0)
        sample_rate = request.get("sample_rate", 24000)
        chunk_size_ms = request.get("chunk_size_ms", 100)

        try:
            # CosyVoice generate returns generator
            # This is a simplified version - actual API may vary
            generator = self.model.generate(
                input=text,
                # CosyVoice specific params
            )

            # Convert to streaming chunks
            chunk_samples = int(sample_rate * chunk_size_ms / 1000)
            chunk_bytes = chunk_samples * 2  # 16-bit = 2 bytes per sample
            
            results = []
            chunk_index = 0
            first_chunk = True
            start_time = time.time()

            for chunk in generator:
                # Convert chunk to bytes
                import numpy as np
                import soundfile as sf
                import io
                
                if isinstance(chunk, dict):
                    audio = chunk.get("audio") or chunk.get("waveform")
                else:
                    audio = chunk
                
                if audio is None:
                    continue
                    
                audio_np = audio.cpu().numpy() if hasattr(audio, 'cpu') else np.array(audio)
                audio_int16 = (audio_np * 32767).astype(np.int16)
                
                # Split into chunks
                for i in range(0, len(audio_int16), chunk_samples):
                    chunk_data = audio_int16[i:i+chunk_samples]
                    if len(chunk_data) == 0:
                        continue
                    
                    is_final = (i + chunk_samples >= len(audio_int16))
                    
                    chunk_bytes = chunk_data.tobytes()
                    audio_hex = chunk_bytes.hex()
                    
                    latency = int((time.time() - start_time) * 1000) if first_chunk else 0
                    first_chunk = False
                    
                    results.append({
                        "audio_hex": audio_hex,
                        "sample_rate": sample_rate,
                        "is_final": is_final,
                        "text": text if chunk_index == 0 else "",
                    })
                    chunk_index += 1
                    
                    if is_final:
                        break

            return results

        except Exception as e:
            return {"error": str(e)}, 500


# =============================================================================
# FastAPI App
# =============================================================================


@app.function(image=IMAGE)
@modal.asgi_app()
def fastapi_app():
    """ASGI app for Modal deployment."""
    from fastapi import FastAPI, HTTPException, StreamingResponse

    fastapi_app = FastAPI(title="CosyVoice Stream API", version="1.0.0")

    service = CosyVoiceStreamServer()

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
        """Returns JSON lines stream."""
        result = service.synthesize_stream.remote(request.model_dump())
        
        if isinstance(result, tuple):
            raise HTTPException(status_code=result[1], detail=result[0].get("error", "Error"))
        
        # Stream as JSON lines
        async def generate():
            for chunk in result:
                yield json.dumps(chunk) + "\n"
        
        return StreamingResponse(
            generate(),
            media_type="application/x-ndjson",
        )

    return fastapi_app


if __name__ == "__main__":
    print("Deploy via: modal deploy modal_cosyvoice_stream_server.py")
    print("Dev via: modal serve modal_cosyvoice_stream_server.py")
