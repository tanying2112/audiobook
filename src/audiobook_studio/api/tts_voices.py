"""TTS Voice enumeration API endpoint."""

import asyncio
import logging
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional

import numpy as np
from fastapi import APIRouter, File, Form, UploadFile

from ..exceptions import DomainError
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..tts.clone import AudioQuality, VoiceCloningManager, VoiceSample
from ..tts.engine import TTSTaskPayload, TTSProsody, TTSVoiceAnchor
from ..tts.kokoro_backend import create_kokoro_backend
from ..tts.piper_models import detect_piper_availability, list_piper_voices

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tts", tags=["tts"])


# ─────────────────────────────────────────────────────────────────────────────
# Response Schemas
# ─────────────────────────────────────────────────────────────────────────────


class TTSVoice(BaseModel):
    """Single TTS voice definition."""

    id: str = Field(..., description="Voice identifier")
    name: str = Field(..., description="Display name")
    gender: str = Field(..., description="Voice gender: male/female/neutral")
    language: str = Field(..., description="Language code (e.g., zh-CN, en-US)")
    description: Optional[str] = Field(None, description="Voice description")
    sample_url: Optional[str] = Field(None, description="Audio sample URL")


class TTSEngine(BaseModel):
    """TTS engine with available voices."""

    id: str = Field(..., description="Engine identifier")
    name: str = Field(..., description="Engine display name")
    available: bool = Field(..., description="Whether engine is available")
    voices: List[TTSVoice] = Field(default_factory=list, description="Available voices")
    priority: int = Field(0, description="Engine priority (lower = higher priority)")
    supports_prosody: bool = Field(True, description="Whether engine supports prosody controls")
    supports_ssml: bool = Field(False, description="Whether engine supports SSML")
    supports_emotion: bool = Field(
        False,
        description="Whether engine renders voice from emotion (metadata-only otherwise)",
    )


class TTSVoicesResponse(BaseModel):
    """TTS voices enumeration response."""

    engines: Dict[str, TTSEngine] = Field(default_factory=dict)
    total_voices: int = 0
    default_engine: str = "kokoro"
    default_voice: str = "kokoro_narrator"


class TTSStatusResponse(BaseModel):
    """TTS engine status response for dynamic frontend adaptation."""

    local_engines_available: bool = Field(..., description="Whether any local TTS engine is available")
    kokoro_available: bool = Field(False, description="Kokoro ONNX local engine availability")
    kokoro_model_loaded: bool = Field(False, description="Whether Kokoro model is loaded in memory")
    voxcpm2_available: bool = Field(False, description="VoxCPM2 local engine availability")
    voxcpm2_model_loaded: bool = Field(False, description="Whether VoxCPM2 model is loaded")
    sherpa_onnx_available: bool = Field(False, description="Sherpa-ONNX local engine availability")
    piper_available: bool = Field(False, description="Piper (local, priority 0) engine availability")
    piper_model_loaded: bool = Field(False, description="Whether Piper model is present on disk")
    cloud_engines_available: bool = Field(..., description="Whether any cloud TTS engine is available")
    edge_tts_available: bool = Field(True, description="Edge-TTS (free cloud) availability")
    azure_available: bool = Field(False, description="Azure Cognitive Services TTS availability")
    gcp_available: bool = Field(False, description="Google Cloud TTS availability")
    recommended_engine: str = Field(..., description="Recommended engine based on availability")
    recommended_voice: str = Field(..., description="Recommended voice for the recommended engine")
    enable_local_tts_env: bool = Field(..., description="Value of ENABLE_LOCAL_TTS environment variable")


# ─────────────────────────────────────────────────────────────────────────────
# Voice Definitions
# ─────────────────────────────────────────────────────────────────────────────

# Kokoro voices (kokoro-onnx)
KOKORO_VOICES = [
    TTSVoice(
        id="kokoro_narrator",
        name="旁白",
        gender="neutral",
        language="zh-CN",
        description="Default narrator voice for Kokoro",
    ),
    TTSVoice(
        id="kokoro_female_1",
        name="女声 1",
        gender="female",
        language="zh-CN",
        description="Female voice for Kokoro",
    ),
]

# Edge-TTS voices (Microsoft Edge TTS - free, no auth required)
EDGE_TTS_VOICES = [
    TTSVoice(
        id="zh-CN-XiaoxiaoNeural",
        name="晓晓",
        gender="female",
        language="zh-CN",
        description="温暖柔和的女声，适合讲故事",
    ),
    TTSVoice(
        id="zh-CN-YunxiNeural",
        name="云希",
        gender="male",
        language="zh-CN",
        description="沉稳的男声",
    ),
    TTSVoice(
        id="zh-CN-YunjianNeural",
        name="云健",
        gender="male",
        language="zh-CN",
        description="成熟的男声",
    ),
    TTSVoice(
        id="zh-CN-XiaoyiNeural",
        name="晓伊",
        gender="female",
        language="zh-CN",
        description="温柔的女声",
    ),
    TTSVoice(
        id="en-US-JennyNeural",
        name="Jenny",
        gender="female",
        language="en-US",
        description="Natural female voice for English",
    ),
    TTSVoice(
        id="en-US-GuyNeural",
        name="Guy",
        gender="male",
        language="en-US",
        description="Natural male voice for English",
    ),
]

# Azure Cognitive Services voices (paid, requires API key)
AZURE_VOICES = [
    TTSVoice(
        id="zh-CN-XiaozhenNeural",
        name="晓珍",
        gender="female",
        language="zh-CN",
        description="Azure premium voice",
    ),
]

# GCP Cloud TTS voices
GCP_VOICES = [
    TTSVoice(
        id="zh-CN-Wavenet-A",
        name="WaveNet A (女)",
        gender="female",
        language="zh-CN",
        description="GCP WaveNet female voice",
    ),
    TTSVoice(
        id="zh-CN-Wavenet-B",
        name="WaveNet B (男)",
        gender="male",
        language="zh-CN",
        description="GCP WaveNet male voice",
    ),
]

# Piper voices (local, priority 0) — Chinese-focused model family.
PIPER_VOICES = [
    TTSVoice(
        id="zh_CN-huayan-medium",
        name="华婉 (中等)",
        gender="female",
        language="zh-CN",
        description="Piper 本地中文女声 · 自然中等质量 (默认旁白)",
    ),
    TTSVoice(
        id="zh_CN-huayan-x_low",
        name="华婉 (极轻量)",
        gender="female",
        language="zh-CN",
        description="Piper 本地中文女声 · 极轻量 (CPU 低延迟)",
    ),
    TTSVoice(
        id="zh_CN-shaoer-medium",
        name="少儿 (中等)",
        gender="neutral",
        language="zh-CN",
        description="Piper 本地中文少儿/活泼声线",
    ),
]

# Priority ordering is sourced from config/tts_providers.yaml (S2-4):
# Piper=0 (preferred local), Kokoro=1 (fallback local), Edge-TTS=2 (cloud).
try:
    from ..tts.providers_config import provider_priority_map
    _PROVIDER_PRIORITY = provider_priority_map()
except Exception:  # noqa: BLE001
    _PROVIDER_PRIORITY = {"piper": 0, "kokoro": 1, "edge_tts": 2}
_PIPER_PRIORITY = _PROVIDER_PRIORITY.get("piper", 0)
_KOKORO_PRIORITY = _PROVIDER_PRIORITY.get("kokoro", 1)
_EDGE_PRIORITY = _PROVIDER_PRIORITY.get("edge_tts", 2)


# VoxCPM2 voices
VOXCPM2_VOICES = [
    TTSVoice(
        id="zh_female_1",
        name="中文女声",
        gender="female",
        language="zh-CN",
        description="VoxCPM2 Chinese female voice",
    ),
    TTSVoice(
        id="zh_male_1",
        name="中文男声",
        gender="male",
        language="zh-CN",
        description="VoxCPM2 Chinese male voice",
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/voices", response_model=TTSVoicesResponse)
async def list_tts_voices(
    include_unavailable: bool = False,
    language: Optional[str] = None,
    gender: Optional[str] = None,
):
    """
    Get available TTS voices by engine.

    Returns comprehensive voice list for frontend dropdown selection.

    Query parameters:
    - include_unavailable: Whether to include unavailable engines
    - language: Filter by language (e.g., 'zh-CN', 'en-US')
    - gender: Filter by gender (male/female/neutral)

    Response includes:
    - Engine availability status
    - Voice list with metadata
    - Default engine/voice recommendations
    """
    import os

    # Check ENABLE_LOCAL_TTS environment variable
    enable_local_tts = os.environ.get("ENABLE_LOCAL_TTS", "true").lower() == "true"

    engines = {}

    # Piper (local, priority 0 — preferred local engine per tts_providers.yaml).
    # Honest availability: only "available" when a real piper binary + model exist.
    piper_available, piper_detail = detect_piper_availability()
    engines["piper"] = TTSEngine(
        id="piper",
        name="Piper TTS",
        available=bool(piper_available) or include_unavailable,
        voices=PIPER_VOICES,
        priority=_PIPER_PRIORITY,
        supports_prosody=True,
        supports_ssml=False,
    )

    # Kokoro (local fallback, available when ENABLE_LOCAL_TTS=true)
    engines["kokoro"] = TTSEngine(
        id="kokoro",
        name="Kokoro ONNX",
        available=enable_local_tts,
        voices=KOKORO_VOICES,
        priority=_KOKORO_PRIORITY,
        supports_prosody=True,
        supports_ssml=False,
    )

    # Edge-TTS (free, no auth)
    engines["edge_tts"] = TTSEngine(
        id="edge_tts",
        name="Edge TTS",
        available=True,
        voices=EDGE_TTS_VOICES,
        priority=_EDGE_PRIORITY,
        supports_prosody=True,
        supports_ssml=True,
    )

    # Azure (requires API key). P1.9: honest availability — express False
    # when no key, rather than a fake hardcoded True. No real azure backend
    # module exists (only this API placeholder); aligns with status endpoint.
    azure_available = bool(os.environ.get("AZURE_TTS_KEY"))
    engines["azure"] = TTSEngine(
        id="azure",
        name="Azure Cognitive Services",
        available=azure_available or include_unavailable,
        voices=AZURE_VOICES,
        priority=3,
        supports_prosody=True,
        supports_ssml=True,
    )

    # GCP (requires API key). P1.9: honest availability — GOOGLE_APPLICATION_CREDENTIALS
    # is the service-account key path (.env.example). No real gcp backend module
    # exists (only this API placeholder); aligns with status endpoint.
    gcp_available = bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
    engines["gcp"] = TTSEngine(
        id="gcp",
        name="Google Cloud TTS",
        available=gcp_available or include_unavailable,
        voices=GCP_VOICES,
        priority=4,
        supports_prosody=True,
        supports_ssml=True,
    )

    # VoxCPM2 (local)
    voxcpm_available = enable_local_tts  # Only available when local TTS enabled
    engines["voxcpm2"] = TTSEngine(
        id="voxcpm2",
        name="VoxCPM2",
        available=voxcpm_available or include_unavailable,
        voices=VOXCPM2_VOICES,
        priority=5,
        supports_prosody=False,
        supports_ssml=False,
    )

    # Apply filters
    if language:
        for engine in engines.values():
            engine.voices = [v for v in engine.voices if v.language == language]

    if gender:
        for engine in engines.values():
            engine.voices = [v for v in engine.voices if v.gender == gender]

    # Calculate total voices
    total_voices = sum(len(e.voices) for e in engines.values())

    # Determine default engine: prefer Piper (local, priority 0) when available,
    # then Kokoro, else Edge-TTS (cloud).
    if piper_available:
        default_engine = "piper"
        default_voice = "zh_CN-huayan-medium"
    elif enable_local_tts:
        default_engine = "kokoro"
        default_voice = "kokoro_narrator"
    else:
        default_engine = "edge_tts"
        default_voice = "zh-CN-XiaoxiaoNeural"

    return TTSVoicesResponse(
        engines=engines,
        total_voices=total_voices,
        default_engine=default_engine,
        default_voice=default_voice,
    )


@router.get("/status", response_model=TTSStatusResponse)
async def get_tts_status():
    """
    Get TTS engine status for dynamic frontend adaptation.

    This endpoint allows the frontend to dynamically show/hide
    local offline engine options based on actual model availability.

    Returns:
        TTSStatusResponse with engine availability and recommendations
    """
    import asyncio
    import os

    def _check_kokoro_model_available() -> tuple[bool, bool]:
        """Check if Kokoro ONNX model files exist AND can be loaded.

        Returns:
            (files_exist, can_load): files_exist checks disk, can_load checks if onnxruntime can initialize
        """
        model_dir = Path("models/kokoro")
        model_file = model_dir / "kokoro-v1.0.onnx"
        voices_file = model_dir / "voices-v1.0.bin"
        # Also check alternative locations
        alt_model = Path("models/kokoro-v1.0.onnx")
        alt_voices = Path("models/voices-v1.0.bin")

        files_exist = (model_file.exists() and voices_file.exists()) or (alt_model.exists() and alt_voices.exists())

        if not files_exist:
            return (False, False)

        # Try to actually load the model to verify it works
        can_load = True
        try:
            import onnxruntime as ort

            # Use the first existing path pair
            mpath = str(model_file.absolute()) if model_file.exists() else str(alt_model.absolute())
            vpath = str(voices_file.absolute()) if voices_file.exists() else str(alt_voices.absolute())

            sess_options = ort.SessionOptions()
            sess_options.intra_op_num_threads = 1
            sess = ort.InferenceSession(mpath, sess_options=sess_options, providers=["CPUExecutionProvider"])

            # Try loading voice embeddings
            import numpy as np

            np.load(vpath, allow_pickle=True)

        except Exception as e:
            logger.warning(f"Kokoro model files exist but cannot load: {e}")
            can_load = False

        return (files_exist, can_load)

    async def _check_edge_tts_connectivity() -> bool:
        """Quick async connectivity check to Edge-TTS."""
        try:
            import edge_tts

            # Lightweight check - just list a few voices
            voices = await edge_tts.list_voices()
            return len(voices) > 0
        except Exception as e:
            logger.warning(f"Edge-TTS connectivity check failed: {e}")
            return False

    # Check ENABLE_LOCAL_TTS environment variable
    enable_local_tts = os.environ.get("ENABLE_LOCAL_TTS", "true").lower() == "true"

    # Check local engine availability with REAL model file checks
    kokoro_files_exist, kokoro_can_load = _check_kokoro_model_available()
    kokoro_available = enable_local_tts and kokoro_files_exist and kokoro_can_load
    kokoro_model_loaded = kokoro_available  # For now, "loaded" means "can load"

    # Piper (local, priority 0) — real binary + model detection (S2-4).
    piper_available, _piper_detail = detect_piper_availability()
    piper_model_loaded = bool(_piper_detail.get("model"))

    voxcpm2_available = False  # VoxCPM2 not yet implemented locally
    voxcpm2_model_loaded = False
    sherpa_onnx_available = False  # Sherpa-ONNX not yet implemented

    local_engines_available = (
        piper_available or kokoro_available or voxcpm2_available or sherpa_onnx_available
    )

    # Cloud engines - Edge-TTS with real connectivity check
    edge_tts_available = await _check_edge_tts_connectivity()
    azure_available = False  # TODO: Check actual Azure credentials
    gcp_available = False  # TODO: Check actual GCP credentials
    cloud_engines_available = edge_tts_available or azure_available or gcp_available

    # Determine recommended engine: prefer Piper (local, available) -> Kokoro -> Edge.
    if piper_available:
        recommended_engine = "piper"
        recommended_voice = "zh_CN-huayan-medium"
    elif enable_local_tts and local_engines_available:
        recommended_engine = "kokoro"
        recommended_voice = "zf_xiaoxiao"  # Chinese female voice
    else:
        recommended_engine = "edge_tts"
        recommended_voice = "zh-CN-XiaoxiaoNeural"

    return TTSStatusResponse(
        local_engines_available=local_engines_available,
        kokoro_available=kokoro_available,
        kokoro_model_loaded=kokoro_model_loaded,
        voxcpm2_available=voxcpm2_available,
        voxcpm2_model_loaded=voxcpm2_model_loaded,
        sherpa_onnx_available=sherpa_onnx_available,
        piper_available=piper_available,
        piper_model_loaded=piper_model_loaded,
        cloud_engines_available=cloud_engines_available,
        edge_tts_available=edge_tts_available,
        azure_available=azure_available,
        gcp_available=gcp_available,
        recommended_engine=recommended_engine,
        recommended_voice=recommended_voice,
        enable_local_tts_env=enable_local_tts,
    )


@router.get("/voices/recommended")
async def get_recommended_voices(
    context: Optional[str] = None,
    language: Optional[str] = "zh-CN",
):
    """
    Get recommended voices for a specific context.

    Args:
        context: Context hint ('narration', 'dialogue', 'female_character', 'male_character')
        language: Language filter

    Returns:
        List of recommended voices for the context
    """
    # Get all voices first
    all_voices = []
    for engine in ["kokoro", "edge_tts", "azure", "gcp"]:
        voices_response = await list_tts_voices(language=language)
        if engine in voices_response.engines:
            all_voices.extend(voices_response.engines[engine].voices)

    # Context-based recommendations
    if context == "narration":
        # Narrator voices (neutral, calm)
        recommendations = [v for v in all_voices if v.gender == "neutral" or "晓" in v.name]
    elif context == "dialogue":
        # Expressive voices for dialogue
        recommendations = [v for v in all_voices if v.gender in ("male", "female")]
    elif context == "female_character":
        recommendations = [v for v in all_voices if v.gender == "female"]
    elif context == "male_character":
        recommendations = [v for v in all_voices if v.gender == "male"]
    else:
        # Default: top 5 voices
        recommendations = all_voices[:5]

    return {
        "context": context or "general",
        "recommended": recommendations,
        "count": len(recommendations),
    }


@router.get("/voices/preview/{voice_id}")
async def preview_voice(voice_id: str, text: str = "这是一个语音试听样本。"):
    """
    Preview a voice with sample text.

    The preview is served by the real streaming TTS endpoint (``/api/tts/stream``),
    which performs genuine synthesis - the returned ``preview_url`` is a working
    link rather than a dead placeholder. No audio is synthesized server-side here.
    """
    return {
        "voice_id": voice_id,
        "text": text,
        "preview_url": f"/api/tts/stream?voice_id={voice_id}&text={text}",
        "note": "Live preview via /api/tts/stream (real synthesis).",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Streaming TTS
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_STREAM_VOICE = "zh-CN-XiaoxiaoNeural"


class TTSStreamRequest(BaseModel):
    """Request body for streaming TTS synthesis."""

    text: str = Field(..., min_length=1, description="Text to synthesize (streamed back as audio)")
    voice_id: str = Field(
        default=DEFAULT_STREAM_VOICE,
        description="Voice identifier (Edge-TTS voice id)",
    )
    engine: str = Field(
        default="edge_tts",
        description="Synthesis backend: 'edge_tts' (real, free, MP3) or 'mock' (offline WAV sine).",
    )
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="Speech rate multiplier")
    pitch: float = Field(default=0.0, ge=-12.0, le=12.0, description="Pitch shift in semitones")
    volume: float = Field(default=0.0, ge=-20.0, le=20.0, description="Volume gain in dB")


def _tts_stream_use_mock(engine: str) -> bool:
    """Whether to use the offline mock generator.

    Mock is used when MOCK_TTS is enabled globally (the project-wide free/offline
    switch) or when the caller explicitly requests engine='mock'.
    """
    env_mock = os.environ.get("MOCK_TTS", "false").lower() == "true"
    return env_mock or engine == "mock"


def _mock_wav_bytes(text: str, sample_rate: int = 24000) -> bytes:
    """Generate a deterministic sine-tone WAV (no external deps) for offline streaming.

    The WAV header is written first so a client can start decoding/playback as soon
    as the first chunk arrives, while the remaining PCM chunks keep streaming.
    """
    import array
    import io
    import math
    import wave

    duration_s = min(max(1.0, len(text) / 20.0), 5.0)
    num_samples = int(sample_rate * duration_s)
    pcm = array.array("h")
    for i in range(num_samples):
        sample = int(32767 * 0.3 * math.sin(2.0 * math.pi * 220.0 * i / sample_rate))
        pcm.append(sample)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())
    return buf.getvalue()


async def _mock_stream_generator(text: str, chunk_size: int = 4096) -> AsyncGenerator[bytes, None]:
    """Yield the mock WAV in chunks so the HTTP response streams progressively."""
    data = _mock_wav_bytes(text)
    for start in range(0, len(data), chunk_size):
        yield data[start : start + chunk_size]
        await asyncio.sleep(0)  # cooperative yield -> client receives chunks incrementally


async def _edge_stream_generator(req: TTSStreamRequest) -> AsyncGenerator[bytes, None]:
    """Stream real audio via Edge-TTS (yields MP3 chunks as they are synthesized)."""
    from ..tts.edge_tts_engine import create_edge_tts_engine

    engine = await create_edge_tts_engine(mock_mode=False)
    payload = TTSTaskPayload(
        text=req.text,
        voice_anchor=TTSVoiceAnchor(voice_id=req.voice_id or DEFAULT_STREAM_VOICE),
        prosody=TTSProsody(rate=req.speed, pitch=req.pitch, volume=req.volume),
    )
    async for chunk in engine.stream(payload):
        if chunk:
            yield chunk


@router.post("/stream")
async def stream_tts(req: TTSStreamRequest):
    """
    Stream synthesized speech in real time (chunked HTTP response).

    The response is an ``audio/chunk`` stream: audio bytes are sent to the client
    as soon as they are synthesized, so playback can begin *before* the whole
    utterance has finished — no need to wait for full synthesis.

    - ``engine="edge_tts"`` (default): real, free Microsoft Edge TTS. Chunks are
      MP3 (``audio/mpeg``) produced by Edge-TTS's native streaming API.
    - ``engine="mock"`` (or global ``MOCK_TTS=true``): a deterministic WAV sine
      tone is streamed (``audio/wav``), so the endpoint works fully offline.
    """
    if _tts_stream_use_mock(req.engine):
        generator: AsyncGenerator[bytes, None] = _mock_stream_generator(req.text)
        media_type = "audio/wav"
    else:
        generator = _edge_stream_generator(req)
        media_type = "audio/mpeg"

    return StreamingResponse(
        generator,
        media_type=media_type,
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # disable proxy buffering for real-time playback
            "Content-Disposition": "inline",
        },
    )


@router.get("/stream")
async def stream_tts_get(
    text: str = "",
    voice_id: str = DEFAULT_STREAM_VOICE,
    engine: str = "edge_tts",
    speed: float = 1.0,
    pitch: float = 0.0,
    volume: float = 0.0,
):
    """
    GET convenience variant of ``POST /api/tts/stream`` for quick browser/curl tests.

    Example::

        curl -N "http://localhost:8000/api/tts/stream?text=hello&engine=mock" > out.wav
    """
    if not text:
        raise DomainError(
            message="query parameter 'text' is required",
            error_code="VALIDATION_ERROR",
            stage="tts",
            context={"field": "text"},
        )
    req = TTSStreamRequest(
        text=text, voice_id=voice_id, engine=engine, speed=speed, pitch=pitch, volume=volume
    )
    return await stream_tts(req)


# ─────────────────────────────────────────────────────────────────────────────
# Voice Cloning Endpoint
# ─────────────────────────────────────────────────────────────────────────────


class CloneVoiceRequest(BaseModel):
    """Request for voice cloning."""

    speaker_id: str = Field(..., description="Speaker/character identifier")
    language: str = Field(default="zh-CN", description="Target language")
    text_content: str = Field(default="", description="Reference text content")
    # P2.11 合规: 克隆前必须获得样本提供者授权 (红线#1: 不勾 → 422 拒绝, 不假装处理成功)
    consent: bool = Field(..., description="样本提供者已授权克隆 (必填, 不勾 → 422)")


class CloneVoiceResponse(BaseModel):
    """Response for voice cloning."""

    success: bool
    speaker_id: str
    voice_id: str
    message: str
    quality: Optional[str] = None
    snr_db: Optional[float] = None
    sample_count: Optional[int] = None
    # A2 honesty: under free + no-GPU, cloning degrades to 'preset' mode — the
    # sample is stored for a future GPU clone backend but no real clone is produced.
    mode: str = Field(
        default="preset",
        description="'clone' = real zero-shot clone produced; 'preset' = no-GPU fallback (sample stored).",
    )
    clone_available: bool = Field(
        default=False,
        description="Whether a real zero-shot clone backend was available for this request.",
    )


@router.post("/voices/clone", response_model=CloneVoiceResponse)
async def clone_voice(
    file: UploadFile = File(..., description="15s+ audio sample (WAV/MP3)"),
    speaker_id: str = Form(..., description="Speaker/character identifier"),
    language: str = Form(default="zh-CN", description="Target language"),
    text_content: str = Form(default="", description="Reference text content"),
    consent: bool = Form(..., description="样本提供者已授权克隆 (必填, 不勾 → 422)"),
):
    """
    Clone a voice from an uploaded audio sample.

    ⚠️ Honest scope (free + no-GPU): this endpoint **stores the sample** and, when a
    real zero-shot clone backend (F5-TTS / CosyVoice2, Track B) is deployed, produces
    a true clone. On CPU-only hosts (the current default) no GPU clone model can run,
    so cloning **degrades to 'preset' mode**: the sample is saved for later and the
    response reports ``mode='preset'`` / ``clone_available=False``. We never claim a
    usable clone was created when none was.

    - Upload a 15+ second audio sample (WAV/MP3)
    - System validates duration/SNR and stores the sample (future clone source)
    - Returns ``voice_id`` plus honest ``mode`` / ``clone_available`` flags

    Requirements:
    - Minimum 15 seconds duration
    - SNR >= 20dB for good quality
    - Supported formats: WAV, MP3
    - **consent=true 样本提供者已授权克隆 (P2.11 合规, 必填)**

    Response:
    - success: True if the sample was validated and stored
    - voice_id: The stored-sample identifier (use with /api/tts/voices)
    - mode: 'clone' (real) or 'preset' (no-GPU fallback)
    - clone_available: whether a real clone backend served this request
    """
    from ..tts.clone import AudioQuality, clone_mode, real_clone_available

    # P2.11 合规: 克隆前强制授权核实 (红线#1A: 不勾 → 422 诚实拒, 不假装处理)
    if not consent:
        raise DomainError(
            message="声音克隆需样本提供者明确授权 (consent=true)。未经授权的样本不得克隆。",
            error_code="VALIDATION_ERROR",
            stage="tts",
            context={"field": "consent"},
        )

    # Validate file type
    allowed_types = {"audio/wav", "audio/wave", "audio/x-wav", "audio/mpeg", "audio/mp3"}
    if file.content_type not in allowed_types:
        raise DomainError(
            message=f"Unsupported audio format: {file.content_type}. Use WAV or MP3.",
            error_code="VALIDATION_ERROR",
            stage="tts",
            context={"content_type": file.content_type, "allowed_types": list(allowed_types)},
        )

    # Save uploaded file to temp location
    with tempfile.NamedTemporaryFile(suffix=Path(file.filename).suffix, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        # Initialize voice cloning manager
        manager = VoiceCloningManager()

        # Validate audio file
        import soundfile as sf

        audio_data, sr = sf.read(str(tmp_path))
        duration = len(audio_data) / sr

        # Estimate SNR
        noise_floor = min(
            np.std(audio_data[: min(100, len(audio_data))]),
            np.std(audio_data[max(0, len(audio_data) - 100) :]),
        )
        signal_power = np.std(audio_data)
        snr_db = 20 * np.log10(signal_power / noise_floor) if noise_floor > 0 else 50.0

        if duration < 15.0:
            raise DomainError(
                message=f"Sample too short: {duration:.1f}s. Minimum 15 seconds required.",
                error_code="VALIDATION_ERROR",
                stage="tts",
                context={"duration": duration, "min_duration": 15.0},
            )

        if snr_db < 20.0:
            raise DomainError(
                message=f"SNR too low: {snr_db:.1f}dB. Minimum 20dB required.",
                error_code="VALIDATION_ERROR",
                stage="tts",
                context={"snr_db": snr_db, "min_snr_db": 20.0},
            )

        # Create voice sample with P2.11 attestation (consent 授权版本记入持久化字段)
        sample = VoiceSample(
            id=f"clone_{speaker_id}",
            file_path=tmp_path,
            duration=duration,
            sample_rate=sr,
            snr_db=snr_db,
            text_content=text_content or "Voice clone sample",
            language=language,
            speaker_id=speaker_id,
            attestation_at=datetime.now().isoformat(),  # P2.11: 授权时间戳
            consent_version="v1",  # P2.11: 当前授权条款版本
        )

        # Add sample (creates voice print)
        success, message = manager.add_voice_sample(sample)

        if not success:
            raise DomainError(
                message=message,
                error_code="VALIDATION_ERROR",
                stage="tts",
                context={"speaker_id": speaker_id},
            )

        # Get voice info
        voice_info = manager.get_voice_info(speaker_id)
        voice_id = f"cloned_{speaker_id}"

        # A2 honesty: report real mode instead of implying a usable clone was made.
        clone_is_available = real_clone_available()
        active_mode = clone_mode()
        if clone_is_available:
            honest_message = message
        else:
            honest_message = (
                "样本已存储；当前无 GPU 克隆后端，克隆降级为预设声线模式 "
                "(待 F5-TTS / CosyVoice2 接入后启用真零样本克隆)。"
            )

        return CloneVoiceResponse(
            success=True,
            speaker_id=speaker_id,
            voice_id=voice_id,
            message=honest_message,
            quality=voice_info.get("quality") if voice_info else None,
            snr_db=voice_info.get("avg_snr_db") if voice_info else None,
            sample_count=voice_info.get("sample_count") if voice_info else None,
            mode=active_mode,
            clone_available=clone_is_available,
        )

    except DomainError:
        raise
    except Exception as e:
        logger.error(f"Voice cloning failed: {e}")
        raise DomainError(
            message=f"Voice cloning failed: {str(e)}",
            error_code="INTERNAL_ERROR",
            stage="tts",
            context={"speaker_id": speaker_id},
            original_error=e,
        ) from e
    finally:
        # Cleanup temp file
        if tmp_path.exists():
            tmp_path.unlink()


@router.get("/voices/cloned")
async def list_cloned_voices():
    """
    List all available cloned voices.
    """
    manager = VoiceCloningManager()
    cloned_voices = []
    for speaker_id, info in [(sp_id, manager.get_voice_info(sp_id)) for sp_id in manager.voice_prints.keys()]:
        if info:
            cloned_voices.append(
                {
                    "speaker_id": speaker_id,
                    "voice_id": f"cloned_{speaker_id}",
                    "quality": info["quality"],
                    "snr_db": info["avg_snr_db"],
                    "sample_count": info["sample_count"],
                    "created_at": info["created_at"],
                }
            )
    return {"cloned_voices": cloned_voices, "count": len(cloned_voices)}
