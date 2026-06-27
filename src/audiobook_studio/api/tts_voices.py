"""TTS Voice enumeration API endpoint."""

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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
    engines = {}

    # Kokoro (local, always available)
    engines["kokoro"] = TTSEngine(
        id="kokoro",
        name="Kokoro ONNX",
        available=True,
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
    voxcpm_available = False  # TODO: Check actual availability
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

    return TTSVoicesResponse(
        engines=engines,
        total_voices=total_voices,
        default_engine="kokoro",
        default_voice="kokoro_narrator",
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