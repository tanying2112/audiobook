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
from .edge_tts_engine import EdgeTTSEngine, create_edge_tts_engine
from .edge_tts_port import EdgeTTSPort, create_edge_tts_port
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
from .fake_port import FakeRemoteTTSPort, MockRemoteTTSPort
from .kokoro_backend import KokoroBackend, create_kokoro_backend
from .kokoro_port import KokoroPort, create_kokoro_port
from .model_downloader import (
    FALLBACK_FILES,
    REQUIRED_FILES,
    download_all_models,
    ensure_models_available,
    get_model_paths,
    verify_models,
)
from .port import (
    PortFactory,
    RemoteTTSPort,
    TTSProsody,
    TTSStatus,
    TTSTaskPayload,
    TTSTaskResult,
    TTSTaskStatus,
    TTSVoiceAnchor,
)
from .port_factory import create_port, get_port, make_port_factory, reset_port, set_port
from .rate_limiter import (
    DEFAULT_TTS_RATE_LIMITS,
    ProviderRateLimiter,
    RateLimitConfig,
    TTSRateLimiter,
    create_tts_rate_limiter,
    get_tts_rate_limiter,
)
from .remote_voxcpm2_client import RemoteVoxCPM2Client, RemoteVoxCPM2Config, create_remote_voxcpm2_client
from .remote_voxcpm2_port import (
    PortConnectionError,
    PortError,
    PortRemoteError,
    PortTimeoutError,
    RemoteVoxCPM2Port,
    RemoteVoxCPM2PortConfig,
    create_remote_voxcpm2_port,
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
    # Remote VoxCPM2 client (legacy)
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
    # Port Implementations
    "FakeRemoteTTSPort",
    "MockRemoteTTSPort",
    "RemoteVoxCPM2Port",
    "RemoteVoxCPM2PortConfig",
    "create_remote_voxcpm2_port",
    "EdgeTTSPort",
    "create_edge_tts_port",
    "KokoroPort",
    "create_kokoro_port",
    # Port Factory
    "create_port",
    "get_port",
    "set_port",
    "reset_port",
    "make_port_factory",
    # Port Exceptions
    "PortError",
    "PortTimeoutError",
    "PortConnectionError",
    "PortRemoteError",
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
