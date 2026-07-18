"""TTS Voice enumeration API endpoint."""

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from ..tts.clone import AudioQuality, VoiceCloningManager, VoiceSample

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

    # Kokoro (local, available when ENABLE_LOCAL_TTS=true)
    engines["kokoro"] = TTSEngine(
        id="kokoro",
        name="Kokoro ONNX",
        available=enable_local_tts,
        voices=KOKORO_VOICES,
        priority=1,
        supports_prosody=True,
        supports_ssml=False,
    )

    # Edge-TTS (free, no auth)
    engines["edge_tts"] = TTSEngine(
        id="edge_tts",
        name="Edge TTS",
        available=True,
        voices=EDGE_TTS_VOICES,
        priority=2,
        supports_prosody=True,
        supports_ssml=True,
    )

    # Azure (requires API key)
    azure_available = True  # TODO: Check actual availability
    engines["azure"] = TTSEngine(
        id="azure",
        name="Azure Cognitive Services",
        available=azure_available or include_unavailable,
        voices=AZURE_VOICES,
        priority=3,
        supports_prosody=True,
        supports_ssml=True,
    )

    # GCP (requires API key)
    gcp_available = True  # TODO: Check actual availability
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

    # Determine default engine based on ENABLE_LOCAL_TTS
    default_engine = "kokoro" if enable_local_tts else "edge_tts"
    default_voice = "kokoro_narrator" if enable_local_tts else "zh-CN-XiaoxiaoNeural"

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
    local offline engine options based on actual availability.

    Returns:
        TTSStatusResponse with engine availability and recommendations
    """
    import os

    # Check ENABLE_LOCAL_TTS environment variable
    enable_local_tts = os.environ.get("ENABLE_LOCAL_TTS", "true").lower() == "true"

    # Check local engine availability
    # In production, these would check actual model loading status
    kokoro_available = enable_local_tts  # Kokoro available if local TTS enabled
    kokoro_model_loaded = enable_local_tts  # Simplified: assume loaded if enabled
    voxcpm2_available = False  # VoxCPM2 not yet implemented locally
    voxcpm2_model_loaded = False
    sherpa_onnx_available = False  # Sherpa-ONNX not yet implemented

    local_engines_available = kokoro_available or voxcpm2_available or sherpa_onnx_available

    # Cloud engines (Edge-TTS is always available - free, no auth)
    edge_tts_available = True
    azure_available = False  # TODO: Check actual Azure credentials
    gcp_available = False  # TODO: Check actual GCP credentials
    cloud_engines_available = edge_tts_available or azure_available or gcp_available

    # Determine recommended engine based on ENABLE_LOCAL_TTS and availability
    if enable_local_tts and local_engines_available:
        recommended_engine = "kokoro"
        recommended_voice = "kokoro_narrator"
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

    Returns:
        Audio preview URL or synthesized audio data
    """
    # TODO: Implement actual voice preview
    # For now, return mock response
    return {
        "voice_id": voice_id,
        "text": text,
        "preview_url": f"/api/tts/preview/{voice_id}.mp3",
        "note": "Voice preview synthesis - placeholder implementation",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Voice Cloning Endpoint
# ─────────────────────────────────────────────────────────────────────────────


class CloneVoiceRequest(BaseModel):
    """Request for voice cloning."""

    speaker_id: str = Field(..., description="Speaker/character identifier")
    language: str = Field(default="zh-CN", description="Target language")
    text_content: str = Field(default="", description="Reference text content")


class CloneVoiceResponse(BaseModel):
    """Response for voice cloning."""

    success: bool
    speaker_id: str
    voice_id: str
    message: str
    quality: Optional[str] = None
    snr_db: Optional[float] = None
    sample_count: Optional[int] = None


@router.post("/voices/clone", response_model=CloneVoiceResponse)
async def clone_voice(
    file: UploadFile = File(..., description="15s+ audio sample (WAV/MP3)"),
    speaker_id: str = Form(..., description="Speaker/character identifier"),
    language: str = Form(default="zh-CN", description="Target language"),
    text_content: str = Form(default="", description="Reference text content"),
):
    """
    Clone a voice from an uploaded audio sample.

    - Upload a 15+ second audio sample (WAV/MP3)
    - System extracts voice embedding and creates voice print
    - Returns voice_id that can be used for TTS synthesis

    Requirements:
    - Minimum 15 seconds duration
    - SNR >= 20dB for good quality
    - Supported formats: WAV, MP3

    Response:
    - success: True if cloning succeeded
    - voice_id: The cloned voice identifier (use with /api/tts/voices)
    - quality: Audio quality rating (excellent/good/fair/poor)
    """
    from ..tts.clone import AudioQuality

    # Validate file type
    allowed_types = {"audio/wav", "audio/wave", "audio/x-wav", "audio/mpeg", "audio/mp3"}
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format: {file.content_type}. Use WAV or MP3.",
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
            raise HTTPException(
                status_code=400,
                detail=f"Sample too short: {duration:.1f}s. Minimum 15 seconds required.",
            )

        if snr_db < 20.0:
            raise HTTPException(
                status_code=400,
                detail=f"SNR too low: {snr_db:.1f}dB. Minimum 20dB required.",
            )

        # Create voice sample
        sample = VoiceSample(
            id=f"clone_{speaker_id}",
            file_path=tmp_path,
            duration=duration,
            sample_rate=sr,
            snr_db=snr_db,
            text_content=text_content or "Voice clone sample",
            language=language,
            speaker_id=speaker_id,
        )

        # Add sample (creates voice print)
        success, message = manager.add_voice_sample(sample)

        if not success:
            raise HTTPException(status_code=400, detail=message)

        # Get voice info
        voice_info = manager.get_voice_info(speaker_id)
        voice_id = f"cloned_{speaker_id}"

        return CloneVoiceResponse(
            success=True,
            speaker_id=speaker_id,
            voice_id=voice_id,
            message=message,
            quality=voice_info.get("quality") if voice_info else None,
            snr_db=voice_info.get("avg_snr_db") if voice_info else None,
            sample_count=voice_info.get("sample_count") if voice_info else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Voice cloning failed: {e}")
        raise HTTPException(status_code=500, detail=f"Voice cloning failed: {str(e)}")
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
