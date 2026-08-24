# Audiobook Studio - Quality Module
"""Quality metrics and coherence checking."""

# Import check_semantic_coherence from feedback module (it's defined there for now)
from ..feedback.quality_enhancement import (
    check_semantic_coherence,
    get_false_positive_tracker,
    get_free_tier_health,
    grade_difficulty,
    validate_emotions,
)
from .metrics import (
    ASRResult,
    ASRWerMetric,
    DNSMOSMetric,
    DNSMOSResult,
    ECAPATDNNBackend,
    FunASRBackend,
    QualityCheckResult,
    QualityCheckSuite,
    SpeakerEmbedding,
    SpeakerSimilarityMetric,
    SpeakerSimilarityResult,
    WavLMBackend,
    WERResult,
    WhisperBackend,
)
from .semantic_coherence import SemanticCoherenceChecker
from .audio_metrics import (
    AudioQualityReport,
    check_audio_quality,
    compute_wer,
    get_available_metrics,
    predict_mos,
    voice_cosine,
)

__all__ = [
    "SemanticCoherenceChecker",
    "DNSMOSMetric",
    "ASRWerMetric",
    "SpeakerSimilarityMetric",
    "QualityCheckSuite",
    "QualityCheckResult",
    "DNSMOSResult",
    "ASRResult",
    "WERResult",
    "SpeakerEmbedding",
    "SpeakerSimilarityResult",
    "FunASRBackend",
    "WhisperBackend",
    "ECAPATDNNBackend",
    "WavLMBackend",
    # From feedback.quality_enhancement
    "check_semantic_coherence",
    "validate_emotions",
    "grade_difficulty",
    "get_free_tier_health",
    "get_false_positive_tracker",
    # P0.2 Audio Quality Metrics
    "AudioQualityReport",
    "check_audio_quality",
    "compute_wer",
    "get_available_metrics",
    "predict_mos",
    "voice_cosine",
]
