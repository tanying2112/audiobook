# Audiobook Studio - TTS Module
"""Text-to-Speech engines and voice cloning."""

from .engine import (
    TTSEngine,
    VoiceInfo,
    SynthesisResult,
    EngineRegistry,
    get_engine_registry,
    register_engine,
    get_engine,
    initialize_all_engines,
    cleanup_all_engines,
)
from .clone import (
    VoiceCloner,
    VoiceSample,
    VoicePrint,
    AudioQuality,
    clone_voice,
    load_voice_print,
)
from .kokoro_backend import KokoroBackend, create_kokoro_backend
from .voxcpm2_backend import VoxCPM2Backend, create_voxcpmp2_backend
from .model_downloader import (
    ensure_models_available,
    get_model_paths,
    verify_models,
    download_all_models,
    REQUIRED_FILES,
    FALLBACK_FILES,
)

__all__ = [
    # Engine abstraction
    "TTSEngine",
    "VoiceInfo",
    "SynthesisResult",
    "EngineRegistry",
    "get_engine_registry",
    "register_engine",
    "get_engine",
    "initialize_all_engines",
    "cleanup_all_engines",
    # Voice cloning
    "VoiceCloner",
    "VoiceSample",
    "VoicePrint",
    "AudioQuality",
    "clone_voice",
    "load_voice_print",
    # Backends
    "KokoroBackend",
    "create_kokoro_backend",
    "VoxCPM2Backend",
    "create_voxcpmp2_backend",
    # Model Downloader
    "ensure_models_available",
    "get_model_paths",
    "verify_models",
    "download_all_models",
    "REQUIRED_FILES",
    "FALLBACK_FILES",
]