# Audiobook Studio - TTS Module
"""Text-to-Speech engines and voice cloning."""

from .clone import (
    AudioQuality,
    VoiceCloner,
    VoiceCloningManager,
    VoicePrint,
    VoiceSample,
    clone_voice,
    load_voice_print,
)
from .engine import (
    EngineRegistry,
    SynthesisResult,
    TTSEngine,
    VoiceInfo,
    cleanup_all_engines,
    get_engine,
    get_engine_registry,
    initialize_all_engines,
    register_engine,
)
from .kokoro_backend import KokoroBackend, create_kokoro_backend
from .model_downloader import (
    FALLBACK_FILES,
    REQUIRED_FILES,
    download_all_models,
    ensure_models_available,
    get_model_paths,
    verify_models,
)
from .voxcpm2_backend import VoxCPM2Backend, create_voxcpmp2_backend

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
    "VoiceCloningManager",
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
