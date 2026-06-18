"""Pipeline Stage 6: Quality Check - Multi-dimensional audio quality assessment.

Combines rule-based checks (silence, clipping, duration) with LLM-as-a-Judge
for speaker/emotion/prosody evaluation. Triggers regeneration on failure.
"""

import base64
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np

from ..monitoring.langfuse_client import (
    is_enabled,
    observe_quality_check,
    trace_function,
)

from ..config.loader import load_quality_thresholds
from ..llm import LLMJudge, LLMRouter, create_judge, create_router
from ..monitoring import record_stage_performance
from ..schemas import ParagraphAnnotation, QualityJudgment, TtsRoutingDecision
from ..utils.ffmpeg_probe import (
    detect_silence_sync,
    get_duration_sync,
    get_rms_peak_sync,
    read_pcm_samples_sync,
)

logger = logging.getLogger(__name__)


@dataclass
class AudioAnalysisResult:
    """Result of rule-based audio analysis."""

    duration_ms: int
    has_silence: bool
    silence_regions: List[tuple]  # (start_ms, end_ms)
    has_clipping: bool
    rms_db: float
    peak_db: float
    duration_match: bool  # vs estimated
    issues: List[str]


class QualityCheckPipeline:
    """Pipeline for audio quality checking."""

    def __init__(
        self,
        router=None,
        judge=None,
        mock_mode=False,
        config_path: str = "./config/quality_thresholds.yaml",
    ):
        self.router = router or create_router(mock_mode=mock_mode)
        self.judge = judge or create_judge(router=self.router)
        self.mock_mode = mock_mode
        # Load quality thresholds for compliance monitoring
        self.quality_thresholds = load_quality_thresholds(config_path)
        self._config_path = config_path
        self._last_config_modified = None

    def _reload_config_if_changed(self):
        """Hot-reload quality thresholds if config file changed."""
        from ..config.loader import reload_config_if_changed

        self.quality_thresholds, self._last_config_modified = reload_config_if_changed(
            self._config_path, self._last_config_modified
        )

    def _get_threshold(self, *keys, default=None):
        """Get nested threshold value from config."""
        value = self.quality_thresholds
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return default
            if value is None:
                return default
        return value if value is not None else default

    def _analyze_audio_rules(
        self, audio_path: Path, expected_duration_ms: int
    ) -> AudioAnalysisResult:
        """Rule-based audio analysis using ffprobe/ffmpeg subprocess.

        Uses the ffmpeg_probe utility for Python 3.14+ compatibility.
        """
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
        except Exception as e:
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

    def _analyze_with_ffprobe(
        self, audio_path: Path, expected_duration_ms: int
    ) -> AudioAnalysisResult:
        """Audio analysis using ffprobe/ffmpeg subprocess (Python 3.14+ compatible)."""
        # Hot-reload config if changed
        self._reload_config_if_changed()

        # Get thresholds from config
        silence_threshold_db = self._get_threshold(
            "audio", "silence_threshold_db", default=-40.0
        )
        clipping_threshold = self._get_threshold(
            "audio", "clipping_threshold_percent", default=0.001
        )
        duration_match_threshold = (
            self._get_threshold("audio", "duration_match_threshold_percent", default=30)
            / 100.0
        )
        low_volume_threshold_db = self._get_threshold(
            "audio", "low_volume_threshold_db", default=-30
        )
        high_volume_threshold_db = self._get_threshold(
            "audio", "high_volume_threshold_db", default=-1
        )

        try:
            # Step 1: Get duration using utility
            actual_duration_ms = get_duration_sync(audio_path)

            # Duration match check (from config)
            duration_match = (
                abs(actual_duration_ms - expected_duration_ms)
                / max(expected_duration_ms, 1)
                < duration_match_threshold
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
                issues.append(
                    f"duration_mismatch: expected {expected_duration_ms}ms, got {actual_duration_ms}ms"
                )
            if has_clipping:
                issues.append(
                    f"clipping: {clipped_samples}/{total_samples} samples clipped"
                )
            if has_silence:
                silence_report = "; ".join(
                    f"{s:.0f}-{e:.0f}ms" for s, e in silence_regions[:5]
                )
                issues.append(
                    f"silence: {len(silence_regions)} silent regions detected ({silence_report})"
                )

            # Volume thresholds from config (with defaults)
            if rms_db < low_volume_threshold_db:
                issues.append(
                    f"low_volume: RMS={rms_db:.1f}dB below threshold ({low_volume_threshold_db}dB)"
                )
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
        except Exception as e:
            logger.error(f"ffprobe analysis failed: {e}")
            raise

    def _build_audio_description(
        self, analysis: AudioAnalysisResult, annotation: ParagraphAnnotation
    ) -> str:
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
        except Exception as e:
            logger.error(f"Failed to encode audio {audio_path}: {e}")
            return None

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
        if self.mock_mode:
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
                        {"type": "audio", "source": {"data": audio_b64, "mime_type": "audio/mp3"}}
                    ]
                }
            ]
            
            result = self.router.call(
                stage="quality",
                response_model=QualityJudgment,
                messages=messages,
            )
            
            if result and result.output:
                logger.info(f"Multimodal quality judge completed for {segment_id}: score={result.output.overall_score:.2f}")
                return result.output
            
        except Exception as e:
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


    @trace_function(name="pipeline.quality_check.run", stage="quality")
    def run(self, inputs: List[tuple]) -> List[QualityJudgment]:
        """Run quality check on synthesized segments.

        Args:
            inputs: List of (audio_path, paragraph_annotation, routing_decision, reference_text)
        """
        logger.info(f"Quality checking {len(inputs)} segments")

        judgments = []

        for audio_path, annotation, routing, reference_text in inputs:
            logger.info(f"Checking quality: {audio_path}")

            # Rule-based analysis
            rule_start_time = time.time()
            analysis = self._analyze_audio_rules(
                Path(audio_path), routing.estimated_duration_ms
            )
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

            # Build audio description for LLM judge
            audio_description = self._build_audio_description(analysis, annotation)

            # Start timing for LLM judgment
            judgment_start_time = time.time()

            # LLM-as-a-Judge evaluation
            try:
                judgment = self.judge.judge_quality(
                    segment_id=Path(audio_path).stem,
                    paragraph_annotation=annotation,
                    audio_description=audio_description,
                    reference_text=reference_text,
                )

                judgment_latency_ms = (time.time() - judgment_start_time) * 1000

                # Combine rule-based issues
                if analysis.issues:
                    judgment.issues.extend(analysis.issues)
                    # If rule-based issues exist, may need regeneration
                    if any("clipping" in i or "silence" in i for i in analysis.issues):
                        judgment.needs_regeneration = True
                        judgment.fix_suggestions.extend(["重新合成以修复音频质量问题"])

                logger.info(
                    f"Quality judgment: overall={judgment.overall_score:.2f} "
                    f"speaker={judgment.speaker_clarity:.2f} emotion={judgment.emotion_match:.2f} "
                    f"prosody={judgment.prosody_naturalness:.2f} "
                    f"alignment={judgment.text_audio_alignment:.2f} "
                    f"regen={judgment.needs_regeneration}"
                )

                # Record LLM judge quality check observation
                judge_passed = not judgment.needs_regeneration
                judge_issues = judgment.issues if judgment.issues else []
                observe_quality_check(
                    stage="llm_judge",
                    passed=judge_passed,
                    score=judgment.overall_score,
                    issues=judge_issues,
                    latency_ms=judgment_latency_ms,
                )

                # Record performance metric for quality check
                # Estimate token usage for LLM judgment
                # Input: audio description + annotation + reference text
                # Output: judgment (JSON-like)
                input_chars = (
                    len(audio_description) + len(str(annotation)) + len(reference_text)
                )
                output_chars = len(str(judgment))

                # Rough approximation: 1 token ≈ 4 characters
                tokens_in = max(1, input_chars // 4)
                tokens_out = max(1, output_chars // 4)

                # Estimate cost (this would depend on the LLM provider used)
                # For now, use a placeholder - in reality, this would come from the LLM router
                cost_usd = 0.002  # Placeholder for LLM judgment cost

                record_stage_performance(
                    stage="quality_check",
                    latency_ms=judgment_latency_ms,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=cost_usd,
                    success=True,  # Quality check itself succeeded if we got here
                    quality_score=judgment.overall_score,  # This is the key quality metric!
                    provider="llm_judge",  # Could be made more specific
                    model="unknown",  # Would ideally come from the judge
                    schema_compliance=True,
                )

                judgments.append(judgment)
            except Exception as e:
                judgment_latency_ms = (time.time() - judgment_start_time) * 1000
                # Record failure
                record_stage_performance(
                    stage="quality_check",
                    latency_ms=judgment_latency_ms,
                    tokens_in=max(
                        1,
                        (
                            len(audio_description)
                            + len(str(annotation))
                            + len(reference_text)
                        )
                        // 4,
                    ),
                    tokens_out=max(1, 0),  # no output on failure
                    cost_usd=0.002,  # same placeholder
                    success=False,
                    quality_score=None,
                    provider="llm_judge",
                    model="unknown",
                    schema_compliance=False,
                )
                raise  # Re-raise to propagate failure

        return judgments


def quality_check(
    inputs: List[tuple],
    mock_mode: bool = False,
) -> List[QualityJudgment]:
    """Convenience function for quality check."""
    pipeline = QualityCheckPipeline(mock_mode=mock_mode)
    return pipeline.run(inputs)


if __name__ == "__main__":  # pragma: no cover
    import sys

    logging.basicConfig(level=logging.INFO)
    print("QualityCheckPipeline ready")
