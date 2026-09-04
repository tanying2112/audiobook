"""Pipeline Stage 6: Quality Check - Multi-dimensional audio quality assessment.

Combines rule-based checks (silence, clipping, duration) with LLM-as-a-Judge
for speaker/emotion/prosody evaluation and hard quality metrics (DNSMOS/ASR/Speaker Sim).
Triggers regeneration on failure.
"""

import base64
import logging
import os
import queue
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TypeAlias, cast

import numpy as np

from ..config.hardware_profile import HardwareProfile, get_hardware_profile
from ..config.loader import load_quality_thresholds
from ..llm import LLMJudge, LLMRouter, create_judge, create_router
from ..monitoring.langfuse_client import observe_quality_check, trace_function
from ..pipeline.progress_emitter import emit_stage_enter, emit_stage_exit, emit_stage_progress
from ..quality import QualityCheckResult, QualityCheckSuite
from ..quality.audio_quality import fuse_audio_scores
from ..schemas import ParagraphAnnotation, QualityJudgment, TtsRoutingDecision
from ..schemas.quality import FixSuggestion
from ..utils.ffmpeg_probe import detect_silence_sync, get_duration_sync, get_rms_peak_sync, read_pcm_samples_sync

logger = logging.getLogger(__name__)

# ── A2 全局质检判定收集器 ────────────────────────────────────────────────────
# run() 在 golden_feedback 开启时把质检判定（pass/fail + 原因）推入此收集器，
# 由 pipeline/sop_reflection.SOPBackgroundThread 周期性抽干并回流为 judge 金标，
# 实现「运行时自动回流」而非仅单次 run() 同步回流。


@dataclass
class _QualityJudgmentRecord:
    judgment: Any
    annotation: Any = None
    reference_text: str = ""
    audio_description: Optional[str] = None


class QualityJudgmentCollector:
    """线程安全的质检判定收集器，供 SOPBackgroundThread 周期性抽干回流。"""

    def __init__(self, max_size: int = 10000) -> None:
        self._queue: "queue.Queue[_QualityJudgmentRecord]" = queue.Queue(maxsize=max_size)

    def add(
        self,
        judgment: Any,
        annotation: Any = None,
        reference_text: str = "",
        audio_description: Optional[str] = None,
    ) -> bool:
        try:
            self._queue.put_nowait(_QualityJudgmentRecord(judgment, annotation, reference_text, audio_description))
            return True
        except queue.Full:
            return False

    def drain(self, max_size: int = 500) -> List[_QualityJudgmentRecord]:
        records: List[_QualityJudgmentRecord] = []
        while len(records) < max_size:
            try:
                records.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return records

    def size(self) -> int:
        return self._queue.qsize()


_QUALITY_JUDGMENT_COLLECTOR: Optional[QualityJudgmentCollector] = None


def get_quality_judgment_collector() -> QualityJudgmentCollector:
    """返回全局质检判定收集器（懒初始化，单例）。"""
    global _QUALITY_JUDGMENT_COLLECTOR
    if _QUALITY_JUDGMENT_COLLECTOR is None:
        _QUALITY_JUDGMENT_COLLECTOR = QualityJudgmentCollector()
    return _QUALITY_JUDGMENT_COLLECTOR


# One segment passed to the quality-check run loop:
# (audio_path, paragraph_annotation, routing_decision, reference_text).
# audio_path is path-like (str/Path牧场 — callers pass str); cast below narrows it.
QualityRunInput: TypeAlias = Tuple[Any, ParagraphAnnotation, TtsRoutingDecision, str]


@dataclass
class AudioAnalysisResult:
    """Result of rule-based audio analysis."""

    duration_ms: int
    has_silence: bool
    silence_regions: List[Tuple[float, float]]  # (start_ms, end_ms) — floats from ffprobe
    has_clipping: bool
    rms_db: float
    peak_db: float
    duration_match: bool  # vs estimated
    issues: List[str]


class QualityCheckPipeline:
    """Pipeline for audio quality checking.

    Uses ffmpeg exclusively (via ffmpeg_probe) for audio analysis — no pydub dependency.
    Optional hard metrics (DNSMOS, ASR WER, Speaker Similarity) are conditionally
    enabled based on available Python packages. Missing packages are gracefully
    skipped rather than triggering mock mode.

    Architecture:
        1. Rule-based analysis (always runs, requires only ffmpeg)
        2. Hard quality checks (DNSMOS/ASR/SpeakerSim, requires optional deps)
        3. LLM-as-a-Judge (always runs, requires LLM API)
    """

    def __init__(
        self,
        router: Optional[LLMRouter] = None,
        judge: Optional[LLMJudge] = None,
        mock_mode: Optional[bool] = None,
        config_path: str = "./config/quality_thresholds.yaml",
        hardware_profile: Optional[HardwareProfile] = None,
    ) -> None:
        # mock_mode is ONLY for testing — production always uses real analysis.
        # Default to False (real path); only set True via explicit parameter or MOCK_LLM env.
        if mock_mode is not None:
            self.mock_mode = mock_mode
        else:
            self.mock_mode = os.environ.get("MOCK_LLM", "false").lower() == "true"

        # Hard-metric thresholds overridden by hardware profile (Optional — None when
        # the profile does not enable hardware-tier thresholds). Declared here so the
        # later Optional[float] assignments (mock/potato tier) are type-consistent.
        self._hw_dnsmos_min: Optional[float] = None
        self._hw_asr_wer_max: Optional[float] = None
        self._hw_speaker_sim_min: Optional[float] = None

        # Check which optional hard-metric dependencies are available.
        # This enables graceful degradation: missing deps skip their metric
        # instead of forcing the entire pipeline into mock mode.
        self._available_features = self._check_optional_dependencies()
        # Safety gate: heavy native audio-metric models (faster-whisper/ctranslate2)
        # can hard-crash the whole process on some hosts. Unit tests and other
        # constrained environments set AUDIO_HARD_METRICS_DISABLED=1 to force
        # graceful skip of DNSMOS/ASR/SpeakerSim hard checks.
        import os as _os

        if _os.environ.get("AUDIO_HARD_METRICS_DISABLED", "").lower() in ("1", "true", "yes"):
            for _k in ("dnsmos", "asr", "speaker_sim"):
                self._available_features[_k] = False

        # Create router (mock mode passed directly to avoid thread-unsafe env manipulation)
        if router is None:
            self.router = create_router(mock_mode=self.mock_mode)
        else:
            self.router = router

        self.judge = judge or create_judge(router=self.router)

        # Hardware profile for quality check configuration
        self.hardware_profile = hardware_profile or get_hardware_profile()

        # Load quality thresholds for compliance monitoring
        self.quality_thresholds = load_quality_thresholds(config_path)
        self._config_path = config_path
        # mtime of config at last load — None until first reload records one.
        self._last_config_modified: Optional[float] = None

        # Initialize hard quality check suite (DNSMOS + ASR WER + Speaker Sim)
        self._quality_suite = QualityCheckSuite(
            config=dict(self.quality_thresholds),
            hardware_profile=self.hardware_profile.active_profile,
        )

        # Apply hardware profile quality check settings
        self._sync_hardware_profile()

        # Log available features for diagnostics
        enabled = [k for k, v in self._available_features.items() if v]
        disabled = [k for k, v in self._available_features.items() if not v]
        logger.info(f"Quality features — enabled: {enabled}, disabled: {disabled}")

    @staticmethod
    def _check_optional_dependencies() -> Dict[str, bool]:
        """Check availability of optional hard-metric dependencies.

        Returns a dict mapping feature name to bool (available or not).
        This allows graceful degradation: missing deps skip their metric
        instead of forcing the entire pipeline into mock mode.

        Features:
            - ffmpeg: Always True (core dependency)
            - dnsmos: ONNX Runtime for DNSMOS scoring
            - asr: FunASR, faster-whisper, or openai-whisper for WER
            - speaker_sim: torch + SpeechBrain for speaker embeddings
        """
        features: Dict[str, bool] = {
            "ffmpeg": True,  # Always available — core dependency
            "dnsmos": False,  # ONNX Runtime for DNSMOS scoring
            "asr": False,  # FunASR or faster-whisper for WER
            "speaker_sim": False,  # torch + SpeechBrain for speaker embeddings
        }

        # Check ONNX Runtime (for DNSMOS)
        try:
            import onnxruntime  # noqa: F401

            features["dnsmos"] = True
        except Exception:
            # Optional dep: a failed import (missing OR a native/torch conflict at
            # runtime) must degrade gracefully to "dnsmos unavailable" rather than
            # crash pipeline construction.
            pass

        # Check ASR backends (FunASR or faster-whisper)
        try:
            import funasr  # noqa: F401

            features["asr"] = True
        except Exception:
            # ``funasr`` pulls in ``torch``; a runtime import failure (e.g. a
            # polluted/native-torch conflict) is treated as "asr unavailable".
            try:
                import faster_whisper  # noqa: F401

                features["asr"] = True
            except Exception:
                try:
                    import whisper  # noqa: F401

                    features["asr"] = True
                except Exception:
                    pass

        # Check Speaker Similarity (torch + speechbrain)
        try:
            import torch  # noqa: F401
            from speechbrain.inference.speaker import EncoderClassifier  # noqa: F401

            features["speaker_sim"] = True
        except Exception:
            pass

        return features

    def _apply_hardware_profile_quality_config(self) -> None:
        """Apply quality check settings from hardware profile."""
        if not self.hardware_profile:
            return

        qc = self.hardware_profile.quality_check

        # Override thresholds from hardware profile if enabled
        if qc.dnsmos_enabled and "thresholds" in qc.__dict__:
            # Store hardware profile thresholds for use in judgment
            self._hw_dnsmos_min = qc.thresholds.get("dnsmos_min", 3.5)
            self._hw_asr_wer_max = qc.thresholds.get("asr_wer_max", 0.05)
            self._hw_speaker_sim_min = qc.thresholds.get("speaker_sim_min", 0.85)
        else:
            self._hw_dnsmos_min = None
            self._hw_asr_wer_max = None
            self._hw_speaker_sim_min = None

        # Store feature flags
        self._hw_dnsmos_enabled = qc.dnsmos_enabled
        self._hw_asr_enabled = qc.asr_enabled
        self._hw_speaker_sim_enabled = qc.speaker_similarity_enabled

    def _sync_hardware_profile(self) -> None:
        """Re-apply the active hardware profile to this checker.

        Safe to call before each :meth:`run`. It re-resolves the live
        :class:`HardwareProfile` singleton, so a runtime
        ``set_active_profile`` / ``reload_hardware_profile`` is observed without
        restarting the process. The underlying :class:`QualityCheckSuite` is
        rebuilt whenever the active tier actually changes, because its device
        selection (CPU vs CUDA) is bound at construction time.
        """
        if not self.hardware_profile:
            return
        current = self.hardware_profile.active_profile
        self._apply_hardware_profile_quality_config()
        if getattr(self._quality_suite, "hardware_profile", None) != current:
            self._quality_suite = QualityCheckSuite(
                config=dict(self.quality_thresholds),
                hardware_profile=current,
            )

    def _reload_config_if_changed(self) -> None:
        """Hot-reload quality thresholds if config file changed."""
        from ..config.loader import reload_config_if_changed

        self.quality_thresholds, self._last_config_modified = reload_config_if_changed(
            self._config_path, self._last_config_modified
        )

    def _get_threshold(self, *keys: str, default: Any = None) -> Any:
        """Get nested threshold value from config.

        Hardware profile thresholds take precedence over file config.
        Threshold values are heterogeneous (floats/ints), so the return is Any;
        callers fold the result into typed locals with explicit defaults.
        """
        # Check hardware profile thresholds first
        if keys == ("audio", "dnsmos_min") and hasattr(self, "_hw_dnsmos_min") and self._hw_dnsmos_min is not None:
            return self._hw_dnsmos_min
        if keys == ("audio", "asr_wer_max") and hasattr(self, "_hw_asr_wer_max") and self._hw_asr_wer_max is not None:
            return self._hw_asr_wer_max
        if (
            keys == ("audio", "speaker_sim_min")
            and hasattr(self, "_hw_speaker_sim_min")
            and self._hw_speaker_sim_min is not None
        ):
            return self._hw_speaker_sim_min

        # Walk nested config; values are heterogeneous (dicts/scalars), so Any.
        value: Any = self.quality_thresholds
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return default
            if value is None:
                return default
        return value if value is not None else default

    def _analyze_audio_rules(self, audio_path: Path, expected_duration_ms: int) -> AudioAnalysisResult:
        """Rule-based audio analysis using ffprobe/ffmpeg subprocess.

        Uses the ffmpeg_probe utility for Python 3.14+ compatibility.
        """
        # MOCK: 待真实实现
        # Mock mode: return defaults without actual analysis
        if self.mock_mode:
            return AudioAnalysisResult(
                duration_ms=expected_duration_ms,
                has_silence=False,
                silence_regions=[],
                has_clipping=False,
                rms_db=-20.0,
                peak_db=-3.0,
                duration_match=True,
                issues=[],
            )

        # Use ffprobe-based analysis via utility module
        try:
            return self._analyze_with_ffprobe(audio_path, expected_duration_ms)
        except FileNotFoundError:
            logger.error("ffprobe not found, cannot analyze audio")
            return AudioAnalysisResult(
                duration_ms=expected_duration_ms,
                has_silence=False,
                silence_regions=[],
                has_clipping=False,
                rms_db=-60.0,
                peak_db=-60.0,
                duration_match=False,
                issues=["ffprobe_not_found"],
            )
        except (OSError, subprocess.CalledProcessError, ValueError, RuntimeError) as e:
            logger.error(f"Audio analysis failed for {audio_path}: {e}")
            return AudioAnalysisResult(
                duration_ms=expected_duration_ms,
                has_silence=False,
                silence_regions=[],
                has_clipping=False,
                rms_db=-60.0,
                peak_db=-60.0,
                duration_match=False,
                issues=[f"analysis_error: {str(e)}"],
            )
        except Exception as e:
            logger.error(f"Unexpected audio analysis error for {audio_path}: {e}")
            return AudioAnalysisResult(
                duration_ms=expected_duration_ms,
                has_silence=False,
                silence_regions=[],
                has_clipping=False,
                rms_db=-60.0,
                peak_db=-60.0,
                duration_match=False,
                issues=[f"analysis_error: {str(e)}"],
            )

    def _analyze_with_ffprobe(self, audio_path: Path, expected_duration_ms: int) -> AudioAnalysisResult:
        """Audio analysis using ffprobe/ffmpeg subprocess (Python 3.14+ compatible)."""
        # Hot-reload config if changed
        self._reload_config_if_changed()

        # Get thresholds from config
        silence_threshold_db = self._get_threshold("audio", "silence_threshold_db", default=-40.0)
        clipping_threshold = self._get_threshold("audio", "clipping_threshold_percent", default=0.001)
        duration_match_threshold = self._get_threshold("audio", "duration_match_threshold_percent", default=30) / 100.0
        low_volume_threshold_db = self._get_threshold("audio", "low_volume_threshold_db", default=-30)
        high_volume_threshold_db = self._get_threshold("audio", "high_volume_threshold_db", default=-1)

        try:
            # Step 1: Get duration using utility
            actual_duration_ms = get_duration_sync(audio_path)

            # Duration match check (from config)
            duration_match = (
                abs(actual_duration_ms - expected_duration_ms) / max(expected_duration_ms, 1) < duration_match_threshold
            )

            # Step 2: Detect silence regions using utility
            silence_regions = detect_silence_sync(
                audio_path,
                threshold_db=silence_threshold_db,
                min_duration_ms=500,
            )
            has_silence = len(silence_regions) > 0

            # Step 3: Get RMS and peak using utility
            rms_db, peak_db = get_rms_peak_sync(audio_path)

            # Step 4: Read PCM samples for clipping detection
            samples = read_pcm_samples_sync(audio_path, sample_rate=16000, channels=1)

            if len(samples) == 0:
                # No audio data; return what we have
                return AudioAnalysisResult(
                    duration_ms=actual_duration_ms or expected_duration_ms,
                    has_silence=False,
                    silence_regions=[],
                    has_clipping=False,
                    rms_db=-60.0,
                    peak_db=-60.0,
                    duration_match=duration_match,
                    issues=["no_audio_data"] if not actual_duration_ms else [],
                )

            # Clipping detection (from config)
            clipped_samples = int(np.sum(np.abs(samples) >= 0.99))
            total_samples = len(samples)
            has_clipping = clipped_samples > max(10, total_samples * clipping_threshold)

            # Step 5: Compile issues
            issues = []
            if not duration_match:
                issues.append(f"duration_mismatch: expected {expected_duration_ms}ms, got {actual_duration_ms}ms")
            if has_clipping:
                issues.append(f"clipping: {clipped_samples}/{total_samples} samples clipped")
            if has_silence:
                silence_report = "; ".join(f"{s:.0f}-{e:.0f}ms" for s, e in silence_regions[:5])
                issues.append(f"silence: {len(silence_regions)} silent regions detected ({silence_report})")

            # Volume thresholds from config (with defaults)
            if rms_db < low_volume_threshold_db:
                issues.append(f"low_volume: RMS={rms_db:.1f}dB below threshold ({low_volume_threshold_db}dB)")
            if rms_db > high_volume_threshold_db:
                issues.append(f"high_volume: RMS={rms_db:.1f}dB may clip")

            logger.info(
                f"Audio analysis (ffprobe): duration={actual_duration_ms}ms match={duration_match} "
                f"rms={rms_db:.1f}dB peak={peak_db:.1f}dB "
                f"silence={len(silence_regions)} clipping={has_clipping} "
                f"issues={len(issues)}"
            )

            return AudioAnalysisResult(
                duration_ms=actual_duration_ms,
                has_silence=has_silence,
                silence_regions=silence_regions,
                has_clipping=has_clipping,
                rms_db=rms_db,
                peak_db=peak_db,
                duration_match=duration_match,
                issues=issues,
            )

        except FileNotFoundError:
            raise
        except (OSError, subprocess.CalledProcessError, ValueError, RuntimeError) as e:
            logger.error(f"ffprobe analysis failed: {e}")
            raise

    def _build_audio_description(self, analysis: AudioAnalysisResult, annotation: ParagraphAnnotation) -> str:
        """Build text description of audio for LLM judge."""
        desc = f"音频时长 {analysis.duration_ms}ms"
        if analysis.has_silence:
            desc += f"，检测到 {len(analysis.silence_regions)} 处静音段"
        if analysis.has_clipping:
            desc += "，存在削波失真"
        desc += f"，RMS {analysis.rms_db:.1f}dB，峰值 {analysis.peak_db:.1f}dB"
        if not analysis.duration_match:
            desc += f"，时长与预期不符(预期{analysis.duration_ms}ms)"
        return desc

    def _encode_audio_base64(self, audio_path: Path) -> Optional[str]:
        """Encode audio file to base64 for multimodal LLM."""
        try:
            with open(audio_path, "rb") as f:
                audio_bytes = f.read()
            return base64.b64encode(audio_bytes).decode("utf-8")
        except (OSError, ValueError) as e:  # IOError is an alias of OSError
            logger.error(f"Failed to encode audio {audio_path}: {e}")
            return None

    def _should_use_multimodal_judge(self) -> bool:
        """Check if multimodal judge should be used based on hardware profile."""
        if not self.hardware_profile:
            return False
        # Only use multimodal in pro_studio or cloud_hybrid with good GPU
        return (
            self.hardware_profile.active_profile in ("pro_studio", "cloud_hybrid")
            and self.hardware_profile.is_gpu_available()
        )

    def _multimodal_judge_quality(
        self,
        segment_id: str,
        audio_path: Path,
        annotation: ParagraphAnnotation,
        reference_text: str,
    ) -> Optional[QualityJudgment]:
        """
        Use multimodal LLM (Gemini 1.5 Flash) to directly listen to audio and judge quality.
        This provides true audio understanding unlike text-description-based LLM judge.
        """
        # Check hardware profile for multimodal capability
        if not self._should_use_multimodal_judge():
            logger.debug("Multimodal judge skipped: not enabled in current hardware profile")
            return None

        try:
            audio_b64 = self._encode_audio_base64(audio_path)
            if not audio_b64:
                logger.warning(f"Could not encode audio for multimodal judge: {audio_path}")
                return None

            prompt = self._build_multimodal_prompt(segment_id, annotation, reference_text, audio_b64)

            from ..schemas import QualityJudgment

            messages = [
                {
                    "role": "system",
                    "content": "你是专业的有声书音频质量检测专家。请直接听取音频并评分，输出严格符合 JSON Schema 的 QualityJudgment。",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "audio",
                            "source": {"data": audio_b64, "mime_type": "audio/mp3"},
                        },
                    ],
                },
            ]

            result = self.router.call(
                stage="quality",
                response_model=QualityJudgment,
                messages=messages,
            )

            if result and result.output:
                logger.info(
                    f"Multimodal quality judge completed for {segment_id}: score={result.output.overall_score:.2f}"
                )
                return cast(QualityJudgment, result.output)

        except (ValueError, RuntimeError, OSError) as e:  # OSError covers Connection/Timeout
            logger.warning(f"Multimodal quality judge failed for {segment_id}: {e}")
            return None

        return None

    def _build_multimodal_prompt(
        self,
        segment_id: str,
        annotation: ParagraphAnnotation,
        reference_text: str,
        audio_b64: str,
    ) -> str:
        """Build prompt for multimodal quality判断."""
        lines = []
        lines.append("请直接听取音频文件, 评估有声书片段的质量。")
        lines.append("")
        lines.append("**片段信息:**")
        lines.append(f"- 片段ID: {segment_id}")
        lines.append(f"- 说话人: {annotation.speaker_canonical_name}")
        lines.append(f"- 是否对话: {annotation.is_dialogue}")
        lines.append(f"- 期望情感: {annotation.emotion} (强度: {annotation.emotion_intensity})")
        lines.append(f"- 期望语速: {annotation.speech_rate}x")
        lines.append(f"- 期望音高偏移: {annotation.pitch_shift_semitones} 半音")
        lines.append(f"- 参考文本: {reference_text[:200]}...")
        lines.append("")
        lines.append("**评分维度 (0-1分):**")
        lines.append("1. speaker_clarity - 说话人清晰度 (声音是否清晰可辨、无杂音)")
        lines.append("2. emotion_match - 情感匹配度 (实际情感是否与期望一致)")
        lines.append("3. prosody_naturalness - 韵律自然度 (语调、节奏、停顿是否自然)")
        lines.append("4. text_audio_alignment - 文音对齐 (音频内容是否与文本匹配)")
        lines.append("")
        lines.append("**输出格式: 严格符合 QualityJudgment JSON Schema, 包含:")
        lines.append("{")
        lines.append(f'  "segment_id": "{segment_id}",')
        lines.append('  "speaker_clarity": 0.0-1.0,')
        lines.append('  "emotion_match": 0.0-1.0,')
        lines.append('  "prosody_naturalness": 0.0-1.0,')
        lines.append('  "text_audio_alignment": 0.0-1.0,')
        lines.append('  "overall_score": 0.0-1.0,')
        lines.append('  "issues": ["issue1", "issue2"],')
        lines.append('  "fix_suggestions": ["建议1", "建议2"],')
        lines.append('  "needs_regeneration": true/false,')
        lines.append('  "judge_model": "gemini-1.5-flash-multimodal",')
        lines.append('  "contract_version": 1,')
        lines.append('  "confidence": 0.0-1.0,')
        lines.append('  "rationale": "详细判断理由"')
        lines.append("}")
        return "\n".join(lines)

    def _run_hard_quality_checks(
        self,
        audio_path: Path,
        reference_text: str,
        speaker_id: Optional[str] = None,
        reference_speaker_audio: Optional[Path] = None,
    ) -> QualityCheckResult:
        """Run hard quality checks (DNSMOS + ASR WER + Speaker Similarity).

        Gracefully skips metrics whose dependencies are unavailable,
        rather than failing the entire check.
        """
        # If no hard metric deps are available, skip entirely
        any_available = any(self._available_features.get(k) for k in ("dnsmos", "asr", "speaker_sim"))
        if not any_available:
            logger.info("No hard metric dependencies available — skipping DNSMOS/ASR/SpeakerSim")
            return QualityCheckResult(
                passed=True,
                overall_message="Hard metrics skipped (no optional dependencies available)",
            )

        # Run the actual quality check suite
        return self._quality_suite.check_all(
            audio_path=audio_path,
            reference_text=reference_text,
            reference_speaker_id=speaker_id,
            reference_speaker_audio=reference_speaker_audio,
        )

    @trace_function(name="pipeline.quality_check.run", stage="quality")  # type: ignore[untyped-decorator]  # langfuse trace_function returns Callable[..., Any]; cannot make it parametric from here
    def run(
        self,
        inputs: List[QualityRunInput],
        *,
        golden_feedback: bool = False,
        golden_feedback_split: str = "val",
        golden_feedback_stage: str = "judge",
    ) -> List[QualityJudgment]:
        """Run quality check on synthesized segments.

        Args:
            inputs: List of (audio_path, paragraph_annotation, routing_decision, reference_text)

        Keyword Args:
            golden_feedback: 若为真，将每段质检判定（pass/fail + 原因）回流为
                ``judge`` 阶段金标样本（A2：quality_check → golden 闭环）。默认关闭，
                避免污染生产数据流。也可用环境变量 ``AUDIOBOOK_GOLDEN_FEEDBACK=1`` 全局开启。
            golden_feedback_split: 回流目标 split（默认 ``val``，不进 train 防污染）。
            golden_feedback_stage: 回流目标 stage（默认 ``judge``）。
        """
        # 环境变量可全局开启质检回流（A2），便于在生产入口处统一开关。
        if not golden_feedback and os.environ.get("AUDIOBOOK_GOLDEN_FEEDBACK", "0") == "1":
            golden_feedback = True

        # Re-resolve the active hardware profile so a runtime tier switch
        # (set_active_profile / reload_hardware_profile) is reflected here
        # without a process restart.
        self._sync_hardware_profile()
        logger.info(f"Quality checking {len(inputs)} segments")

        # Emit stage enter
        if inputs:
            annotation = inputs[0][1]
            project_id = getattr(annotation, "book_id", 0) or 0
            chapter_index = getattr(annotation, "chapter_index", 1)
            # Default to project_id=1 if not set (for testing)
            if project_id == 0:
                project_id = 1
            try:
                import asyncio

                loop = asyncio.get_running_loop()
                loop.create_task(
                    emit_stage_enter(
                        stage="quality",
                        project_id=project_id,
                        chapter_index=chapter_index,
                        total_items=len(inputs),
                    )
                )
            except RuntimeError:
                pass

        judgments: List[QualityJudgment] = []
        # 与 judgments 一一对应配对（(annotation, reference_text)），供 A2 回流。
        qc_pairs: List[Tuple[Any, str]] = []
        # 当前段的音频描述（非 mock 分支才会赋值），供 A2 样本富化；默认 None。
        audio_description: Optional[str] = None

        for i, (audio_path, annotation, routing, reference_text) in enumerate(inputs):
            # Emit stage progress
            annotation = inputs[i][1]
            project_id = getattr(annotation, "book_id", 0) or 0
            chapter_index = getattr(annotation, "chapter_index", 1)
            # Default to project_id=1 if not set (for testing)
            if project_id == 0:
                project_id = 1
            try:
                import asyncio

                loop = asyncio.get_running_loop()
                loop.create_task(
                    emit_stage_progress(
                        stage="quality",
                        project_id=project_id,
                        chapter_index=chapter_index,
                        current=i + 1,
                        total=len(inputs),
                        message=f"Quality checking segment {i + 1}/{len(inputs)}",
                    )
                )
            except RuntimeError:
                pass

            logger.info(f"Checking quality: {audio_path}")
            logger.info(f"Checking quality: {audio_path}")

            # Rule-based analysis (runs in both mock and non-mock mode)
            rule_start_time = time.time()
            analysis = self._analyze_audio_rules(Path(audio_path), routing.estimated_duration_ms)
            rule_latency_ms = (time.time() - rule_start_time) * 1000

            # Record rule-based quality check observation
            rule_passed = len(analysis.issues) == 0
            rule_score = 1.0 if rule_passed else max(0.0, 1.0 - len(analysis.issues) * 0.2)
            observe_quality_check(
                stage="rule_based",
                passed=rule_passed,
                score=rule_score,
                issues=analysis.issues,
                latency_ms=rule_latency_ms,
            )

            # Mock mode: skip hard quality checks entirely (DNSMOS/ASR/SpeakerSim)
            # Mock audio has no real acoustic features, so hard metrics would fail
            if self.mock_mode:
                # Call judge in mock mode to get the mock judgment
                judgment = self.judge.judge_quality(
                    segment_id=routing.segment_id,
                    paragraph_annotation=annotation,
                    audio_description=f"Mock audio analysis: duration={analysis.duration_ms}ms, issues={analysis.issues}",
                    reference_text=reference_text,
                )
                # Merge rule-based issues into judgment.
                # analysis.issues are free-text diagnostics (List[str]); QualityJudgment.issues
                # is a strict Literal enum, so the free-text diagnostics are surfaced via the
                # rationale-bearing FixSuggestion. cast preserves the existing runtime merge
                # of diagnostics into the typed issues list against the (out-of-scope) schema.
                if analysis.issues:
                    judgment.issues = cast(List[Any], list(analysis.issues) + list(judgment.issues))
                    judgment.needs_regeneration = True
                    judgment.fix_suggestions = [
                        FixSuggestion(
                            suggestion_type="content_edit",
                            target_text=reference_text[:50] if reference_text else "",
                            current_value=None,
                            suggested_value="重新合成以修复音频质量问题",
                            rationale=f"Rule-based issues: {analysis.issues}",
                        )
                    ]
                judgments.append(judgment)
                # A2 回流配对：判定与对应标注/参考文本同步收集。
                qc_pairs.append((annotation, reference_text))
                # A2 运行时自动回流：判定推入全局收集器，交由 SOPBackgroundThread 抽干。
                if golden_feedback:
                    try:
                        get_quality_judgment_collector().add(judgment, annotation, reference_text, audio_description)
                    except Exception:  # 收集失败绝不应中断主链路
                        pass
                continue

            # MOCK: 待真实实现
            # Non-mock mode: run hard quality checks (conditional) + LLM judge
            hard_start_time = time.time()
            hard_result = self._run_hard_quality_checks(
                audio_path=Path(audio_path),
                reference_text=reference_text,
                speaker_id=getattr(annotation, "speaker_canonical_name", None),
            )
            hard_latency_ms = (time.time() - hard_start_time) * 1000

            # Record hard quality checks observation
            observe_quality_check(
                stage="hard_checks",
                passed=hard_result.passed,
                score=1.0 if hard_result.passed else 0.5,
                issues=[hard_result.overall_message] if not hard_result.passed else [],
                latency_ms=hard_latency_ms,
            )

            # Build audio description for LLM judge (always runs)
            audio_description = self._build_audio_description(analysis, annotation)

            # Include hard check results in audio description (only if actually computed)
            if hard_result.dnsmos and hard_result.dnsmos.success:
                audio_description += f"，DNSMOS综合={hard_result.dnsmos.mos_ovr:.2f}"
            if hard_result.wer and hard_result.wer.success:
                audio_description += f"，ASR WER={hard_result.wer.wer:.1%}"
            if hard_result.speaker_sim and hard_result.speaker_sim.success:
                audio_description += f"，声纹相似度={hard_result.speaker_sim.similarity:.3f}"

            # Start timing for LLM judgment
            judgment_start_time = time.time()

            # Prepare real audio metrics for the judge (P0-C1)
            real_metrics: Optional[Dict[str, Any]] = None
            if not self.mock_mode and hard_result:

                def _numeric(v: Any) -> Optional[float]:
                    # Defensive: hard-check results may surface non-numeric
                    # placeholders (e.g. when a feature is unavailable); only
                    # pass real scores to the MOS fuser.
                    return v if isinstance(v, (int, float)) else None

                real_metrics = {
                    "utmos": (
                        _numeric(hard_result.utmos.mos) if hard_result.utmos and hard_result.utmos.success else None
                    ),
                    "dnsmos": (
                        _numeric(hard_result.dnsmos.mos_ovr)
                        if hard_result.dnsmos and hard_result.dnsmos.success
                        else None
                    ),
                    "wer": _numeric(hard_result.wer.wer) if hard_result.wer and hard_result.wer.success else None,
                    "speaker_sim": (
                        _numeric(hard_result.speaker_sim.similarity)
                        if hard_result.speaker_sim and hard_result.speaker_sim.success
                        else None
                    ),
                }
                # Count available metrics
                avail = sum(1 for v in real_metrics.values() if v is not None)
                if avail:
                    real_metrics["available_metrics"] = avail
                    real_metrics["overall"] = fuse_audio_scores(
                        real_metrics.get("utmos"),
                        real_metrics.get("dnsmos"),
                        real_metrics.get("wer"),
                        real_metrics.get("speaker_sim"),
                    )

            # LLM-as-a-Judge evaluation
            try:
                from ..monitoring import record_stage_performance

                judgment = self.judge.judge_quality(
                    segment_id=Path(audio_path).stem,
                    paragraph_annotation=annotation,
                    audio_description=audio_description,
                    reference_text=reference_text,
                    real_audio_metrics=real_metrics,
                )

                judgment_latency_ms = (time.time() - judgment_start_time) * 1000

                # Combine rule-based issues (free-text diagnostics into the typed issues list,
                # see schema-gap note above; cast preserves existing runtime behaviour).
                if analysis.issues:
                    cast(List[Any], judgment.issues).extend(analysis.issues)
                    # If rule-based issues exist, may need regeneration
                    if any("clipping" in i or "silence" in i for i in analysis.issues):
                        judgment.needs_regeneration = True
                        judgment.fix_suggestions.append(
                            FixSuggestion(
                                suggestion_type="content_edit",
                                target_text=reference_text[:50] if reference_text else "",
                                current_value=None,
                                suggested_value="重新合成以修复音频质量问题",
                                rationale="rule-based clipping/silence issue",
                            )
                        )

                # Incorporate hard quality check results into judgment
                if not hard_result.passed:
                    judgment.needs_regeneration = True
                    cast(List[Any], judgment.issues).append(f"Hard quality check failed: {hard_result.overall_message}")
                    judgment.fix_suggestions.append(
                        FixSuggestion(
                            suggestion_type="content_edit",
                            target_text=reference_text[:50] if reference_text else "",
                            current_value=None,
                            suggested_value="重新合成以通过硬质检门禁",
                            rationale=f"hard quality check failed: {hard_result.overall_message}",
                        )
                    )

                # Adjust scores based on hard checks
                if hard_result.dnsmos and hard_result.dnsmos.success:
                    # DNSMOS 映射到 1-5 -> 0-1
                    dnsmos_score = hard_result.dnsmos.mos_ovr / 5.0
                    judgment.speaker_clarity = (judgment.speaker_clarity + dnsmos_score) / 2

                if hard_result.speaker_sim and hard_result.speaker_sim.success:
                    # Speaker similarity directly maps to clarity
                    judgment.speaker_clarity = (judgment.speaker_clarity + hard_result.speaker_sim.similarity) / 2

                logger.info(
                    f"Quality judgment: overall={judgment.overall_score:.2f} "
                    f"speaker={judgment.speaker_clarity:.2f} emotion={judgment.emotion_match:.2f} "
                    f"prosody={judgment.prosody_naturalness:.2f} "
                    f"alignment={judgment.text_audio_alignment:.2f} "
                    f"regen={judgment.needs_regeneration}"
                )

                # Record LLM judge quality check observation
                judge_passed = not judgment.needs_regeneration
                # observe_quality_check expects list[str]; judgment.issues is a list of
                # Literal issue tags (each a str value) — cast narrows the invariant list.
                judge_issues: List[str] = cast(List[str], judgment.issues) if judgment.issues else []
                observe_quality_check(
                    stage="llm_judge",
                    passed=judge_passed,
                    score=judgment.overall_score,
                    issues=judge_issues,
                    latency_ms=judgment_latency_ms,
                )

                # Record performance metric for quality check
                input_chars = len(audio_description) + len(str(annotation)) + len(reference_text)
                output_chars = len(str(judgment))

                tokens_in = max(1, input_chars // 4)
                tokens_out = max(1, output_chars // 4)

                cost_usd = 0.002

                record_stage_performance(
                    stage="quality_check",
                    latency_ms=judgment_latency_ms,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=cost_usd,
                    success=True,
                    quality_score=judgment.overall_score,
                    provider="llm_judge",
                    model="unknown",
                    schema_compliance=True,
                )

                judgments.append(judgment)
                qc_pairs.append((annotation, reference_text))
                # A2 运行时自动回流：判定推入全局收集器，交由 SOPBackgroundThread 抽干。
                if golden_feedback:
                    try:
                        get_quality_judgment_collector().add(judgment, annotation, reference_text, audio_description)
                    except Exception:  # 收集失败绝不应中断主链路
                        pass
            except (ValueError, RuntimeError, OSError):  # OSError covers Connection/Timeout
                from ..monitoring import record_stage_performance

                judgment_latency_ms = (time.time() - judgment_start_time) * 1000
                record_stage_performance(
                    stage="quality_check",
                    latency_ms=judgment_latency_ms,
                    tokens_in=max(
                        1,
                        (len(audio_description) + len(str(annotation)) + len(reference_text)) // 4,
                    ),
                    tokens_out=max(1, 0),
                    cost_usd=0.002,
                    success=False,
                    quality_score=None,
                    provider="llm_judge",
                    model="unknown",
                    schema_compliance=False,
                )
                raise

        # Emit stage exit (success)
        if inputs:
            annotation = inputs[0][1]
            project_id = getattr(annotation, "book_id", 0) or 0
            chapter_index = getattr(annotation, "chapter_index", 1)
            # Default to project_id=1 if not set (for testing)
            if project_id == 0:
                project_id = 1
            try:
                import asyncio

                loop = asyncio.get_running_loop()
                loop.create_task(
                    emit_stage_exit(
                        stage="quality",
                        project_id=project_id,
                        chapter_index=chapter_index,
                        success=True,
                    )
                )
            except RuntimeError:
                pass

        # A2 质检回流：将本批判定（pass/fail + 原因）归一化为 judge 金标样本。
        # 已产出的判定（即便个别段走异常路径未产出）都在此回流为可学习数据；
        # 用环境变量或 run(golden_feedback=True) 开启，默认关闭以防污染生产数据。
        if golden_feedback and judgments:
            try:
                from ..feedback.loop import quality_judgments_to_golden

                added = quality_judgments_to_golden(
                    judgments,
                    annotations=[a for a, _ in qc_pairs],
                    reference_texts=[r for _, r in qc_pairs],
                    split=golden_feedback_split,
                    stage=golden_feedback_stage,
                )
                logger.info(
                    f"[A2 golden feedback]回流 {added} 条质检判定 -> "
                    f"{golden_feedback_split}/{golden_feedback_stage}"
                )
            except Exception as e:  # 回流失败绝不应中断主链路
                logger.warning(f"[A2 golden feedback]回流失败（已跳过）: {e}")

        return judgments


def quality_check(
    inputs: List[QualityRunInput],
    mock_mode: bool = False,
) -> List[QualityJudgment]:
    """Convenience function for quality check."""
    pipeline = QualityCheckPipeline(mock_mode=mock_mode)
    # run() is wrapped by trace_function (returns Callable[..., Any]), so its
    # declared return type is erased to Any here; cast restores the contract.
    return cast(List[QualityJudgment], pipeline.run(inputs))


if __name__ == "__main__":  # pragma: no cover

    logging.basicConfig(level=logging.INFO)
    logger.info("QualityCheckPipeline ready")
