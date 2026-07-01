"""Pipeline Stage 3: Annotate Paragraph - Paragraph-level annotation with God's Eye Context.

Injects BookAnalysisOutput as context, processes each paragraph to generate
ParagraphAnnotation with speaker, emotion, prosody, and SFX tags.
"""

import json
import logging
import os
from pathlib import Path
from typing import List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..llm import LLMRouter, create_router
from ..schemas import BookAnalysisOutput, ParagraphAnnotation, ParagraphAnnotationInput

logger = logging.getLogger(__name__)


class AnnotateParagraphPipeline:
    """Pipeline for paragraph-level annotation."""

    def __init__(
        self,
        router=None,
        prompt_dir=None,
        mock_mode: Optional[bool] = None,
    ):
        self.mock_mode = (
            mock_mode
            if mock_mode is not None
            else os.environ.get("MOCK_LLM", "false").lower() == "true"
        )

        # Create router (mock mode passed directly to avoid thread-unsafe env manipulation)
        if router is None:
            self.router = create_router(mock_mode=mock_mode or False)
        else:
            self.router = router

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

    def _load_few_shot(self, stage):
        examples_path = self.prompt_dir / stage / "few_shot.jsonl"
        if not examples_path.exists():
            return "(暂无示例)"
        examples = []
        with open(examples_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    examples.append(json.loads(line))
        formatted = []
        for i, ex in enumerate(examples[:3], 1):
            formatted.append(f"### 示例 {i}\n")
            formatted.append(
                f"输入：{json.dumps(ex['input'], ensure_ascii=False, indent=2)[:2000]}...\n"
            )
            formatted.append(
                f"期望输出：{json.dumps(ex['expected_output'], ensure_ascii=False, indent=2)[:3000]}...\n"
            )
        return "\n".join(formatted)

    def _build_prompt(self, input_data):
        template = self.jinja_env.get_template("annotate_paragraph/v1.j2")
        schema_json = ParagraphAnnotation.model_json_schema()
        few_shot = self._load_few_shot("annotate_paragraph")

        return template.render(
            schema_json=schema_json,
            paragraph_text=input_data.paragraph_text,
            paragraph_index=input_data.paragraph_index,
            chapter_index=input_data.chapter_index,
            book_meta=input_data.book_meta.model_dump(),
            character_voice_map=[
                c.model_dump() for c in input_data.character_voice_map
            ],
            emotion_snapshot=input_data.emotion_snapshot.model_dump(),
            story_line_summary=input_data.story_line_summary,
            global_style_notes=input_data.global_style_notes,
            few_shot_examples=few_shot,
        )

    def run(self, input_data):
        logger.info(
            f"Annotating paragraph {input_data.paragraph_index} (ch{input_data.chapter_index})"
        )

        # MOCK: 待真实实现
        # Mock mode: return simulated annotation
        if self.mock_mode:
            return ParagraphAnnotation(
                paragraph_index=input_data.paragraph_index,
                speaker_canonical_name="旁白",
                is_dialogue=False,
                emotion="neutral",
                emotion_intensity=0.5,
                speech_rate=1.0,
                pitch_shift_semitones=0,
                pause_before_ms=300,
                pause_after_ms=500,
                confidence=0.9,
                difficulty="B",
                needs_sfx=False,
                sfx_tags=[],
                notes="Mock annotation for testing",
            )

        prompt = self._build_prompt(input_data)
        messages = [
            {
                "role": "system",
                "content": "你是专业的有声书段落标注师。请严格按照 JSON Schema 输出标注结果。",
            },
            {"role": "user", "content": prompt},
        ]

        try:
            result = self.router.call(
                stage="annotate",
                response_model=ParagraphAnnotation,
                messages=messages,
            )
            logger.info(
                f"Paragraph annotation completed: schema_compliance={result.schema_compliance}, "
                f"model={result.model}, cost=${result.cost_usd:.6f}, latency={result.latency_ms}ms"
            )

            # Record performance to monitoring system
            from ..monitoring import record_stage_performance

            # Try to get difficulty from input_data if available (it should be in book_meta)
            difficulty = None
            if hasattr(input_data, "book_meta") and input_data.book_meta:
                difficulty = getattr(input_data.book_meta, "difficulty", None)

            record_stage_performance(
                stage="annotate_paragraph",
                latency_ms=result.latency_ms,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                cost_usd=result.cost_usd,
                success=True,
                provider=(
                    result.model.split("/")[0] if "/" in result.model else result.model
                ),
                model=result.model,
                difficulty=difficulty,
                schema_compliance=result.schema_compliance,
            )

            return result.output
        except Exception as e:
            # Record failed performance
            from ..monitoring import record_stage_performance

            # Try to get difficulty from input_data if available
            difficulty = None
            if hasattr(input_data, "book_meta") and input_data.book_meta:
                difficulty = getattr(input_data.book_meta, "difficulty", None)

            record_stage_performance(
                stage="annotate_paragraph",
                latency_ms=0,  # We don't have latency on failure
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                success=False,
                provider="unknown",
                model="unknown",
                difficulty=difficulty,
                schema_compliance=False,
                error=str(e),
            )
            logger.error(f"Paragraph annotation failed: {e}")
            raise


def annotate_paragraph(
    paragraph_text,
    paragraph_index,
    chapter_index,
    book_meta,
    character_voice_map,
    emotion_snapshot,
    story_line_summary,
    global_style_notes,
    mock_mode: bool = True,
):
    input_data = ParagraphAnnotationInput(
        paragraph_text=paragraph_text,
        paragraph_index=paragraph_index,
        chapter_index=chapter_index,
        book_meta=book_meta,
        character_voice_map=character_voice_map,
        emotion_snapshot=emotion_snapshot,
        story_line_summary=story_line_summary,
        global_style_notes=global_style_notes,
    )
    pipeline = AnnotateParagraphPipeline(mock_mode=mock_mode)
    return pipeline.run(input_data)


if __name__ == "__main__":  # pragma: no cover
    import sys

    logging.basicConfig(level=logging.INFO)
    logger.info("AnnotateParagraphPipeline ready")
