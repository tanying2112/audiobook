"""
StructuralCritic (结构派) - 文档结构、章节边界、段落流程、成本约束批评器.

基于规则与 LLM 混合评估音频的结构层面质量：
- 文档结构完整性：章节划分、段落边界、层级关系
- 段落流程连贯性：前后段落衔接、过渡自然度、断点检测
- 成本约束合规：TTS 成本是否在预算内、引擎选择合理性
- 格式规范性：音频片段命名、元数据完整性、契约版本对齐
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ...schemas import ParagraphAnnotation, TtsRoutingDecision
from .base import BaseCritic, CriticResult, CriticType, CriticVerdict

logger = logging.getLogger(__name__)


class StructuralCritic(BaseCritic):
    """结构派批评器.

    评估维度：
    1. document_structure - 文档结构：章节/段落层级、边界完整性
    2. paragraph_flow - 段落流程：前后衔接、过渡自然度、断点
    3. cost_compliance - 成本合规：预算内、引擎选择、成本估算准确
    4. format_compliance - 格式规范：命名、元数据、契约版本
    """

    def __init__(
        self,
        router=None,
        config: Optional[Dict[str, Any]] = None,
        prompt_dir: Optional[str] = None,
    ):
        super().__init__(CriticType.STRUCTURAL, router, config)

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

        # Structural-specific thresholds
        self.boundary_tolerance = self.config.get("boundary_tolerance", 0.1)  # 10% boundary deviation tolerance
        self.cost_tolerance = self.config.get("cost_tolerance", 0.2)  # 20% cost deviation tolerance
        self.min_flow_score = self.config.get("min_flow_score", 0.6)

    def evaluate(
        self,
        audio_path: Path,
        annotation: ParagraphAnnotation,
        routing_decision: TtsRoutingDecision,
        reference_text: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> CriticResult:
        """评估结构质量."""
        prompt = self._build_prompt(audio_path, annotation, routing_decision, reference_text, context)

        messages = [
            {
                "role": "system",
                "content": self._build_base_prompt(
                    "评估音频的结构质量：文档结构完整性、段落流程连贯性、成本约束合规、格式规范性。"
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
            critic_result.critic_type = CriticType.STRUCTURAL
            logger.info(
                f"StructuralCritic: verdict={critic_result.verdict.value}, "
                f"score={critic_result.score:.2f}, confidence={critic_result.confidence:.2f}"
            )
            return critic_result
        except Exception as e:
            logger.error(f"StructuralCritic LLM call failed: {e}")
            raise

    def _build_prompt(
        self,
        audio_path: Path,
        annotation: ParagraphAnnotation,
        routing_decision: TtsRoutingDecision,
        reference_text: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """构建结构评估提示词."""
        template = self.jinja_env.get_template("critics/structural_critic/v1.j2")

        # Prepare context data
        prev_paragraph = {}
        next_paragraph = {}
        chapter_boundary_info = ""
        cost_context = {}
        document_structure = {}

        if context:
            prev_paragraph = context.get("prev_paragraph", {})
            next_paragraph = context.get("next_paragraph", {})
            chapter_boundary_info = context.get("chapter_boundary_info", "")
            cost_context = context.get("cost_context", {})
            document_structure = context.get("document_structure", {})

        return template.render(
            # Segment info
            segment_id=Path(audio_path).stem,
            speaker=annotation.speaker_canonical_name,
            is_dialogue=annotation.is_dialogue,
            paragraph_index=annotation.paragraph_index,
            chapter_index=context.get("chapter_index", 1) if context else 1,

            # Reference text
            reference_text=reference_text,

            # Context: adjacent paragraphs
            prev_text=prev_paragraph.get("text", "（无前段）")[:500],
            prev_speaker=prev_paragraph.get("speaker", ""),
            prev_is_dialogue=prev_paragraph.get("is_dialogue", False),
            next_text=next_paragraph.get("text", "（无后段）")[:500],
            next_speaker=next_paragraph.get("speaker", ""),
            next_is_dialogue=next_paragraph.get("is_dialogue", False),

            # Chapter boundary
            chapter_boundary_info=chapter_boundary_info or "（非章节边界）",
            is_chapter_start=context.get("is_chapter_start", False) if context else False,
            is_chapter_end=context.get("is_chapter_end", False) if context else False,

            # Document structure
            total_chapters=document_structure.get("total_chapters", 0),
            total_paragraphs=document_structure.get("total_paragraphs", 0),
            current_chapter_paragraphs=document_structure.get("current_chapter_paragraphs", 0),

            # Cost context
            cumulative_cost=cost_context.get("cumulative_cost_usd", 0.0),
            cost_limit_per_book=cost_context.get("cost_limit_per_book", 20.0),
            cost_limit_per_chapter=cost_context.get("cost_limit_per_chapter", 5.0),
            estimated_cost=routing_decision.estimated_cost_usd,
            engine_choice=routing_decision.engine_choice,
            fallback_engine=routing_decision.fallback_engine,

            # Format compliance
            segment_id_format=routing_decision.segment_id,
            contract_version=routing_decision.contract_version,

            # Thresholds
            pass_threshold=self.pass_threshold,
            warning_threshold=self.warning_threshold,
            boundary_tolerance=self.boundary_tolerance,
            cost_tolerance=self.cost_tolerance,
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
        score = 0.75
        confidence = 0.8
        verdict = self._determine_verdict(score)

        reasoning = "[Mock] 文档结构完整，段落流程基本连贯，成本在预算内，格式规范"
        evidence = {
            "document_structure": 0.85,
            "paragraph_flow": 0.7,
            "cost_compliance": 0.9,
            "format_compliance": 0.8,
        }
        tags = []

        # Check for structural issues in mock
        if context:
            if context.get("is_chapter_start") and annotation.paragraph_index != 0:
                tags.append("chapter_boundary_mismatch")
                score -= 0.15
            cc = context.get("cost_context", {})
            if cc.get("cumulative_cost_usd", 0) > cc.get("cost_limit_per_book", 20):
                tags.append("cost_overrun")
                score -= 0.2

        verdict = self._determine_verdict(score)

        return CriticResult(
            critic_type=CriticType.STRUCTURAL,
            verdict=verdict,
            score=max(0.0, score),
            confidence=confidence,
            reasoning=reasoning,
            evidence=evidence,
            tags=tags,
        )


# Register template
__all__ = ["StructuralCritic"]
