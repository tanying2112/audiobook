"""Hardware Profile Configuration using Pydantic Settings.

Three-tier architecture:
- potato: Pure CPU, fully offline, llama.cpp + Kokoro-ONNX
- cloud_hybrid: Free cloud APIs + local TTS (DEFAULT)
- pro_studio: GPU + VoxCPM2/CosyVoice + DSPy evolution
"""

import os
import platform
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class HardwareSpecs:
    """Hardware specifications for the current machine."""

    def __init__(
        self,
        gpu_enabled: bool = False,
        gpu_name: str = "",
        vram_gb: float = 0.0,
        ram_gb: float = 0.0,
        cpu_cores: int = 0,
        cpu_arch: str = "",
        cuda_version: str = "",
        has_nvidia_smi: bool = False,
    ):
        self.gpu_enabled = gpu_enabled
        self.gpu_name = gpu_name
        self.vram_gb = vram_gb
        self.ram_gb = ram_gb
        self.cpu_cores = cpu_cores
        self.cpu_arch = cpu_arch
        self.cuda_version = cuda_version
        self.has_nvidia_smi = has_nvidia_smi

    @classmethod
    def detect(cls) -> "HardwareSpecs":
        """Auto-detect hardware capabilities."""
        specs = cls()

        # CPU & RAM
        specs.cpu_cores = os.cpu_count() or 4
        specs.cpu_arch = platform.machine()

        try:
            import psutil

            specs.ram_gb = psutil.virtual_memory().total / (1024**3)
        except ImportError:
            specs.ram_gb = 8.0

        # GPU detection
        specs.has_nvidia_smi = cls._check_nvidia_smi()
        if specs.has_nvidia_smi:
            gpu_info = cls._query_nvidia_smi()
            specs.gpu_enabled = True
            specs.gpu_name = gpu_info.get("name", "Unknown GPU")
            specs.vram_gb = gpu_info.get("vram_gb", 0.0)
            specs.cuda_version = gpu_info.get("cuda_version", "")

        return specs

    @staticmethod
    def _check_nvidia_smi() -> bool:
        try:
            subprocess.run(
                ["nvidia-smi", "--version"],
                capture_output=True,
                check=True,
                timeout=5,
            )
            return True
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def _query_nvidia_smi() -> Dict[str, Any]:
        info = {"name": "Unknown", "vram_gb": 0.0, "cuda_version": ""}
        try:
            # Get GPU name and VRAM
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            output = result.stdout.strip()
            if output:
                lines = output.split("\n")
                # Take first GPU
                name, mem = lines[0].split(", ")
                info["name"] = name.strip()
                info["vram_gb"] = float(mem.strip()) / 1024.0

            # Get CUDA version
            result = subprocess.run(
                ["nvidia-smi", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.split("\n"):
                if "CUDA Version" in line:
                    info["cuda_version"] = line.split("CUDA Version:")[1].split()[0]
                    break
        except Exception:
            pass
        return info


class LLMProfileConfig(BaseSettings):
    """LLM configuration for a hardware profile."""

    model_config = SettingsConfigDict(extra="ignore")

    backend: str = "litellm_router"
    models: Dict[str, str] = Field(default_factory=dict)
    stage_model_map: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)
    context_window: int = 8192
    n_threads: int = 4
    n_batch: int = 512
    temperature: float = 0.3
    max_tokens: int = 2048
    local_fallback: Dict[str, Any] = Field(default_factory=dict)
    quota_registry: Dict[str, Any] = Field(default_factory=dict)


class TTSProfileConfig(BaseSettings):
    """TTS configuration for a hardware profile."""

    model_config = SettingsConfigDict(extra="ignore")

    engine: str = "kokoro_onnx"
    model_path: str = "models/kokoro-v1.0.onnx"
    voices_path: str = "models/voices-v1.0.bin"
    dtype: str = "float16"
    compile: bool = False
    voice_design_enabled: bool = False
    reference_audio_enabled: bool = False
    sample_rate: int = 24000
    providers: List[str] = Field(default_factory=lambda: ["CPUExecutionProvider"])
    session_options: Dict[str, Any] = Field(default_factory=dict)
    voice_presets: str = "config/voice_mapping.yaml"
    fallback_chain: List[Dict[str, Any]] = Field(default_factory=list)
    batch_size: int = 1
    kv_cache_reuse: bool = False


class QualityCheckProfileConfig(BaseSettings):
    """Quality check configuration for a hardware profile."""

    model_config = SettingsConfigDict(extra="ignore")

    dnsmos_enabled: bool = False
    asr_enabled: bool = False
    asr_model: str = "sensevoice_small"
    speaker_similarity_enabled: bool = False
    speaker_embed_model: str = "ecapa_tdnn"
    rules_enabled: bool = True
    thresholds: Dict[str, float] = Field(default_factory=dict)


class RoutingProfileConfig(BaseSettings):
    """Routing configuration for a hardware profile."""

    model_config = SettingsConfigDict(extra="ignore")

    strategy: str = "local_only"
    priority_order: List[str] = Field(default_factory=list)
    cost_aware: bool = False


class CostControlProfileConfig(BaseSettings):
    """Cost control configuration for a hardware profile."""

    model_config = SettingsConfigDict(extra="ignore")

    max_cost_per_chapter_usd: float = 0.0
    budget_enforcement: str = "strict"


class DSPyProfileConfig(BaseSettings):
    """DSPy configuration for pro_studio profile."""

    model_config = SettingsConfigDict(extra="ignore")

    enabled: bool = False
    optimizer: str = "BootstrapFewShotWithRandomSearch"
    metric_weights: Dict[str, float] = Field(default_factory=dict)
    budget: Dict[str, Any] = Field(default_factory=dict)
    target_modules: List[str] = Field(default_factory=list)


class VoiceAnchorProfileConfig(BaseSettings):
    """Voice Anchor configuration for pro_studio profile."""

    model_config = SettingsConfigDict(extra="ignore")

    enabled: bool = False
    embedding_model: str = "wavlm_large"
    similarity_threshold: float = 0.85
    max_drift_alerts_per_chapter: int = 3


class HardwareProfileConfig(BaseSettings):
    """Complete hardware profile configuration."""

    model_config = SettingsConfigDict(extra="ignore")

    name: str
    description: str
    hardware: Dict[str, Any]
    llm: LLMProfileConfig
    tts: TTSProfileConfig
    quality_check: QualityCheckProfileConfig
    routing: RoutingProfileConfig
    cost_control: CostControlProfileConfig
    dspy: DSPyProfileConfig = Field(default_factory=DSPyProfileConfig)
    voice_anchor: VoiceAnchorProfileConfig = Field(default_factory=VoiceAnchorProfileConfig)


class HardwareProfile:
    """Hardware profile manager.

    Uses pydantic-settings for type-safe configuration management.
    """

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = Path(__file__).parent / "hardware_profile.yaml"
        self.config_path = Path(config_path)
        self._config: Optional[HardwareProfileConfig] = None
        self._active_profile_name: str = "cloud_hybrid"
        self._hardware_specs: HardwareSpecs = HardwareSpecs.detect()
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        """Load configuration from YAML."""
        with open(self.config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Get active profile
        self._active_profile_name = data.get("active_profile", "cloud_hybrid")
        profiles_data = data.get("profiles", {})

        if self._active_profile_name not in profiles_data:
            raise ValueError(
                f"Active profile '{self._active_profile_name}' not found in config. "
                f"Available: {list(profiles_data.keys())}"
            )

        profile_data = profiles_data[self._active_profile_name]
        self._config = self._parse_profile(self._active_profile_name, profile_data)

        # Auto-detect if enabled and not explicitly set
        auto_detect = data.get("auto_detect", {})
        if auto_detect.get("enabled", True) and not os.getenv("HARDWARE_PROFILE"):
            recommended = self._auto_recommend_profile()
            if recommended != self._active_profile_name:
                print(f"[HardwareProfile] Auto-detected: {recommended} (config: {self._active_profile_name})")

    def _parse_profile(self, name: str, data: Dict[str, Any]) -> HardwareProfileConfig:
        """Parse profile data into typed config objects."""
        return HardwareProfileConfig(
            name=name,
            description=data.get("description", ""),
            hardware=data.get("hardware", {}),
            llm=LLMProfileConfig(**data.get("llm", {})),
            tts=TTSProfileConfig(**data.get("tts", {})),
            quality_check=QualityCheckProfileConfig(**data.get("quality_check", {})),
            routing=RoutingProfileConfig(**data.get("routing", {})),
            cost_control=CostControlProfileConfig(**data.get("cost_control", {})),
            dspy=DSPyProfileConfig(**data.get("dspy", {})),
            voice_anchor=VoiceAnchorProfileConfig(**data.get("voice_anchor", {})),
        )

    def _auto_recommend_profile(self) -> str:
        """Recommend profile based on detected hardware."""
        specs = self._hardware_specs

        if not specs.gpu_enabled or specs.vram_gb < 8 or specs.ram_gb < 16:
            return "potato"
        elif specs.vram_gb >= 16 and specs.ram_gb >= 32:
            return "pro_studio"
        else:
            return "cloud_hybrid"

    @property
    def active_profile(self) -> str:
        return self._active_profile_name

    @property
    def config(self) -> HardwareProfileConfig:
        return self._config

    @property
    def hardware_specs(self) -> HardwareSpecs:
        return self._hardware_specs

    @property
    def llm(self) -> LLMProfileConfig:
        return self._config.llm if self._config else LLMProfileConfig()

    @property
    def tts(self) -> TTSProfileConfig:
        return self._config.tts if self._config else TTSProfileConfig()

    @property
    def quality_check(self) -> QualityCheckProfileConfig:
        return self._config.quality_check if self._config else QualityCheckProfileConfig()

    @property
    def routing(self) -> RoutingProfileConfig:
        return self._config.routing if self._config else RoutingProfileConfig()

    @property
    def cost_control(self) -> CostControlProfileConfig:
        return self._config.cost_control if self._config else CostControlProfileConfig()

    @property
    def dspy(self) -> DSPyProfileConfig:
        return self._config.dspy if self._config else DSPyProfileConfig()

    @property
    def voice_anchor(self) -> VoiceAnchorProfileConfig:
        return self._config.voice_anchor if self._config else VoiceAnchorProfileConfig()

    def get_llm_stage_models(self, stage: str) -> List[Dict[str, Any]]:
        """Get model mapping for a specific stage."""
        if not self._config:
            return []
        return self._config.llm.stage_model_map.get(stage, [])

    def get_tts_fallback_chain(self) -> List[Dict[str, Any]]:
        """Get TTS fallback chain."""
        if not self._config:
            return []
        return self._config.tts.fallback_chain

    def is_gpu_available(self) -> bool:
        return self._hardware_specs.gpu_enabled

    def get_vram_gb(self) -> float:
        return self._hardware_specs.vram_gb

    def get_ram_gb(self) -> float:
        return self._hardware_specs.ram_gb

    def reload(self):
        """Reload configuration from disk."""
        self._load()


# Global singleton managed by DI container
_hardware_profile_instance: Optional["HardwareProfile"] = None
_lock = threading.Lock()


def get_hardware_profile(config_path: Optional[str] = None) -> HardwareProfile:
    """Get HardwareProfile instance."""
    global _hardware_profile_instance
    with _lock:
        if _hardware_profile_instance is None:
            _hardware_profile_instance = HardwareProfile(config_path)
        return _hardware_profile_instance


def reset_hardware_profile():
    """Reset singleton (mainly for testing)."""
    global _hardware_profile_instance
    with _lock:
        _hardware_profile_instance = None


def get_active_profile() -> str:
    """Get active hardware profile name."""
    return get_hardware_profile().active_profile


def is_potato_mode() -> bool:
    """Check if running in potato mode (CPU-only)."""
    return get_active_profile() == "potato"


def is_cloud_hybrid_mode() -> bool:
    """Check if running in cloud hybrid mode."""
    return get_active_profile() == "cloud_hybrid"


def is_pro_studio_mode() -> bool:
    """Check if running in pro studio mode (GPU-enabled)."""
    return get_active_profile() == "pro_studio"


if __name__ == "__main__":
    # Test auto-detection
    specs = HardwareSpecs.detect()
    print("Detected Hardware:")
    print(f"  CPU: {specs.cpu_cores} cores ({specs.cpu_arch})")
    print(f"  RAM: {specs.ram_gb:.1f} GB")
    print(f"  GPU: {specs.gpu_enabled} ({specs.gpu_name}, VRAM: {specs.vram_gb:.1f} GB)")

    # Load profile
    profile = get_hardware_profile()
    print(f"\nActive Profile: {profile.active_profile}")
    print(f"  LLM Backend: {profile.llm.backend}")
    print(f"  TTS Engine: {profile.tts.engine}")
    print(f"  Quality DNSMOS: {profile.quality_check.dnsmos_enabled}")
    print(f"  Voice Anchor: {profile.voice_anchor.enabled}")