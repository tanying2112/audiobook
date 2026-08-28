"""Real audio-quality scoring layer — P0-C1.

Ties the golden dataset and the self-iteration loop to *real* acoustic
evaluation signals (DNSMOS / UTMOS / ASR WER / Speaker Similarity) instead of a
pure heuristic compliance proxy.

The deterministic heuristic (``AnnotationQualityMetric`` in
``feedback.sop_verification``) stays as a CI-stable *annotation* proxy. This
module adds the complementary layer that actually opens audio files and scores
them with real models via :class:`~audiobook_studio.quality.metrics.QualityCheckSuite`.

Design:
* :class:`AudioQualityScorer` — a thin, dependency-safe wrapper around
  ``QualityCheckSuite`` that produces a fused ``AudioQualityScore`` (0-1).
* :func:`fuse_audio_scores` — combine per-metric MOS/WER/similarity into a single
  0-1 ``overall`` with honest "insufficient data" handling (no fabricated values
  when a metric is unavailable).
* :class:`AudioQualitySample` — one scored audio file.

``mock_mode`` returns deterministic values (no model download), so CI stays
hermetic and reproducible. Real mode lazily loads models (DNSMOS/UTMOS via ONNX
Runtime, ASR via faster-whisper, speaker sim via SpeechBrain) and degrades
gracefully when a dependency is absent — the same honesty rule as
``QualityCheckSuite`` (a missing metric is reported unavailable, never fake).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Metric weightings for the fused overall score (must sum to 1.0).
# DNSMOS/UTMOS carry speech quality, WER carries intelligibility, speaker-sim
# carries voice consistency.
DEFAULT_WEIGHTS: Dict[str, float] = {
    "utmos": 0.35,
    "dnsmos": 0.25,
    "wer": 0.20,
    "speaker_sim": 0.20,
}


@dataclass
class AudioQualitySample:
    """A single scored audio file."""

    audio_path: str
    utmos: Optional[float] = None
    dnsmos: Optional[float] = None
    wer: Optional[float] = None
    speaker_sim: Optional[float] = None
    overall: float = 0.0
    available_metrics: int = 0
    total_metrics: int = 4
    success: bool = False
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audio_path": self.audio_path,
            "utmos": round(self.utmos, 4) if self.utmos is not None else None,
            "dnsmos": round(self.dnsmos, 4) if self.dnsmos is not None else None,
            "wer": round(self.wer, 4) if self.wer is not None else None,
            "speaker_sim": round(self.speaker_sim, 4) if self.speaker_sim is not None else None,
            "overall": round(self.overall, 4),
            "available_metrics": self.available_metrics,
            "total_metrics": self.total_metrics,
            "success": self.success,
            "error": self.error,
        }

    @property
    def has_sufficient_data(self) -> bool:
        """True when at least one real acoustic metric was actually computed."""
        return self.success and self.available_metrics > 0


@dataclass
class AudioQualityReport:
    """Aggregate report for a batch of audio files."""

    samples: List[AudioQualitySample] = field(default_factory=list)
    mean_overall: float = 0.0
    mean_utmos: Optional[float] = None
    mean_dnsmos: Optional[float] = None
    mean_wer: Optional[float] = None
    mean_speaker_sim: Optional[float] = None
    scored_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mean_overall": round(self.mean_overall, 4),
            "mean_utmos": round(self.mean_utmos, 4) if self.mean_utmos is not None else None,
            "mean_dnsmos": round(self.mean_dnsmos, 4) if self.mean_dnsmos is not None else None,
            "mean_wer": round(self.mean_wer, 4) if self.mean_wer is not None else None,
            "mean_speaker_sim": round(self.mean_speaker_sim, 4) if self.mean_speaker_sim is not None else None,
            "scored_count": self.scored_count,
            "total_count": len(self.samples),
            "samples": [s.to_dict() for s in self.samples],
        }


def _mos_to_unit(mos: float) -> float:
    """Map a MOS in [1,5] to [0,1] (linear; 1 -> 0, 5 -> 1)."""
    if mos is None:
        return 0.0
    return max(0.0, min(1.0, (mos - 1.0) / 4.0))


def _wer_to_unit(wer: float) -> float:
    """Map WER (0-1, lower better) to [0,1] (higher better)."""
    if wer is None:
        return 0.0
    return max(0.0, min(1.0, 1.0 - wer * 10.0))


def fuse_audio_scores(
    utmos: Optional[float],
    dnsmos: Optional[float],
    wer: Optional[float],
    speaker_sim: Optional[float],
    weights: Optional[Dict[str, float]] = None,
) -> float:
    """Fuse per-metric values into a single 0-1 overall score.

    Only available metrics contribute; weights are renormalized over the
    available subset so a partially-measured sample still yields a meaningful
    0-1 score. Returns 0.0 when no metric is available (insufficient data —
    never a fabricated value).
    """
    w = weights or DEFAULT_WEIGHTS
    components: List[float] = []
    avail: Dict[str, float] = {}
    if utmos is not None:
        avail["utmos"] = _mos_to_unit(utmos)
    if dnsmos is not None:
        avail["dnsmos"] = _mos_to_unit(dnsmos)
    if wer is not None:
        avail["wer"] = _wer_to_unit(wer)
    if speaker_sim is not None:
        avail["speaker_sim"] = max(0.0, min(1.0, speaker_sim))

    if not avail:
        return 0.0

    total_w = sum(w.get(k, 0.0) for k in avail)
    if total_w <= 0:
        # No configured weight for any available metric; fall back to unweighted mean.
        return sum(avail.values()) / len(avail)

    weighted = sum(w.get(k, 0.0) * v for k, v in avail.items()) / total_w
    return max(0.0, min(1.0, weighted))


class AudioQualityScorer:
    """Score audio files with real acoustic metrics.

    Wraps :class:`~audiobook_studio.quality.metrics.QualityCheckSuite`, so it
    inherits the same honest-degradation rule: a metric whose dependency is
    missing is reported unavailable, never fabricated.

    Parameters
    ----------
    suite : optional pre-built QualityCheckSuite. If None, one is built from
        ``thresholds`` and ``hardware_profile``.
    thresholds : threshold dict (see QualityCheckSuite).
    hardware_profile : hardware tier string (potato/cloud_hybrid/pro_studio).
    weights : per-metric fusion weights (defaults to DEFAULT_WEIGHTS).
    mock_mode : when True, return deterministic values without loading models
        (CI-hermetic). Real-mode models load lazily on first score.
    """

    def __init__(
        self,
        suite: Any = None,
        thresholds: Optional[Dict[str, Any]] = None,
        hardware_profile: Optional[str] = None,
        weights: Optional[Dict[str, float]] = None,
        mock_mode: bool = False,
    ) -> None:
        self.mock_mode = mock_mode
        self.weights = weights or DEFAULT_WEIGHTS
        self._suite = suite
        self._hw_profile = hardware_profile
        self._thresholds = thresholds or {}
        # Hard metric feature flags (mirrors QualityCheckPipeline): used to skip
        # a metric honestly when its dependency is absent.
        self._available = self._check_dependencies()

        if suite is None and not mock_mode:
            from .metrics import QualityCheckSuite

            qc = self._thresholds.get("quality_check", {})
            qc["mock_mode"] = False
            self._suite = QualityCheckSuite(
                config=self._thresholds,
                hardware_profile=hardware_profile or "cloud_hybrid",
            )

    @staticmethod
    def _check_dependencies() -> Dict[str, bool]:
        """Check optional dependency availability (honest metric gating)."""
        features: Dict[str, bool] = {"dnsmos": False, "utmos": False, "asr": False, "speaker_sim": False}
        try:
            import onnxruntime  # noqa: F401

            features["dnsmos"] = True
            features["utmos"] = True
        except ImportError:
            pass
        try:
            import faster_whisper  # noqa: F401

            features["asr"] = True
        except ImportError:
            try:
                import whisper  # noqa: F401

                features["asr"] = True
            except ImportError:
                pass
        try:
            import torch  # noqa: F401
            from speechbrain.inference.speaker import EncoderClassifier  # noqa: F401

            features["speaker_sim"] = True
        except (ImportError, Exception):
            pass
        return features

    def score(
        self,
        audio_path: Path,
        reference_text: str = "",
        reference_speaker_audio: Optional[Path] = None,
    ) -> AudioQualitySample:
        """Score a single audio file.

        Parameters
        ----------
        audio_path : path to the synthesized audio to evaluate.
        reference_text : expected text for WER (empty skips WER honestly).
        reference_speaker_audio : voice anchor for speaker similarity (optional).

        Returns
        -------
        AudioQualitySample with real metric values; ``overall`` fused 0-1.
        """
        path = Path(audio_path)
        if not path.exists():
            return AudioQualitySample(
                audio_path=str(path),
                success=False,
                error=f"audio file not found: {path}",
            )

        if self.mock_mode:
            return self._mock_sample(path)

        try:
            # Delegate to the real QualityCheckSuite when built.
            if self._suite is not None:
                result = self._suite.check_all(
                    audio_path=path,
                    reference_text=reference_text,
                    reference_speaker_audio=reference_speaker_audio,
                )
            else:
                # Build a one-shot suite honoring dependency gating.
                from .metrics import QualityCheckSuite

                qc: Dict[str, Any] = {
                    "dnsmos_enabled": self._available["dnsmos"],
                    "utmos_enabled": self._available["utmos"],
                    "asr_enabled": self._available["asr"] and bool(reference_text),
                    "speaker_similarity_enabled": self._available["speaker_sim"],
                }
                suite = QualityCheckSuite(
                    config={"quality_check": qc, "thresholds": self._thresholds},
                    hardware_profile=self._hw_profile or "cloud_hybrid",
                )
                result = suite.check_all(
                    audio_path=path,
                    reference_text=reference_text,
                    reference_speaker_audio=reference_speaker_audio,
                )

            utmos = result.utmos.mos if result.utmos and result.utmos.success else None
            dnsmos = result.dnsmos.mos_ovr if result.dnsmos and result.dnsmos.success else None
            wer = result.wer.wer if result.wer and result.wer.success else None
            sim = result.speaker_sim.similarity if result.speaker_sim and result.speaker_sim.success else None

            available = sum(1 for v in (utmos, dnsmos, wer, sim) if v is not None)
            overall = fuse_audio_scores(utmos, dnsmos, wer, sim, self.weights)

            return AudioQualitySample(
                audio_path=str(path),
                utmos=utmos,
                dnsmos=dnsmos,
                wer=wer,
                speaker_sim=sim,
                overall=overall,
                available_metrics=available,
                success=available > 0,
                error=None if available > 0 else "no real audio metric available (dependencies missing?)",
            )
        except Exception as e:  # noqa: BLE001 - surface scoring failure honestly
            logger.error(f"Audio quality scoring failed for {path}: {e}")
            return AudioQualitySample(
                audio_path=str(path),
                success=False,
                error=str(e),
            )

    def _mock_sample(self, path: Path) -> AudioQualitySample:
        """Deterministic mock sample (no models, CI-hermetic).

        Values are fixed, not derived from the file, so tests are reproducible.
        """
        return AudioQualitySample(
            audio_path=str(path),
            utmos=4.0,
            dnsmos=4.2,
            wer=0.02,
            speaker_sim=0.90,
            overall=fuse_audio_scores(4.0, 4.2, 0.02, 0.90, self.weights),
            available_metrics=4,
            success=True,
        )

    def score_batch(
        self,
        samples: List[Dict[str, Any]],
        reference_speaker_audio: Optional[Path] = None,
    ) -> AudioQualityReport:
        """Score a batch of audio files.

        Parameters
        ----------
        samples : list of dicts with keys ``audio_path`` (required),
            ``reference_text`` (optional), ``reference_speaker_audio`` (optional,
            overrides the batch-level anchor for this sample).
        reference_speaker_audio : batch-level voice anchor.

        Returns
        -------
        AudioQualityReport with per-sample details and aggregate means.
        """
        scored: List[AudioQualitySample] = []
        for s in samples:
            ap = s.get("audio_path")
            if not ap:
                continue
            ref = s.get("reference_speaker_audio") or reference_speaker_audio
            scored.append(
                self.score(
                    Path(ap),
                    reference_text=s.get("reference_text", ""),
                    reference_speaker_audio=ref,
                )
            )

        report = AudioQualityReport(samples=scored, scored_count=sum(1 for x in scored if x.has_sufficient_data))
        if scored and report.scored_count:
            ok = [x for x in scored if x.has_sufficient_data]
            report.mean_overall = sum(x.overall for x in ok) / len(ok)
            for attr, key in (
                ("mean_utmos", "utmos"),
                ("mean_dnsmos", "dnsmos"),
                ("mean_wer", "wer"),
                ("mean_speaker_sim", "speaker_sim"),
            ):
                vals = [getattr(x, key) for x in ok if getattr(x, key) is not None]
                if vals:
                    setattr(report, attr, sum(vals) / len(vals))
        return report


def load_quality_thresholds_default() -> Dict[str, Any]:
    """Default thresholds for the scorer (mirrors quality_thresholds.yaml)."""
    return {
        "quality_check": {
            "dnsmos_enabled": True,
            "utmos_enabled": True,
            "asr_enabled": True,
            "speaker_similarity_enabled": True,
        },
        "thresholds": {
            "dnsmos_min": 3.5,
            "utmos_min": 3.5,
            "asr_wer_max": 0.05,
            "speaker_sim_min": 0.85,
        },
    }


__all__ = [
    "AudioQualitySample",
    "AudioQualityReport",
    "AudioQualityScorer",
    "fuse_audio_scores",
    "DEFAULT_WEIGHTS",
]