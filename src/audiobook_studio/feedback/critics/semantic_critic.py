"""
SemanticCritic (语义派) - 语义连贯性、情感一致性、角色声音指纹批评器.

基于 LLM-as-a-Judge 评估音频的语义层面质量：
- 语义连贯性：上下文语义是否连贯，是否存在逻辑跳跃
- 情感一致性：音频情感表达与标注要求是否一致
- 角色声音指纹：说话人声音特征是否与角色档案匹配
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ...schemas import FeedbackAnalysis, ParagraphAnnotation, TtsRoutingDecision
from .base import BaseCritic, CriticResult, CriticType, CriticVerdict

logger = logging.getLogger(__name__)


class SemanticCritic(BaseCritic):
    """语义派批评器.
    
    评估维度：
    1. semantic_coherence - 语义连贯性：前后文语义衔接是否自然
    2. emotion_consistency - 情感一致性：实际情感与标注是否匹配
    3. speaker_fingerprint - 角色声音指纹：说话人声音特征是否符合角色档案
    """
    
    def __init__(
        self,
        router=None,
        config: Optional[Dict[str, Any]] = None,
        prompt_dir: Optional[str] = None,
    ):
        super().__init__(CriticType.SEMANTIC, router, config)
        
        # Setup Jinja2 environment
        if prompt_dir is None:
            prompt_dir = Path(__file__).parent.parent.parent.parent / "prompts"
        self.prompt_dir = Path(prompt_dir)
        
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(self.prompt_dir)),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.jinja_env.filters["tojson"] = json.dumps
    
    def evaluate(
        self,
        audio_path: Path,
        annotation: ParagraphAnnotation,
        routing_decision: TtsRoutingDecision,
        reference_text: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> CriticResult:
        """评估语义质量."""
        prompt = self._build_prompt(audio_path, annotation, routing_decision, reference_text, context)
        
        messages = [
            {
                "role": "system",
                "content": self._build_base_prompt(
                    "评估音频的语义质量：语义连贯性、情感一致性、角色声音指纹。"
                    "输出严格符合 CriticResult JSON 结构。"
                ),
            },
            {"role": "user", "content": prompt},
        ]
        
        try:
            result = self.router.call(
                stage="judge",
                response_model=CriticResult,
                messages=messages,
            )
            critic_result = result.output
            # Ensure critic_type is set correctly
            critic_result.critic_type = CriticType.SEMANTIC
            logger.info(
                f"SemanticCritic: verdict={critic_result.verdict.value}, "
                f"score={critic_result.score:.2f}, confidence={critic_result.confidence:.2f}"
            )
            return critic_result
        except Exception as e:
            logger.error(f"SemanticCritic LLM call failed: {e}")
            raise
    
    def _build_prompt(
        self,
        audio_path: Path,
        annotation: ParagraphAnnotation,
        routing_decision: TtsRoutingDecision,
        reference_text: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """构建语义评估提示词."""
        template = self.jinja_env.get_template("critics/semantic_critic/v1.j2")
        
        # Prepare context data
        prev_text = ""
        next_text = ""
        prev_emotion = ""
        next_emotion = ""
        chapter_info = ""
        
        if context:
            prev_text = context.get("prev_text", "")
            next_text = context.get("next_text", "")
            prev_emotion = context.get("prev_emotion", "")
            next_emotion = context.get("next_emotion", "")
            chapter_info = context.get("chapter_info", "")
        
        # Build character voice profile
        char_voice_profile = {}
        if context and "character_profiles" in context:
            for char in context["character_profiles"]:
                char_voice_profile[char.get("canonical_name", "")] = {
                    "voice_id": char.get("suggested_voice_id", ""),
                    "description": char.get("语音描述", char.get("voice_description", "")),
                    "gender": char.get("gender", ""),
                    "age_group": char.get("age_group", ""),
                }
        
        return template.render(
            # Segment info
            segment_id=Path(audio_path).stem,
            speaker=annotation.speaker_canonical_name,
            is_dialogue=annotation.is_dialogue,
            expected_emotion=annotation.emotion,
            emotion_intensity=annotation.emotion_intensity,
            expected_speech_rate=annotation.speech_rate,
            expected_pitch_shift=annotation.pitch_shift_semitones,
            
            # Reference text
            reference_text=reference_text,
            
            # Context
            prev_text=prev_text[:500] if prev_text else "（无前文）",
            next_text=next_text[:500] if next_text else "（无后文）",
            prev_emotion=prev_emotion,
            next_emotion=next_emotion,
            chapter_info=chapter_info,
            
            # Character voice profiles
            character_voice_profiles=char_voice_profile,
            
            # Routing info
            selected_voice=routing_decision.voice_id,
            selected_model=routing_decision.engine_choice,
            voice_instructions=routing_decision.prosody_overrides or {},
            
            # Thresholds
            pass_threshold=self.pass_threshold,
            warning_threshold=self.warning_threshold,
        )
    
    def _evaluate_mock(
        self,
        audio_path: Path,
        annotation: ParagraphAnnotation,
        routing_decision: TtsRoutingDecision,
        reference_text: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> CriticResult:
        """Mock 模式评估（用于测试）."""
        # Simulate semantic analysis
        score = 0.85
        confidence = 0.9
        verdict = self._determine_verdict(score)
        
        reasoning = "[Mock] 语义连贯性良好，情感表达与标注一致，角色声音特征匹配"
        evidence = {
            "semantic_coherence": 0.88,
            "emotion_consistency": 0.92,
            "speaker_fingerprint": 0.85,
        }
        tags = []
        
        return CriticResult(
            critic_type=CriticType.SEMANTIC,
            verdict=verdict,
            score=score,
            confidence=confidence,
            reasoning=reasoning,
            evidence=evidence,
            tags=tags,
        )


# Register template
__all__ = ["SemanticCritic"]
