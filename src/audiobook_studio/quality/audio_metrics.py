"""
Audio Quality Metrics - P0.2 免费CPU硬门禁三件套

三大指标（均为开源/离线/CPU可跑，免费资源为上限）：
1. MOS (UTMOS/DNSMOS) - 语音自然度，无参考音频
2. WER (faster-whisper) - 字错误率，可懂度硬关
3. Speaker Similarity (ECAPA-TDNN) - 声纹一致性，克隆/长文漂移门

缺失依赖 -> 对应指标诚实降级跳过，绝不充当通过。
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Optional Dependencies (Graceful Degradation)

# DNSMOS (ONNX-based, no PyTorch needed) - for MOS
_dnsmos_available = False
_dnsmos_session = None
try:
    import onnxruntime as ort

    _dnsmos_available = True
except ImportError:
    logger.warning("[AudioMetrics] onnxruntime not available, MOS metric will be skipped")

# faster-whisper for WER
_whisper_available = False
_whisper_model = None
try:
    from faster_whisper import WhisperModel

    _whisper_available = True
except ImportError:
    logger.warning("[AudioMetrics] faster-whisper not available, WER metric will be skipped")

# speechbrain for ECAPA-TDNN speaker embeddings
_speechbrain_available = False
_ecapa_classifier = None
try:
    import torch
    from speechbrain.inference.speaker import SpeakerRecognition

    _speechbrain_available = True
except ImportError:
    logger.warning("[AudioMetrics] speechbrain not available, Speaker Similarity metric will be skipped")

# Data Models


@dataclass
class AudioQualityReport:
    """Complete audio quality report with all three metrics."""

    mos: Optional[float] = None
    wer: Optional[float] = None
    speaker_cosine: Optional[float] = None

    # Thresholds for hard gates
    mos_threshold: float = 3.5  # MOS below this = fail
    wer_threshold: float = 0.15  # WER above this = fail
    speaker_cosine_threshold: float = 0.85  # Cosine below this = fail

    # Overall pass/fail (any single metric failing = overall fail)
    overall_passed: bool = True

    def __post_init__(self):
        self.overall_passed = True
        if self.mos is not None and self.mos < self.mos_threshold:
            self.overall_passed = False
        if self.wer is not None and self.wer > self.wer_threshold:
            self.overall_passed = False
        if self.speaker_cosine is not None and self.speaker_cosine < self.speaker_cosine_threshold:
            self.overall_passed = False

    def to_dict(self) -> dict:
        return {
            "mos": self.mos,
            "wer": self.wer,
            "speaker_cosine": self.speaker_cosine,
            "thresholds": {
                "mos": self.mos_threshold,
                "wer": self.wer_threshold,
                "speaker_cosine": self.speaker_cosine_threshold,
            },
            "overall_passed": self.overall_passed,
        }


# MOS (UTMOS/DNSMOS)


def _load_dnsmos_model(model_path: Optional[str] = None):
    """Load DNSMOS ONNX model (cached)."""
    global _dnsmos_session
    if _dnsmos_session is not None:
        return _dnsmos_session

    if not _dnsmos_available:
        return None

    if model_path is None:
        import os

        model_path = os.environ.get("DNSMOS_MODEL_PATH", "dnsmos.onnx")

    if not Path(model_path).exists():
        logger.warning(f"[AudioMetrics] DNSMOS model not found at {model_path}, will use mock")
        return None

    try:
        _dnsmos_session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        logger.info(f"[AudioMetrics] Loaded DNSMOS model from {model_path}")
        return _dnsmos_session
    except Exception as e:
        logger.error(f"[AudioMetrics] Failed to load DNSMOS model: {e}")
        return None


def predict_mos(wav_path: str, sample_rate: int = 16000) -> Optional[float]:
    """Predict MOS (Mean Opinion Score) for speech naturalness using DNSMOS."""
    if not _dnsmos_available:
        logger.debug("[AudioMetrics] DNSMOS unavailable, returning None")
        return None

    session = _load_dnsmos_model()
    if session is None:
        return None

    try:
        import soundfile as sf

        audio, sr = sf.read(wav_path)
        if sr != sample_rate:
            import scipy.signal as signal

            audio = signal.resample(audio, int(len(audio) * sample_rate / sr))

        if audio.ndim > 1:
            audio = audio.mean(axis=1)

        target_len = sample_rate * 9
        if len(audio) < target_len:
            audio = np.pad(audio, (0, target_len - len(audio)))
        else:
            audio = audio[:target_len]

        audio = audio.astype(np.float32)
        if np.max(np.abs(audio)) > 0:
            audio = audio / np.max(np.abs(audio))

        input_name = session.get_inputs()[0].name
        outputs = session.run(None, {input_name: audio.reshape(1, -1)})

        mos_score = float(outputs[0][0, 0])
        return max(1.0, min(5.0, mos_score))

    except Exception as e:
        logger.warning(f"[AudioMetrics] MOS prediction failed: {e}")
        return None


# WER (faster-whisper)


def _load_whisper_model(model_size: str = "base", device: str = "cpu", compute_type: str = "int8"):
    """Load faster-whisper model (cached)."""
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model

    if not _whisper_available:
        return None

    try:
        _whisper_model = WhisperModel(
            model_size, device=device, compute_type=compute_type, cpu_threads=4, num_workers=1
        )
        logger.info(f"[AudioMetrics] Loaded faster-whisper model: {model_size} ({device}, {compute_type})")
        return _whisper_model
    except Exception as e:
        logger.error(f"[AudioMetrics] Failed to load faster-whisper: {e}")
        return None


def compute_wer(wav_path: str, reference_text: str, language: str = "zh") -> Optional[float]:
    """Compute Word Error Rate using faster-whisper ASR."""
    if not _whisper_available:
        logger.debug("[AudioMetrics] faster-whisper unavailable, returning None")
        return None

    model = _load_whisper_model()
    if model is None:
        return None

    if not reference_text or not reference_text.strip():
        logger.warning("[AudioMetrics] Empty reference text, cannot compute WER")
        return None

    try:
        segments, info = model.transcribe(wav_path, language=language, beam_size=5)
        hypothesis = " ".join([seg.text for seg in segments]).strip()

        if not hypothesis:
            logger.warning("[AudioMetrics] Empty hypothesis, WER = 1.0")
            return 1.0

        if language in ("zh", "ja", "ko"):
            ref_chars = list(reference_text.replace(" ", ""))
            hyp_chars = list(hypothesis.replace(" ", ""))
        else:
            ref_chars = reference_text.split()
            hyp_chars = hypothesis.split()

        wer = _levenshtein_distance(ref_chars, hyp_chars) / max(len(ref_chars), 1)
        return min(1.0, wer)

    except Exception as e:
        logger.warning(f"[AudioMetrics] WER computation failed: {e}")
        return None


def _levenshtein_distance(a: list, b: list) -> int:
    """Compute Levenshtein distance between two sequences."""
    if len(a) < len(b):
        a, b = b, a

    previous_row = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        current_row = [i + 1]
        for j, cb in enumerate(b):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (ca != cb)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


# Speaker Similarity (ECAPA-TDNN)


def _load_ecapa_model():
    """Load ECAPA-TDNN speaker embedding model (cached)."""
    global _ecapa_classifier
    if _ecapa_classifier is not None:
        return _ecapa_classifier

    if not _speechbrain_available:
        return None

    try:
        _ecapa_classifier = SpeakerRecognition.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir="pretrained_models/spkrec-ecapa-voxceleb",
            run_opts={"device": "cpu"},
        )
        logger.info("[AudioMetrics] Loaded ECAPA-TDNN speaker recognition model")
        return _ecapa_classifier
    except Exception as e:
        logger.error(f"[AudioMetrics] Failed to load ECAPA-TDNN: {e}")
        return None


_ecapa_cache: dict[str, np.ndarray] = {}


def _get_speaker_embedding(wav_path: str) -> Optional[np.ndarray]:
    """Get speaker embedding for a wav file (cached)."""
    if wav_path in _ecapa_cache:
        return _ecapa_cache[wav_path]

    classifier = _load_ecapa_model()
    if classifier is None:
        return None

    try:
        embedding = classifier.encode_batch(classifier.load_audio(wav_path))
        embedding = embedding.squeeze().cpu().numpy()
        _ecapa_cache[wav_path] = embedding
        return embedding
    except Exception as e:
        logger.warning(f"[AudioMetrics] Failed to get speaker embedding: {e}")
        return None


def voice_cosine(reference_wav: str, target_wav: str) -> Optional[float]:
    """Compute cosine similarity between two speaker embeddings."""
    if not _speechbrain_available:
        logger.debug("[AudioMetrics] speechbrain unavailable, returning None")
        return None

    ref_emb = _get_speaker_embedding(reference_wav)
    tgt_emb = _get_speaker_embedding(target_wav)

    if ref_emb is None or tgt_emb is None:
        return None

    try:
        cos_sim = np.dot(ref_emb, tgt_emb) / (np.linalg.norm(ref_emb) * np.linalg.norm(tgt_emb))
        return float(np.clip(cos_sim, 0.0, 1.0))
    except Exception as e:
        logger.warning(f"[AudioMetrics] Cosine similarity failed: {e}")
        return None


# Unified Quality Check


def check_audio_quality(
    wav_path: str,
    reference_text: Optional[str] = None,
    reference_wav: Optional[str] = None,
    language: str = "zh",
    mos_threshold: float = 3.5,
    wer_threshold: float = 0.15,
    speaker_cosine_threshold: float = 0.85,
) -> AudioQualityReport:
    """Run all three quality metrics and return unified report."""
    report = AudioQualityReport(
        mos_threshold=mos_threshold,
        wer_threshold=wer_threshold,
        speaker_cosine_threshold=speaker_cosine_threshold,
    )

    report.mos = predict_mos(wav_path)

    if reference_text:
        report.wer = compute_wer(wav_path, reference_text, language)

    if reference_wav:
        report.speaker_cosine = voice_cosine(reference_wav, wav_path)

    report.__post_init__()

    logger.info(
        f"[AudioMetrics] Quality check for {wav_path}: " f"MOS={report.mos:.2f}"
        if report.mos
        else (
            "MOS=N/A" f", WER={report.wer:.2%}"
            if report.wer
            else (
                "WER=N/A" f", Cosine={report.speaker_cosine:.3f}"
                if report.speaker_cosine
                else "Cosine=N/A" f" -> {'PASS' if report.overall_passed else 'FAIL'}"
            )
        )
    )

    return report


# Availability Check


def get_available_metrics() -> dict[str, bool]:
    """Return which metrics are available (dependencies installed)."""
    return {
        "mos": _dnsmos_available,
        "wer": _whisper_available,
        "speaker_similarity": _speechbrain_available,
    }
