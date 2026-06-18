"""Configuration loading utilities for Audiobook Studio.

Provides functions to load and manage YAML configuration files with hot-reload
support for constitutional rules and other system parameters.
"""

import yaml
from pathlib import Path
from typing import Dict, Any, Optional
import logging
import threading

logger = logging.getLogger(__name__)

# Global cache for pipeline config with hot-reload support
_pipeline_config_cache: Optional[Dict[str, Any]] = None
_pipeline_config_mtime: Optional[float] = None
_pipeline_config_lock = threading.RLock()

# Default pipeline config path
DEFAULT_PIPELINE_CONFIG_PATH = "./config/pipeline.yaml"


def load_rules(config_path: str = "./config/constitutional_rules.yaml") -> Dict[str, Any]:
    """Load constitutional rules from YAML file with error handling.

    Args:
        config_path: Path to the constitutional rules YAML file

    Returns:
        Dictionary containing the loaded rules, or empty dict if file not found/error

    Note:
        This function supports hot-reloading - calling it multiple times will
        return the current contents of the file, allowing runtime updates
        without restarting the application.
    """
    try:
        path = Path(config_path)
        if not path.exists():
            logger.warning(f"Constitutional rules file not found: {config_path}")
            return {}

        with open(path, 'r', encoding='utf-8') as f:
            rules = yaml.safe_load(f)

        logger.info(f"Loaded constitutional rules from {config_path}")
        return rules if isinstance(rules, dict) else {}

    except yaml.YAMLError as e:
        logger.error(f"Failed to parse YAML in {config_path}: {e}")
        return {}
    except Exception as e:
        logger.error(f"Unexpected error loading rules from {config_path}: {e}")
        return {}


def load_quality_thresholds(config_path: str = "./config/quality_thresholds.yaml") -> Dict[str, Any]:
    """Load quality thresholds from YAML file.

    Args:
        config_path: Path to the quality thresholds YAML file

    Returns:
        Dictionary containing the loaded quality thresholds, or default dict if file not found/error
    """
    try:
        path = Path(config_path)
        if not path.exists():
            logger.warning(f"Quality thresholds file not found: {config_path}")
            return _get_default_quality_thresholds()

        with open(path, 'r', encoding='utf-8') as f:
            thresholds = yaml.safe_load(f)

        logger.info(f"Loaded quality thresholds from {config_path}")
        return thresholds if isinstance(thresholds, dict) else _get_default_quality_thresholds()

    except yaml.YAMLError as e:
        logger.error(f"Failed to parse YAML in {config_path}: {e}")
        return _get_default_quality_thresholds()
    except Exception as e:
        logger.error(f"Unexpected error loading quality thresholds from {config_path}: {e}")
        return _get_default_quality_thresholds()


def _get_default_quality_thresholds() -> Dict[str, Any]:
    """Return default quality thresholds when config file is not available."""
    return {
        "overall": {
            "min_acceptable_score": 0.7,
            "excellent_score": 0.9,
            "schema_compliance_rate": 0.99
        },
        "dimensions": {
            "speaker_clarity": 0.85,
            "emotion_match": 0.80,
            "prosody_naturalness": 0.75,
            "text_audio_alignment": 0.80
        },
        "errors": {
            "max_silent_segments": 0,
            "max_stuttering_issues": 0,
            "max_truncation_issues": 0,
            "max_sensitive_content_hits": 0
        },
        "feedback": {
            "wrong_speaker_consecutive": 3,
            "emotion_mismatch_ratio": 0.20,
            "low_quality_regeneration_ratio": 0.3
        },
        "audio": {
            "silence_threshold_db": -40,
            "clipping_threshold_percent": 0.1,
            "duration_match_threshold_percent": 30,
            "volume_normalization_target_db": -20,
            "low_volume_threshold_db": -30,
            "high_volume_threshold_db": -1
        }
    }


def load_contract_versions(config_path: str = "./config/contract_versions.yaml") -> Dict[str, Any]:
    """Load contract versions from YAML file.

    Args:
        config_path: Path to the contract versions YAML file

    Returns:
        Dictionary containing the loaded contract versions, or default dict if file not found/error
    """
    try:
        path = Path(config_path)
        if not path.exists():
            logger.warning(f"Contract versions file not found: {config_path}")
            return _get_default_contract_versions()

        with open(path, 'r', encoding='utf-8') as f:
            versions = yaml.safe_load(f)

        logger.info(f"Loaded contract versions from {config_path}")
        return versions if isinstance(versions, dict) else _get_default_contract_versions()

    except yaml.YAMLError as e:
        logger.error(f"Failed to parse YAML in {config_path}: {e}")
        return _get_default_contract_versions()
    except Exception as e:
        logger.error(f"Unexpected error loading contract versions from {config_path}: {e}")
        return _get_default_contract_versions()


def _get_default_contract_versions() -> Dict[str, Any]:
    """Return default contract versions when config file is not available."""
    return {
        "global": {"current": 1, "min_compatible": 1, "schema": "HARNESS_v1"},
        "stages": {
            "extract": {"current": 1, "min_compatible": 1, "input_schema": "ExtractionInput", "output_schema": "ExtractionResult"},
            "analyze_structure": {"current": 1, "min_compatible": 1, "input_schema": "BookAnalysisInput", "output_schema": "BookAnalysisOutput"},
            "annotate_paragraph": {"current": 1, "min_compatible": 1, "input_schema": "ParagraphAnnotationInput", "output_schema": "ParagraphAnnotation"},
            "edit_for_tts": {"current": 1, "min_compatible": 1, "input_schema": "TtsEditInput", "output_schema": "TtsEditOutput"},
            "tts_routing": {"current": 1, "min_compatible": 1, "input_schema": "TtsRoutingInput", "output_schema": "TtsRoutingDecision"},
            "synthesize": {"current": 1, "min_compatible": 1, "input_schema": "TtsRoutingInput + TtsRoutingDecision", "output_schema": "AudioSegment"},
            "quality_check": {"current": 1, "min_compatible": 1, "input_schema": "AudioAnalysisResult + ParagraphAnnotation + TtsRoutingDecision + reference_text", "output_schema": "QualityJudgment"},
        },
        "compatibility": {"version_format": "major.minor.patch", "breaking_on_major_change": True, "warn_on_minor_change": True},
        "deprecation": {"cycles_before_removal": 3, "warn_on_deprecated_use": True, "migration_guide_url": "docs/migration_guide.md"},
        "validation": {"strict_mode": True, "coerce_types": True, "validate_enum_values": True, "min_compliance_rate": 0.99},
    }


def _get_default_pipeline_config() -> Dict[str, Any]:
    """Return default pipeline configuration when config file is not available."""
    return {
        "quality_thresholds": {
            "silence_threshold_db": -40,
            "clipping_threshold": 0.001,
            "min_duration_ms": 100,
            "max_duration_ms": 30000,
            "volume_normalization_target_db": -20,
            "low_volume_threshold_db": -30,
            "high_volume_threshold_db": -1,
            "duration_match_threshold_percent": 30,
            "sample_rate": 22050,
            "noise_floor_db": -50,
        },
        "constitutional_rules": {
            "character_consistency": {
                "min_consistency_score": 0.9,
                "verify_voice_binding": True,
                "wrong_speaker_consecutive_threshold": 3,
                "max_voice_drift_per_chapter": 0.05,
            },
            "emotion_coherence": {
                "min_emotion_match": 0.80,
                "max_mismatch_ratio": 0.20,
                "require_context_continuity": True,
                "max_intensity_deviation": 0.15,
            },
            "text_norms": {
                "chinese": {
                    "avoid_english_mixing": True,
                    "classical_modern_balance": 0.3,
                    "normalize_punctuation": True,
                    "traditional_to_simplified": True,
                },
                "english": {
                    "avoid_chinese_pinyin": True,
                    "formality_match_context": True,
                    "normalize_contractions": True,
                },
                "general": {
                    "max_consecutive_repeats": 3,
                    "strip_zero_width": True,
                    "normalize_whitespace": True,
                    "max_segment_chars": 500,
                    "min_segment_chars": 10,
                },
            },
        },
        "difficulty_weights": {
            "char_count_weight": 0.30,
            "dialect_ratio_weight": 0.25,
            "term_density_weight": 0.20,
            "emotion_complexity_weight": 0.15,
            "speaker_count_weight": 0.10,
            "base_difficulty": 0.1,
            "difficulty_tiers": {
                "easy": 0.3,
                "medium": 0.5,
                "hard": 0.7,
                "expert": 1.0,
            },
        },
        "voice_mapping": {
            "male_child": {
                "voice_id": "male_child_001",
                "description": "男童声",
                "language": "zh-CN",
                "age_range": [0, 12],
                "gender": "male",
            },
            "male_teenager": {
                "voice_id": "male_teen_001",
                "description": "男青少年声",
                "language": "zh-CN",
                "age_range": [13, 17],
                "gender": "male",
            },
            "male_young": {
                "voice_id": "male_young_001",
                "description": "男青年声",
                "language": "zh-CN",
                "age_range": [18, 35],
                "gender": "male",
            },
            "male_middle": {
                "voice_id": "male_middle_001",
                "description": "男中年声",
                "language": "zh-CN",
                "age_range": [36, 55],
                "gender": "male",
            },
            "male_elder": {
                "voice_id": "male_elder_001",
                "description": "男老年声",
                "language": "zh-CN",
                "age_range": [56, 120],
                "gender": "male",
            },
            "female_child": {
                "voice_id": "female_child_001",
                "description": "女童声",
                "language": "zh-CN",
                "age_range": [0, 12],
                "gender": "female",
            },
            "female_teenager": {
                "voice_id": "female_teen_001",
                "description": "女青少年声",
                "language": "zh-CN",
                "age_range": [13, 17],
                "gender": "female",
            },
            "female_young": {
                "voice_id": "female_young_001",
                "description": "女青年声",
                "language": "zh-CN",
                "age_range": [18, 35],
                "gender": "female",
            },
            "female_middle": {
                "voice_id": "female_middle_001",
                "description": "女中年声",
                "language": "zh-CN",
                "age_range": [36, 55],
                "gender": "female",
            },
            "female_elder": {
                "voice_id": "female_elder_001",
                "description": "女老年声",
                "language": "zh-CN",
                "age_range": [56, 120],
                "gender": "female",
            },
            "neutral_narrator": {
                "voice_id": "neutral_narrator_001",
                "description": "中性旁白声",
                "language": "zh-CN",
                "age_range": [25, 50],
                "gender": "neutral",
            },
            "special_elderly_wiseman": {
                "voice_id": "special_wiseman_001",
                "description": "智慧老人声",
                "language": "zh-CN",
                "age_range": [60, 100],
                "gender": "male",
            },
            "special_robot": {
                "voice_id": "special_robot_001",
                "description": "机器人声",
                "language": "zh-CN",
                "age_range": [0, 999],
                "gender": "neutral",
            },
            "special_monster": {
                "voice_id": "special_monster_001",
                "description": "怪物声",
                "language": "zh-CN",
                "age_range": [0, 999],
                "gender": "neutral",
            },
            "voice_mapping_en": {
                "male_child": {
                    "voice_id": "male_child_en_001",
                    "description": "Boy voice",
                    "language": "en-US",
                    "age_range": [0, 12],
                    "gender": "male",
                },
                "male_teenager": {
                    "voice_id": "male_teen_en_001",
                    "description": "Teenage boy voice",
                    "language": "en-US",
                    "age_range": [13, 17],
                    "gender": "male",
                },
                "male_young": {
                    "voice_id": "male_young_en_001",
                    "description": "Young man voice",
                    "language": "en-US",
                    "age_range": [18, 35],
                    "gender": "male",
                },
                "male_middle": {
                    "voice_id": "male_middle_en_001",
                    "description": "Middle-aged man voice",
                    "language": "en-US",
                    "age_range": [36, 55],
                    "gender": "male",
                },
                "male_elder": {
                    "voice_id": "male_elder_en_001",
                    "description": "Elderly man voice",
                    "language": "en-US",
                    "age_range": [56, 120],
                    "gender": "male",
                },
                "female_child": {
                    "voice_id": "female_child_en_001",
                    "description": "Girl voice",
                    "language": "en-US",
                    "age_range": [0, 12],
                    "gender": "female",
                },
                "female_teenager": {
                    "voice_id": "female_teen_en_001",
                    "description": "Teenage girl voice",
                    "language": "en-US",
                    "age_range": [13, 17],
                    "gender": "female",
                },
                "female_young": {
                    "voice_id": "female_young_en_001",
                    "description": "Young woman voice",
                    "language": "en-US",
                    "age_range": [18, 35],
                    "gender": "female",
                },
                "female_middle": {
                    "voice_id": "female_middle_en_001",
                    "description": "Middle-aged woman voice",
                    "language": "en-US",
                    "age_range": [36, 55],
                    "gender": "female",
                },
                "female_elder": {
                    "voice_id": "female_elder_en_001",
                    "description": "Elderly woman voice",
                    "language": "en-US",
                    "age_range": [56, 120],
                    "gender": "female",
                },
                "neutral_narrator": {
                    "voice_id": "neutral_narrator_en_001",
                    "description": "Neutral narrator voice",
                    "language": "en-US",
                    "age_range": [25, 50],
                    "gender": "neutral",
                },
                "special_elderly_wiseman": {
                    "voice_id": "special_wiseman_en_001",
                    "description": "Wise old man voice",
                    "language": "en-US",
                    "age_range": [60, 100],
                    "gender": "male",
                },
                "special_robot": {
                    "voice_id": "special_robot_en_001",
                    "description": "Robot voice",
                    "language": "en-US",
                    "age_range": [0, 999],
                    "gender": "neutral",
                },
                "special_monster": {
                    "voice_id": "special_monster_en_001",
                    "description": "Monster voice",
                    "language": "en-US",
                    "age_range": [0, 999],
                    "gender": "neutral",
                },
            },
        },
        "promotion_thresholds": {
            "quality_score_delta": 0.02,
            "golden_regression_baseline": {
                "max_quality_regression": 0.01,
                "max_speaker_clarity_regression": 0.02,
                "max_emotion_match_regression": 0.02,
                "max_prosody_regression": 0.02,
                "max_alignment_regression": 0.02,
                "max_error_rate_increase": 0.005,
                "min_evaluation_samples": 50,
            },
            "cost_efficiency": {
                "max_cost_increase_ratio": 1.1,
                "min_cost_savings_ratio": 0.85,
            },
            "latency": {
                "max_latency_increase_ratio": 1.2,
                "fast_tier_target_ms": 2000,
                "quality_tier_target_ms": 5000,
            },
            "stability": {
                "min_success_rate": 0.99,
                "max_consecutive_failures": 2,
                "evaluation_period_hours": 24,
            },
            "ab_testing": {
                "min_canary_traffic_pct": 5,
                "max_canary_traffic_pct": 50,
                "min_experiment_duration_hours": 4,
                "significance_threshold": 0.05,
                "min_effect_size": 0.01,
            },
        },
    }


def load_pipeline_config(config_path: str = DEFAULT_PIPELINE_CONFIG_PATH) -> Dict[str, Any]:
    """Load pipeline configuration from YAML file with hot-reload support.

    This function reads the pipeline.yaml file and caches it. On subsequent calls,
    it checks if the file has been modified and reloads it if necessary, enabling
    hot-reload without application restart.

    Args:
        config_path: Path to the pipeline.yaml configuration file

    Returns:
        Dictionary containing the full pipeline configuration

    Note:
        The configuration is cached globally. Changes to the file will be picked
        up on the next call to this function or any of the getter functions.
    """
    global _pipeline_config_cache, _pipeline_config_mtime

    with _pipeline_config_lock:
        try:
            path = Path(config_path)
            if not path.exists():
                logger.warning(f"Pipeline config file not found: {config_path}")
                return _get_default_pipeline_config()

            current_mtime = path.stat().st_mtime

            # Reload if first load or file has been modified
            if _pipeline_config_cache is None or current_mtime > _pipeline_config_mtime:
                with open(path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)

                if not isinstance(config, dict):
                    logger.error(f"Invalid pipeline config format in {config_path}, using defaults")
                    return _get_default_pipeline_config()

                _pipeline_config_cache = config
                _pipeline_config_mtime = current_mtime
                logger.info(f"Loaded pipeline configuration from {config_path}")

            return _pipeline_config_cache

        except yaml.YAMLError as e:
            logger.error(f"Failed to parse YAML in {config_path}: {e}")
            return _get_default_pipeline_config()
        except Exception as e:
            logger.error(f"Unexpected error loading pipeline config from {config_path}: {e}")
            return _get_default_pipeline_config()


def get_quality_thresholds(config_path: str = DEFAULT_PIPELINE_CONFIG_PATH) -> Dict[str, Any]:
    """Get quality thresholds from pipeline configuration.

    Args:
        config_path: Path to the pipeline.yaml configuration file

    Returns:
        Dictionary containing quality threshold settings
    """
    config = load_pipeline_config(config_path)
    return config.get("quality_thresholds", _get_default_pipeline_config()["quality_thresholds"])


def get_constitutional_rules(config_path: str = DEFAULT_PIPELINE_CONFIG_PATH) -> Dict[str, Any]:
    """Get constitutional rules from pipeline configuration.

    Args:
        config_path: Path to the pipeline.yaml configuration file

    Returns:
        Dictionary containing constitutional rules
    """
    config = load_pipeline_config(config_path)
    return config.get("constitutional_rules", _get_default_pipeline_config()["constitutional_rules"])


def get_difficulty_weights(config_path: str = DEFAULT_PIPELINE_CONFIG_PATH) -> Dict[str, Any]:
    """Get difficulty weights from pipeline configuration.

    Args:
        config_path: Path to the pipeline.yaml configuration file

    Returns:
        Dictionary containing difficulty weight settings
    """
    config = load_pipeline_config(config_path)
    return config.get("difficulty_weights", _get_default_pipeline_config()["difficulty_weights"])


def get_voice_mapping(config_path: str = DEFAULT_PIPELINE_CONFIG_PATH) -> Dict[str, Any]:
    """Get voice mapping from pipeline configuration.

    Args:
        config_path: Path to the pipeline.yaml configuration file

    Returns:
        Dictionary containing voice mapping configuration
    """
    config = load_pipeline_config(config_path)
    return config.get("voice_mapping", _get_default_pipeline_config()["voice_mapping"])


def get_promotion_thresholds(config_path: str = DEFAULT_PIPELINE_CONFIG_PATH) -> Dict[str, Any]:
    """Get promotion thresholds from pipeline configuration.

    Args:
        config_path: Path to the pipeline.yaml configuration file

    Returns:
        Dictionary containing promotion threshold settings
    """
    config = load_pipeline_config(config_path)
    return config.get("promotion_thresholds", _get_default_pipeline_config()["promotion_thresholds"])


def reload_config_if_changed(
    config_path: str,
    last_modified: Optional[float] = None
) -> tuple[Dict[str, Any], Optional[float]]:
    """Check if config file has changed and reload if necessary.

    Args:
        config_path: Path to the config file to check
        last_modified: Last known modification timestamp (None for first check)

    Returns:
        Tuple of (config_dict, current_modified_timestamp)
    """
    try:
        path = Path(config_path)
        if not path.exists():
            return {}, last_modified

        current_modified = path.stat().st_mtime
        if last_modified is None or current_modified > last_modified:
            # File has changed, reload it
            if "quality_thresholds" in config_path:
                config = load_quality_thresholds(config_path)
            elif "contract_versions" in config_path:
                config = load_contract_versions(config_path)
            else:
                config = load_rules(config_path)
            return config, current_modified
        else:
            # No change, return existing config
            if "quality_thresholds" in config_path:
                return load_quality_thresholds(config_path), last_modified
            elif "contract_versions" in config_path:
                return load_contract_versions(config_path), last_modified
            else:
                return load_rules(config_path), last_modified

    except Exception as e:
        logger.error(f"Error checking/reloading config {config_path}: {e}")
        if "quality_thresholds" in config_path:
            return _get_default_quality_thresholds(), last_modified
        else:
            return {}, last_modified