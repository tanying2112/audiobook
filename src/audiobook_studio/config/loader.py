"""Configuration loading utilities for Audiobook Studio.

Provides Pydantic-based configuration loading with:
- Schema validation at load time
- File lock protection for concurrent access
- Hot-reload support with mtime checking
- Environment variable interpolation (optional)
"""

import fcntl
import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

logger = logging.getLogger(__name__)

# =============================================================================
# Pydantic Configuration Models
# =============================================================================


class OverallQualityThresholds(BaseModel):
    """Overall quality threshold configuration."""

    min_acceptable_score: float = Field(default=0.7, ge=0, le=1)
    excellent_score: float = Field(default=0.9, ge=0, le=1)
    schema_compliance_rate: float = Field(default=0.99, ge=0, le=1)


class DimensionThresholds(BaseModel):
    """Individual dimension threshold configuration."""

    speaker_clarity: float = Field(default=0.85, ge=0, le=1)
    emotion_match: float = Field(default=0.80, ge=0, le=1)
    prosody_naturalness: float = Field(default=0.75, ge=0, le=1)
    text_audio_alignment: float = Field(default=0.80, ge=0, le=1)


class ErrorThresholds(BaseModel):
    """Error count threshold configuration."""

    max_silent_segments: int = Field(default=0, ge=0)
    max_stuttering_issues: int = Field(default=0, ge=0)
    max_truncation_issues: int = Field(default=0, ge=0)
    max_sensitive_content_hits: int = Field(default=0, ge=0)


class FeedbackThresholds(BaseModel):
    """Feedback loop trigger configuration."""

    wrong_speaker_consecutive: int = Field(default=3, ge=1)
    emotion_mismatch_ratio: float = Field(default=0.20, ge=0, le=1)
    low_quality_regeneration_ratio: float = Field(default=0.3, ge=0, le=1)


class AudioThresholds(BaseModel):
    """Audio analysis threshold configuration."""

    silence_threshold_db: float = Field(default=-40)
    clipping_threshold_percent: float = Field(default=0.1, ge=0)
    duration_match_threshold_percent: float = Field(default=30, ge=0)
    volume_normalization_target_db: float = Field(default=-20)
    low_volume_threshold_db: float = Field(default=-30)
    high_volume_threshold_db: float = Field(default=-1)


class QualityThresholdsConfig(BaseModel):
    """Complete quality thresholds configuration."""

    overall: OverallQualityThresholds = Field(default_factory=OverallQualityThresholds)
    dimensions: DimensionThresholds = Field(default_factory=DimensionThresholds)
    errors: ErrorThresholds = Field(default_factory=ErrorThresholds)
    feedback: FeedbackThresholds = Field(default_factory=FeedbackThresholds)
    audio: AudioThresholds = Field(default_factory=AudioThresholds)


# Constitutional Rules Configuration Models


class CharacterConsistencyRules(BaseModel):
    """Character consistency rule configuration."""

    min_consistency_score: float = Field(default=0.9, ge=0, le=1)
    verify_voice_binding: bool = Field(default=True)
    wrong_speaker_consecutive_threshold: int = Field(default=3, ge=1)
    max_voice_drift_per_chapter: float = Field(default=0.05, ge=0, le=1)


class EmotionCoherenceRules(BaseModel):
    """Emotion coherence rule configuration."""

    min_emotion_match: float = Field(default=0.80, ge=0, le=1)
    max_mismatch_ratio: float = Field(default=0.20, ge=0, le=1)
    require_context_continuity: bool = Field(default=True)
    max_intensity_deviation: float = Field(default=0.15, ge=0, le=1)


class TextNormsChinese(BaseModel):
    """Chinese text normalization rules."""

    avoid_english_mixing: bool = Field(default=True)
    classical_modern_balance: float = Field(default=0.3, ge=0, le=1)
    normalize_punctuation: bool = Field(default=True)
    traditional_to_simplified: bool = Field(default=True)


class TextNormsEnglish(BaseModel):
    """English text normalization rules."""

    avoid_chinese_pinyin: bool = Field(default=True)
    formality_match_context: bool = Field(default=True)
    normalize_contractions: bool = Field(default=True)


class TextNormsGeneral(BaseModel):
    """General text normalization rules."""

    max_consecutive_repeats: int = Field(default=3, ge=1)
    strip_zero_width: bool = Field(default=True)
    normalize_whitespace: bool = Field(default=True)
    max_segment_chars: int = Field(default=500, ge=10)
    min_segment_chars: int = Field(default=10, ge=1)


class TextNormsConfig(BaseModel):
    """Complete text norms configuration."""

    chinese: TextNormsChinese = Field(default_factory=TextNormsChinese)
    english: TextNormsEnglish = Field(default_factory=TextNormsEnglish)
    general: TextNormsGeneral = Field(default_factory=TextNormsGeneral)


class ConstitutionalRulesConfig(BaseModel):
    """Complete constitutional rules configuration."""

    character_consistency: CharacterConsistencyRules = Field(
        default_factory=CharacterConsistencyRules
    )
    emotion_coherence: EmotionCoherenceRules = Field(
        default_factory=EmotionCoherenceRules
    )
    text_norms: TextNormsConfig = Field(default_factory=TextNormsConfig)
    safety: Dict[str, Any] = Field(default_factory=dict)
    quality: Dict[str, Any] = Field(default_factory=dict)
    legal: Dict[str, Any] = Field(default_factory=dict)
    technical: Dict[str, Any] = Field(default_factory=dict)
    adaptation: Dict[str, Any] = Field(default_factory=dict)
    evolution: Dict[str, Any] = Field(default_factory=dict)


# Difficulty Weights Configuration Models


class DifficultyWeightsConfig(BaseModel):
    """Difficulty weight configuration."""

    char_count_weight: float = Field(default=0.30, ge=0, le=1)
    dialect_ratio_weight: float = Field(default=0.25, ge=0, le=1)
    term_density_weight: float = Field(default=0.20, ge=0, le=1)
    emotion_complexity_weight: float = Field(default=0.15, ge=0, le=1)
    speaker_count_weight: float = Field(default=0.10, ge=0, le=1)
    base_difficulty: float = Field(default=0.1, ge=0, le=1)
    difficulty_tiers: Dict[str, float] = Field(
        default_factory=lambda: {"easy": 0.3, "medium": 0.5, "hard": 0.7, "expert": 1.0}
    )


# Voice Mapping Configuration Models


class VoiceMappingEntry(BaseModel):
    """Single voice mapping entry."""

    voice_id: str
    description: str
    language: str
    age_range: List[int] = Field(min_length=2, max_length=2)
    gender: Literal["male", "female", "neutral"]

    @field_validator("age_range")
    @classmethod
    def validate_age_range(cls, v: List[int]) -> List[int]:
        if v[0] > v[1]:
            raise ValueError("age_range[0] must be <= age_range[1]")
        return v


class VoiceMappingConfig(BaseModel):
    """Complete voice mapping configuration."""

    male_child: VoiceMappingEntry
    male_teenager: VoiceMappingEntry
    male_young: VoiceMappingEntry
    male_middle: VoiceMappingEntry
    male_elder: VoiceMappingEntry
    female_child: VoiceMappingEntry
    female_teenager: VoiceMappingEntry
    female_young: VoiceMappingEntry
    female_middle: VoiceMappingEntry
    female_elder: VoiceMappingEntry
    neutral_narrator: VoiceMappingEntry
    special_elderly_wiseman: VoiceMappingEntry
    special_robot: VoiceMappingEntry
    special_monster: VoiceMappingEntry
    voice_mapping_en: Dict[str, VoiceMappingEntry] = Field(default_factory=dict)


# Promotion Thresholds Configuration Models


class GoldenRegressionBaseline(BaseModel):
    """Golden regression baseline configuration."""

    max_quality_regression: float = Field(default=0.01, ge=0)
    max_speaker_clarity_regression: float = Field(default=0.02, ge=0)
    max_emotion_match_regression: float = Field(default=0.02, ge=0)
    max_prosody_regression: float = Field(default=0.02, ge=0)
    max_alignment_regression: float = Field(default=0.02, ge=0)
    max_error_rate_increase: float = Field(default=0.005, ge=0)
    min_evaluation_samples: int = Field(default=50, ge=1)


class CostEfficiencyConfig(BaseModel):
    """Cost efficiency configuration."""

    max_cost_increase_ratio: float = Field(default=1.1, ge=0)
    min_cost_savings_ratio: float = Field(default=0.85, ge=0)


class LatencyConfig(BaseModel):
    """Latency configuration."""

    max_latency_increase_ratio: float = Field(default=1.2, ge=0)
    fast_tier_target_ms: int = Field(default=2000, ge=0)
    quality_tier_target_ms: int = Field(default=5000, ge=0)


class StabilityConfig(BaseModel):
    """Stability configuration."""

    min_success_rate: float = Field(default=0.99, ge=0, le=1)
    max_consecutive_failures: int = Field(default=2, ge=1)
    evaluation_period_hours: int = Field(default=24, ge=1)


class ABTestingConfig(BaseModel):
    """A/B testing configuration."""

    min_canary_traffic_pct: float = Field(default=5, ge=0, le=100)
    max_canary_traffic_pct: float = Field(default=50, ge=0, le=100)
    min_experiment_duration_hours: int = Field(default=4, ge=1)
    significance_threshold: float = Field(default=0.05, ge=0, le=1)
    min_effect_size: float = Field(default=0.01, ge=0)


class PromotionThresholdsConfig(BaseModel):
    """Complete promotion thresholds configuration."""

    quality_score_delta: float = Field(default=0.02, ge=0)
    golden_regression_baseline: GoldenRegressionBaseline = Field(
        default_factory=GoldenRegressionBaseline
    )
    cost_efficiency: CostEfficiencyConfig = Field(default_factory=CostEfficiencyConfig)
    latency: LatencyConfig = Field(default_factory=LatencyConfig)
    stability: StabilityConfig = Field(default_factory=StabilityConfig)
    ab_testing: ABTestingConfig = Field(default_factory=ABTestingConfig)


# Pipeline Configuration Model


class PipelineConfig(BaseModel):
    """Complete pipeline configuration schema."""

    quality_thresholds: QualityThresholdsConfig = Field(
        default_factory=QualityThresholdsConfig
    )
    constitutional_rules: ConstitutionalRulesConfig = Field(
        default_factory=ConstitutionalRulesConfig
    )
    difficulty_weights: DifficultyWeightsConfig = Field(
        default_factory=DifficultyWeightsConfig
    )
    voice_mapping: VoiceMappingConfig = Field(
        default_factory=lambda: _get_default_voice_mapping()
    )
    promotion_thresholds: PromotionThresholdsConfig = Field(
        default_factory=PromotionThresholdsConfig
    )


def _get_default_voice_mapping() -> VoiceMappingConfig:
    """Return default voice mapping configuration."""
    return VoiceMappingConfig(
        male_child=VoiceMappingEntry(
            voice_id="male_child_001",
            description="男童声",
            language="zh-CN",
            age_range=[0, 12],
            gender="male",
        ),
        male_teenager=VoiceMappingEntry(
            voice_id="male_teen_001",
            description="男青少年声",
            language="zh-CN",
            age_range=[13, 17],
            gender="male",
        ),
        male_young=VoiceMappingEntry(
            voice_id="male_young_001",
            description="男青年声",
            language="zh-CN",
            age_range=[18, 35],
            gender="male",
        ),
        male_middle=VoiceMappingEntry(
            voice_id="male_middle_001",
            description="男中年声",
            language="zh-CN",
            age_range=[36, 55],
            gender="male",
        ),
        male_elder=VoiceMappingEntry(
            voice_id="male_elder_001",
            description="男老年声",
            language="zh-CN",
            age_range=[56, 120],
            gender="male",
        ),
        female_child=VoiceMappingEntry(
            voice_id="female_child_001",
            description="女童声",
            language="zh-CN",
            age_range=[0, 12],
            gender="female",
        ),
        female_teenager=VoiceMappingEntry(
            voice_id="female_teen_001",
            description="女青少年声",
            language="zh-CN",
            age_range=[13, 17],
            gender="female",
        ),
        female_young=VoiceMappingEntry(
            voice_id="female_young_001",
            description="女青年声",
            language="zh-CN",
            age_range=[18, 35],
            gender="female",
        ),
        female_middle=VoiceMappingEntry(
            voice_id="female_middle_001",
            description="女中年声",
            language="zh-CN",
            age_range=[36, 55],
            gender="female",
        ),
        female_elder=VoiceMappingEntry(
            voice_id="female_elder_001",
            description="女老年声",
            language="zh-CN",
            age_range=[56, 120],
            gender="female",
        ),
        neutral_narrator=VoiceMappingEntry(
            voice_id="neutral_narrator_001",
            description="中性旁白声",
            language="zh-CN",
            age_range=[25, 50],
            gender="neutral",
        ),
        special_elderly_wiseman=VoiceMappingEntry(
            voice_id="special_wiseman_001",
            description="智慧老人声",
            language="zh-CN",
            age_range=[60, 100],
            gender="male",
        ),
        special_robot=VoiceMappingEntry(
            voice_id="special_robot_001",
            description="机器人声",
            language="zh-CN",
            age_range=[0, 999],
            gender="neutral",
        ),
        special_monster=VoiceMappingEntry(
            voice_id="special_monster_001",
            description="怪物声",
            language="zh-CN",
            age_range=[0, 999],
            gender="neutral",
        ),
        voice_mapping_en={},
    )


# Contract Versions Configuration Models


class StageContract(BaseModel):
    """Stage contract configuration."""

    current: int = Field(default=1, ge=1)
    min_compatible: int = Field(default=1, ge=1)
    input_schema: str = ""
    output_schema: str = ""


class GlobalContract(BaseModel):
    """Global contract configuration."""

    current: int = Field(default=1, ge=1)
    min_compatible: int = Field(default=1, ge=1)
    schema_name: str = Field(default="HARNESS_v1", alias="schema")

    model_config = {"populate_by_name": True}


class CompatibilityConfig(BaseModel):
    """Compatibility configuration."""

    version_format: str = "major.minor.patch"
    breaking_on_major_change: bool = True
    warn_on_minor_change: bool = True


class DeprecationConfig(BaseModel):
    """Deprecation configuration."""

    cycles_before_removal: int = Field(default=3, ge=1)
    warn_on_deprecated_use: bool = True
    migration_guide_url: str = "docs/migration_guide.md"


class ValidationConfig(BaseModel):
    """Validation configuration."""

    strict_mode: bool = True
    coerce_types: bool = True
    validate_enum_values: bool = True
    min_compliance_rate: float = Field(default=0.99, ge=0, le=1)


class ContractVersionsConfig(BaseModel):
    """Complete contract versions configuration."""

    global_contract: GlobalContract = Field(
        default_factory=GlobalContract, alias="global"
    )
    stages: Dict[str, StageContract] = Field(default_factory=dict)
    compatibility: CompatibilityConfig = Field(default_factory=CompatibilityConfig)
    deprecation: DeprecationConfig = Field(default_factory=DeprecationConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)

    model_config = {"populate_by_name": True}


# =============================================================================
# Configuration Loader with File Lock and Hot-Reload
# =============================================================================


class ConfigFileLock:
    """File-based lock for concurrent configuration access."""

    _locks: Dict[str, threading.RLock] = {}
    _file_handles: Dict[str, int] = {}

    @classmethod
    @contextmanager
    def acquire(cls, config_path: str):
        """Acquire a lock for a specific config file."""
        path_str = str(Path(config_path).resolve())

        if path_str not in cls._locks:
            cls._locks[path_str] = threading.RLock()

        lock = cls._locks[path_str]
        try:
            lock.acquire()
            yield
        finally:
            lock.release()


class ConfigLoader:
    """Pydantic-based configuration loader with schema validation and hot-reload."""

    def __init__(self):
        self._cache: Dict[str, tuple[Dict[str, Any], float]] = {}
        self._lock = threading.RLock()

    def _read_with_file_lock(self, path: Path) -> str:
        """Read file content with file-level lock for atomic reads."""
        fd = None
        try:
            fd = open(path, "r", encoding="utf-8")
            fcntl.flock(fd.fileno(), fcntl.LOCK_SH)
            return fd.read()
        finally:
            if fd:
                try:
                    fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
                    fd.close()
                except Exception:
                    pass

    def _load_yaml_safe(self, path: Path) -> Dict[str, Any]:
        """Load YAML file with proper error handling."""
        try:
            content = self._read_with_file_lock(path)
            data = yaml.safe_load(content)
            return data if isinstance(data, dict) else {}
        except yaml.YAMLError as e:
            logger.error(f"Failed to parse YAML in {path}: {e}")
            return {}
        except Exception as e:
            logger.error(f"Error reading {path}: {e}")
            return {}

    def _validate_with_pydantic(
        self, data: Dict[str, Any], model_class: type[BaseModel], config_name: str
    ) -> Dict[str, Any]:
        """Validate config data against Pydantic model."""
        try:
            validated = model_class.model_validate(data)
            return validated.model_dump(mode="json", exclude_none=True)
        except ValidationError as e:
            logger.warning(
                f"Config validation warning for {config_name}: {e.error_count()} errors"
            )
            for error in e.errors():
                logger.warning(
                    f"  - {'.'.join(str(x) for x in error['loc'])}: {error['msg']} "
                    f"(type={error['type']})"
                )
            # Return data with defaults merged for missing fields
            return model_class.model_validate(data).model_dump(
                mode="json", exclude_none=True
            )

    def load_quality_thresholds(
        self, config_path: str = "./config/quality_thresholds.yaml"
    ) -> Dict[str, Any]:
        """Load and validate quality thresholds configuration."""
        path = Path(config_path)

        with ConfigFileLock.acquire(config_path):
            if not path.exists():
                logger.warning(f"Quality thresholds file not found: {config_path}")
                return self._get_default_quality_thresholds()

            data = self._load_yaml_safe(path)

            # Validate against Pydantic model
            return self._validate_with_pydantic(
                data, QualityThresholdsConfig, "quality_thresholds"
            )

    def _get_default_quality_thresholds(self) -> Dict[str, Any]:
        """Return default quality thresholds."""
        return QualityThresholdsConfig().model_dump(mode="json", exclude_none=True)

    def load_constitutional_rules(
        self, config_path: str = "./config/constitutional_rules.yaml"
    ) -> Dict[str, Any]:
        """Load and validate constitutional rules configuration."""
        path = Path(config_path)

        with ConfigFileLock.acquire(config_path):
            if not path.exists():
                logger.warning(f"Constitutional rules file not found: {config_path}")
                return {}

            data = self._load_yaml_safe(path)
            if not data:
                return {}

            # Validate nested structure
            try:
                validated = ConstitutionalRulesConfig.model_validate(data)
                return validated.model_dump(mode="json", exclude_none=True)
            except ValidationError as e:
                logger.warning(
                    f"Constitutional rules validation warning: {e.error_count()} errors"
                )
                return data

    def load_contract_versions(
        self, config_path: str = "./config/contract_versions.yaml"
    ) -> Dict[str, Any]:
        """Load and validate contract versions configuration."""
        path = Path(config_path)

        with ConfigFileLock.acquire(config_path):
            if not path.exists():
                logger.warning(f"Contract versions file not found: {config_path}")
                return self._get_default_contract_versions()

            data = self._load_yaml_safe(path)
            return self._validate_with_pydantic(
                data, ContractVersionsConfig, "contract_versions"
            )

    def _get_default_contract_versions(self) -> Dict[str, Any]:
        """Return default contract versions."""
        default = ContractVersionsConfig().model_dump(
            mode="json", exclude_none=True, by_alias=True
        )
        # Ensure 'global' key is used instead of 'global_contract'
        if "global_contract" in default:
            default["global"] = default.pop("global_contract")
        return default

    def load_pipeline_config(
        self, config_path: str = "./config/pipeline.yaml"
    ) -> Dict[str, Any]:
        """Load pipeline configuration with hot-reload support and schema validation."""
        path = Path(config_path)

        with self._lock:
            with ConfigFileLock.acquire(config_path):
                if not path.exists():
                    logger.warning(f"Pipeline config file not found: {config_path}")
                    return self._get_default_pipeline_config()

                current_mtime = path.stat().st_mtime

                # Check cache validity
                cache_entry = self._cache.get(config_path)
                if cache_entry and cache_entry[1] >= current_mtime:
                    return cache_entry[0]

                # Load and validate
                data = self._load_yaml_safe(path)

                # Validate against full pipeline schema
                validated = self._validate_with_pydantic(
                    data, PipelineConfig, "pipeline_config"
                )

                # Merge with defaults for missing top-level keys
                defaults = self._get_default_pipeline_config()
                merged = {**defaults, **validated}

                # Update cache
                self._cache[config_path] = (merged, current_mtime)
                logger.info(
                    f"Loaded and validated pipeline configuration from {config_path}"
                )

                return merged

    def _get_default_pipeline_config(self) -> Dict[str, Any]:
        """Return default pipeline configuration."""
        return PipelineConfig().model_dump(mode="json", exclude_none=True)

    def clear_cache(self, config_path: Optional[str] = None) -> None:
        """Clear configuration cache."""
        with self._lock:
            if config_path:
                self._cache.pop(config_path, None)
            else:
                self._cache.clear()
        logger.info(
            "Configuration cache cleared"
            + (f" for {config_path}" if config_path else "")
        )

    def reload_if_changed(
        self, config_path: str, last_modified: Optional[float] = None
    ) -> tuple[Dict[str, Any], Optional[float]]:
        """Check if config file has changed and reload if necessary."""
        path = Path(config_path)

        with ConfigFileLock.acquire(config_path):
            if not path.exists():
                return {}, last_modified

            current_modified = path.stat().st_mtime

            if last_modified is None or current_modified > last_modified:
                # File has changed, reload
                if "quality_thresholds" in config_path:
                    config = self.load_quality_thresholds(config_path)
                elif "contract_versions" in config_path:
                    config = self.load_contract_versions(config_path)
                elif "constitutional_rules" in config_path:
                    config = self.load_constitutional_rules(config_path)
                elif "pipeline" in config_path:
                    config = self.load_pipeline_config(config_path)
                else:
                    config = self._load_yaml_safe(path)
                return config, current_modified
            else:
                # No change, load from cache or file
                with self._lock:
                    if config_path in self._cache:
                        return self._cache[config_path][0], last_modified

                if "quality_thresholds" in config_path:
                    return self.load_quality_thresholds(config_path), last_modified
                elif "contract_versions" in config_path:
                    return self.load_contract_versions(config_path), last_modified
                else:
                    return self.load_constitutional_rules(config_path), last_modified


# =============================================================================
# Backward-Compatible Module API
# =============================================================================

# Global loader instance
_config_loader = ConfigLoader()

# Cache for backward compatibility
_pipeline_config_cache: Optional[Dict[str, Any]] = None
_pipeline_config_mtime: Optional[float] = None
_pipeline_config_lock = threading.RLock()


def load_quality_thresholds(
    config_path: str = "./config/quality_thresholds.yaml",
) -> Dict[str, Any]:
    """Load quality thresholds from YAML file with validation."""
    return _config_loader.load_quality_thresholds(config_path)


def load_constitutional_rules(
    config_path: str = "./config/constitutional_rules.yaml",
) -> Dict[str, Any]:
    """Load constitutional rules from YAML file with validation."""
    return _config_loader.load_constitutional_rules(config_path)


def load_contract_versions(
    config_path: str = "./config/contract_versions.yaml",
) -> Dict[str, Any]:
    """Load contract versions from YAML file with validation."""
    return _config_loader.load_contract_versions(config_path)


def load_pipeline_config(config_path: str = "./config/pipeline.yaml") -> Dict[str, Any]:
    """Load pipeline configuration with hot-reload support and validation."""
    return _config_loader.load_pipeline_config(config_path)


def get_quality_thresholds(
    config_path: str = "./config/pipeline.yaml",
) -> Dict[str, Any]:
    """Get quality thresholds from pipeline configuration."""
    config = load_pipeline_config(config_path)
    return config.get("quality_thresholds", {})


def get_constitutional_rules(
    config_path: str = "./config/pipeline.yaml",
) -> Dict[str, Any]:
    """Get constitutional rules from pipeline configuration."""
    config = load_pipeline_config(config_path)
    return config.get("constitutional_rules", {})


def get_difficulty_weights(
    config_path: str = "./config/pipeline.yaml",
) -> Dict[str, Any]:
    """Get difficulty weights from pipeline configuration."""
    config = load_pipeline_config(config_path)
    return config.get("difficulty_weights", {})


def get_voice_mapping(config_path: str = "./config/pipeline.yaml") -> Dict[str, Any]:
    """Get voice mapping from pipeline configuration."""
    config = load_pipeline_config(config_path)
    return config.get("voice_mapping", {})


def get_promotion_thresholds(
    config_path: str = "./config/pipeline.yaml",
) -> Dict[str, Any]:
    """Get promotion thresholds from pipeline configuration."""
    config = load_pipeline_config(config_path)
    return config.get("promotion_thresholds", {})


def reload_config_if_changed(
    config_path: str, last_modified: Optional[float] = None
) -> tuple[Dict[str, Any], Optional[float]]:
    """Check if config file has changed and reload if necessary."""
    return _config_loader.reload_if_changed(config_path, last_modified)


def clear_config_cache(config_path: Optional[str] = None) -> None:
    """Clear configuration cache."""
    _config_loader.clear_cache(config_path)


def load_hardware_profile(config_path: str = "./config/hardware_profile.yaml"):
    """Load hardware profile configuration."""
    from .hardware_profile import get_hardware_profile

    return get_hardware_profile(config_path)


def get_hardware_profile_instance(config_path: str = "./config/hardware_profile.yaml"):
    """Get hardware profile singleton instance."""
    return load_hardware_profile(config_path)


# Backward compatibility defaults (kept for existing code)
DEFAULT_PIPELINE_CONFIG_PATH = "./config/pipeline.yaml"


def load_rules(
    config_path: str = "./config/constitutional_rules.yaml",
) -> Dict[str, Any]:
    """Load constitutional rules (standalone function for backward compatibility)."""
    from .loader import ConfigLoader

    loader = ConfigLoader()
    return loader.load_constitutional_rules(config_path)
