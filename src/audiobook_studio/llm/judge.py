"""LLM Judge - Quality evaluation using LLM-as-a-Judge pattern.

Implements pairwise comparison and scoring for quality gate.
"""

import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from ..schemas import AudioPostProcessParams, FixSuggestion, ParagraphAnnotation, QualityJudgment
from .router import LLMRouter, create_router

logger = logging.getLogger(__name__)


class JudgmentType(Enum):
    PAIRWISE = "pairwise"
    SCORING = "scoring"


@dataclass
class JudgeConfig:
    model: str = "claude-3-5-sonnet"
    temperature: float = 0.0
    max_tokens: int = 2000


class LLMJudge:
    """LLM-as-a-Judge for quality evaluation."""

    def __init__(self, config: Optional[JudgeConfig] = None, router: Optional[LLMRouter] = None):
        self.config = config or JudgeConfig()
        self.router = router or create_router()

    def judge_quality(
        self,
        segment_id: str,
        paragraph_annotation: ParagraphAnnotation,
        audio_description: str,  # In real impl: audio analysis via multimodal LLM
        reference_text: str,
        audio_params: Optional[AudioPostProcessParams] = None,
    ) -> QualityJudgment:
        """Evaluate audio quality against paragraph annotation.

        In production, this would use multimodal LLM to listen to audio.
        For now, uses text-based evaluation with simulated audio analysis.
        """
        if audio_params is None:
            audio_params = AudioPostProcessParams()
        # Build judgment prompt
        prompt = self._build_judgment_prompt(
            segment_id=segment_id,
            annotation=paragraph_annotation,
            audio_params=audio_params,
            audio_description=audio_description,
            reference_text=reference_text,
        )

        # Call judge model
        messages = [
            {"role": "system", "content": self._get_system_prompt()},
            {"role": "user", "content": prompt},
        ]

        try:
            result = self.router.call(
                stage="judge",
                response_model=QualityJudgment,
                messages=messages,
                segment_id=segment_id,
            )
            output = result.output
            self._log_judgment(segment_id, output)
            return output
        except Exception as e:
            logger.error(f"Quality judgment failed for {segment_id}: {e}")
            # Return safe default - requires regeneration
            return QualityJudgment(
                segment_id=segment_id,
                speaker_clarity=0.0,
                emotion_match=0.0,
                prosody_naturalness=0.0,
                text_audio_alignment=0.0,
                overall_score=0.0,
                issues=["sensitive_content"],  # Valid literal from schema
                fix_suggestions=[
                    FixSuggestion(
                        suggestion_type="prosody_correction",
                        target_text="",
                        suggested_value="",
                        rationale=f"Judge error: {str(e)}",
                        confidence=0.9,
                    )
                ],
                needs_regeneration=True,
            )

    def _get_system_prompt(self) -> str:
        return """You are an expert audiobook quality evaluator.
Evaluate the audio segment against the expected paragraph annotation.
Score each dimension 0.0-1.0. Be strict but fair.
Identify specific issues and suggest concrete fixes."""

    def _build_judgment_prompt(
        self,
        segment_id: str,
        annotation: ParagraphAnnotation,
        audio_params: "AudioPostProcessParams",
        audio_description: str,
        reference_text: str,
    ) -> str:
        return f"""Segment ID: {segment_id}

EXPECTED (from annotation + audio_postprocess):
- Speaker: {annotation.speaker_canonical_name}
- Is Dialogue: {annotation.is_dialogue}
- Emotion: {annotation.emotion} (intensity: {annotation.emotion_intensity})
- Speech Rate: {audio_params.speech_rate}
- Pitch Shift: {audio_params.pitch_shift_semitones} semitones
- Pauses: before={annotation.pause_before_ms}ms, after={annotation.pause_after_ms}ms
- Reference Text: {reference_text[:500]}...

AUDIO ANALYSIS (simulated):
{audio_description}

EVALUATE AND OUTPUT QualityJudgment JSON with:
- speaker_clarity (0-1): Does the voice match the expected speaker?
- emotion_match (0-1): Does the emotional tone match the annotation?
- prosody_naturalness (0-1): Is the rhythm, stress, intonation natural?
- text_audio_alignment (0-1): Does the audio match the reference text?
- overall_score (0-1): Weighted composite
- issues: List of specific problems found
- fix_suggestions: Concrete suggestions for regeneration
- needs_regeneration: true if any dimension < 0.7 or fatal issue
"""

    def _log_judgment(self, segment_id: str, judgment: QualityJudgment):
        logger.info(
            f"Quality judgment [{segment_id}]: "
            f"overall={judgment.overall_score:.2f} "
            f"speaker={judgment.speaker_clarity:.2f} "
            f"emotion={judgment.emotion_match:.2f} "
            f"prosody={judgment.prosody_naturalness:.2f} "
            f"alignment={judgment.text_audio_alignment:.2f} "
            f"needs_regeneration={judgment.needs_regeneration} "
            f"issues={judgment.issues}"
        )


def create_judge(router: Optional[LLMRouter] = None) -> LLMJudge:
    return LLMJudge(router=router)
