"""LLM Judge - Quality evaluation using LLM-as-a-Judge pattern.

Implements pairwise comparison and scoring for quality gate.
"""

import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..schemas import (
    AudioPostProcessParams,
    FixSuggestion,
    PairwiseJudgment,
    ParagraphAnnotation,
    QualityJudgment,
)
from ..schemas.judge import PairwiseJudgment
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

        # Setup Jinja2 environment for pairwise prompt
        prompt_dir = Path(__file__).parent.parent.parent.parent / "prompts"
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(prompt_dir)),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.jinja_env.filters["tojson"] = json.dumps

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

    def judge_pairwise(
        self,
        segment_id: str,
        stage: str,
        reference_text: str,
        output_a: Dict[str, Any],
        output_b: Dict[str, Any],
        annotation: Optional[ParagraphAnnotation] = None,
        audio_description: Optional[str] = None,
    ) -> PairwiseJudgment:
        """Evaluate two outputs pairwise for A/B testing.

        Blind comparison: judge doesn't know which is control vs treatment.
        Returns structured PairwiseJudgment with winner, per-dimension scores, and reasoning.

        Args:
            segment_id: Segment identifier
            stage: Pipeline stage (edit_for_tts, annotate_paragraph, etc.)
            reference_text: Expected/reference text
            output_a: Version A output (dict)
            output_b: Version B output (dict)
            annotation: Optional paragraph annotation for context
            audio_description: Optional audio analysis description

        Returns:
            PairwiseJudgment with winner, confidence, dimension scores, reasoning
        """
        prompt = self._build_pairwise_prompt(
            segment_id=segment_id,
            stage=stage,
            reference_text=reference_text,
            output_a=output_a,
            output_b=output_b,
            annotation=annotation,
            audio_description=audio_description,
        )

        messages = [
            {"role": "system", "content": self._get_pairwise_system_prompt()},
            {"role": "user", "content": prompt},
        ]

        try:
            result = self.router.call(
                stage="judge",
                response_model=PairwiseJudgment,
                messages=messages,
                segment_id=segment_id,
            )
            judgment = result.output
            self._log_pairwise_judgment(segment_id, judgment)
            return judgment
        except Exception as e:
            logger.error(f"Pairwise judgment failed for {segment_id}: {e}")
            # Return safe default - tie with low confidence
            return PairwiseJudgment(
                segment_id=segment_id,
                winner="tie",
                confidence=0.5,
                dimension_scores={},
                reasoning={},
                overall_reasoning=f"Judge error: {str(e)}",
                statistical_significance=None,
                p_value=None,
                effect_size=None,
                judge_model=self.config.model,
                judge_prompt_version="pairwise_v1",
            )

    def _get_pairwise_system_prompt(self) -> str:
        return """You are an expert audiobook quality evaluator conducting blind A/B tests.
Compare two outputs for the same input without knowing which is control vs treatment.
Score each dimension for both versions (0.0-1.0), then determine overall winner.
Be strict but fair. Output ONLY valid JSON matching the schema."""

    def _build_pairwise_prompt(
        self,
        segment_id: str,
        stage: str,
        reference_text: str,
        output_a: Dict[str, Any],
        output_b: Dict[str, Any],
        annotation: Optional[ParagraphAnnotation],
        audio_description: Optional[str],
    ) -> str:
        template = self.jinja_env.get_template("quality_judge/pairwise_v1.j2")
        schema_json = PairwiseJudgment.model_json_schema()

        # Convert Pydantic model to dict for JSON serialization
        annotation_dict = None
        if annotation is not None:
            if hasattr(annotation, "model_dump"):
                annotation_dict = annotation.model_dump()
            elif hasattr(annotation, "dict"):
                annotation_dict = annotation.dict()
            else:
                annotation_dict = annotation

        return template.render(
            schema_json=schema_json,
            segment_id=segment_id,
            stage=stage,
            reference_text=reference_text,
            output_a=output_a,
            output_b=output_b,
            annotation=annotation_dict,
            audio_description=audio_description,
        )

    def _log_pairwise_judgment(self, segment_id: str, judgment: PairwiseJudgment):
        dim_str = ", ".join(
            f"{k}: A={v.score_a:.2f} B={v.score_b:.2f}" for k, v in judgment.dimension_scores.items()
        )
        logger.info(
            f"Pairwise judgment [{segment_id}]: "
            f"winner={judgment.winner} "
            f"confidence={judgment.confidence:.2f} "
            f"dims=[{dim_str}] "
            f"reasoning={judgment.overall_reasoning[:80]}"
        )


def create_judge(router: Optional[LLMRouter] = None) -> LLMJudge:
    return LLMJudge(router=router)
