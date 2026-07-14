# Audiobook Studio - TTS Module
"""Text-to-Speech engines and voice cloning."""

from .circuit_breaker import CircuitBreaker
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
from .rate_limiter import (
    DEFAULT_TTS_RATE_LIMITS,
    ProviderRateLimiter,
    RateLimitConfig,
    TTSRateLimiter,
    create_tts_rate_limiter,
    get_tts_rate_limiter,
)
from .port import (
    TTSStatus,
    TTSVoiceAnchor,
    TTSProsody,
    TTSTaskPayload,
    TTSTaskResult,
    TTSTaskStatus,
    RemoteTTSPort,
    PortFactory,
)
from .port_factory import create_port, get_port, set_port, reset_port, make_port_factory
from .remote_voxcpm2_client import RemoteVoxCPM2Client, RemoteVoxCPM2Config, create_remote_voxcpm2_client
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
    # Remote VoxCPM2 client
    "RemoteVoxCPM2Client",
    "RemoteVoxCPM2Config",
    "create_remote_voxcpm2_client",
    # Port Contract (Hermes-Celery boundary)
    "TTSStatus",
    "TTSVoiceAnchor",
    "TTSProsody",
    "TTSTaskPayload",
    "TTSTaskResult",
    "TTSTaskStatus",
    "RemoteTTSPort",
    "PortFactory",
    # Port Factory
    "create_port",
    "get_port",
    "set_port",
    "reset_port",
    "make_port_factory",
    # Circuit Breaker
    "CircuitBreaker",
    # Rate Limiter
    "TTSRateLimiter",
    "RateLimitConfig",
    "ProviderRateLimiter",
    "create_tts_rate_limiter",
    "get_tts_rate_limiter",
    "DEFAULT_TTS_RATE_LIMITS",
    # Model Downloader
    "ensure_models_available",
    "get_model_paths",
    "verify_models",
    "download_all_models",
    "REQUIRED_FILES",
    "FALLBACK_FILES",
]
