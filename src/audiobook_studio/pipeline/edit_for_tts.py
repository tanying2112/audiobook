"""Pipeline Stage 4: Edit for TTS - Text editing for TTS synthesis.

Applies difficulty-based editing rules: sentence splitting, number normalization,
punctuation cleanup, dialogue preservation. Outputs TtsEditOutput.
"""

import json
import logging
import os
from pathlib import Path
from typing import Literal, Optional, Union, cast

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..llm import LLMRouter, create_router
from ..pipeline.progress_emitter import emit_stage_enter, emit_stage_exit, emit_stage_progress
from ..schemas import ParagraphAnnotation, TtsEditInput, TtsEditOutput

logger = logging.getLogger(__name__)


class EditForTtsPipeline:
    """Pipeline for text editing for TTS."""

    def __init__(
        self,
        router: Optional[LLMRouter] = None,
        prompt_dir: Optional[Union[str, Path]] = None,
        mock_mode: Optional[bool] = None,
    ):
        self.mock_mode = mock_mode if mock_mode is not None else os.environ.get("MOCK_LLM", "false").lower() == "true"

        # Create router (mock mode passed directly to avoid thread-unsafe env manipulation)
        if router is None:
            self.router = create_router(mock_mode=self.mock_mode)
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

    def _load_few_shot(self, stage: str) -> str:
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
            formatted.append(f"输入：{json.dumps(ex['input'], ensure_ascii=False, indent=2)[:2000]}...\n")
            formatted.append(f"期望输出：{json.dumps(ex['expected_output'], ensure_ascii=False, indent=2)[:3000]}...\n")
        return "\n".join(formatted)

    def _build_prompt(self, input_data: TtsEditInput) -> str:
        template = self.jinja_env.get_template("edit_for_tts/v1.j2")
        schema_json = TtsEditOutput.model_json_schema()
        few_shot = self._load_few_shot("edit_for_tts")

        return template.render(
            schema_json=schema_json,
            paragraph_text=input_data.paragraph_text,
            paragraph_annotation=input_data.paragraph_annotation.model_dump(),
            difficulty=input_data.difficulty,
            forbid_edit=input_data.forbid_edit,
            few_shot_examples=few_shot,
        )

    def run(self, input_data: TtsEditInput) -> TtsEditOutput:
        logger.info(
            f"Editing paragraph {input_data.paragraph_annotation.paragraph_index} for TTS (difficulty={input_data.difficulty})"
        )

        # Emit stage enter
        try:
            import asyncio

            loop = asyncio.get_running_loop()
            loop.create_task(
                emit_stage_enter(
                    stage="edit",
                    project_id=getattr(input_data, "project_id", 0) or 0,
                    chapter_index=getattr(input_data.paragraph_annotation, "chapter_index", 1),
                    paragraph_index=getattr(input_data.paragraph_annotation, "paragraph_index", 1),
                    total_items=1,
                )
            )
        except RuntimeError:
            pass

        # Hard rule: difficulty A or forbid_edit -> return original (checked BEFORE mock_mode)
        if input_data.difficulty == "A" or input_data.forbid_edit:
            return TtsEditOutput(
                edited_text=input_data.paragraph_text,
                changes_made=["difficulty_A_or_forbid_edit_preserved_original"],
                forbidden_content_removed=[],
                confidence=1.0,
                rationale="Difficulty A or forbid_edit=true: preserved original text per hard rule",
            )

        # MOCK: 待真实实现
        # Mock mode: return original text without LLM call
        if self.mock_mode:
            return TtsEditOutput(
                edited_text=input_data.paragraph_text,
                changes_made=["mock_mode_no_changes"],
                forbidden_content_removed=[],
                confidence=0.9,
                rationale="Mock mode: no LLM call made",
            )

        # Emit stage progress
        try:
            import asyncio

            loop = asyncio.get_running_loop()
            loop.create_task(
                emit_stage_progress(
                    stage="edit",
                    project_id=getattr(input_data, "project_id", 0) or 0,
                    chapter_index=getattr(input_data.paragraph_annotation, "chapter_index", 1),
                    paragraph_index=getattr(input_data.paragraph_annotation, "paragraph_index", 1),
                    current=1,
                    total=1,
                    message="Editing text for TTS...",
                )
            )
        except RuntimeError:
            pass

        prompt = self._build_prompt(input_data)
        messages = [
            {
                "role": "system",
                "content": "你是专业的 TTS 文本编辑师。按难度规则编辑文本，严格按 JSON Schema 输出。",
            },
            {"role": "user", "content": prompt},
        ]

        try:
            result = self.router.call(
                stage="edit",
                response_model=TtsEditOutput,
                messages=messages,
            )
            logger.info(
                f"TTS edit completed: schema_compliance={result.schema_compliance}, "
                f"model={result.model}, cost=${result.cost_usd:.6f}, latency={result.latency_ms}ms"
            )

            # Record performance to monitoring system
            from ..monitoring import record_stage_performance

            record_stage_performance(
                stage="edit_for_tts",
                latency_ms=result.latency_ms,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                cost_usd=result.cost_usd,
                success=True,
                provider=(result.model.split("/")[0] if "/" in result.model else result.model),
                model=result.model,
                difficulty=input_data.difficulty,
            )

            # ``router.call`` returns ``Any`` (its signature predates generics);
            # it was invoked with ``response_model=TtsEditOutput``, so narrow the
            # already-validated output to the declared return type.
            # Emit stage exit (success)
            try:
                import asyncio

                loop = asyncio.get_running_loop()
                loop.create_task(
                    emit_stage_exit(
                        stage="edit",
                        project_id=getattr(input_data, "project_id", 0) or 0,
                        chapter_index=getattr(input_data.paragraph_annotation, "chapter_index", 1),
                        paragraph_index=getattr(input_data.paragraph_annotation, "paragraph_index", 1),
                        success=True,
                    )
                )
            except RuntimeError:
                pass

            return cast(TtsEditOutput, result.output)
        except (ValueError, RuntimeError, ConnectionError, TimeoutError) as e:
            # Emit stage exit (error)
            try:
                import asyncio

                loop = asyncio.get_running_loop()
                loop.create_task(
                    emit_stage_exit(
                        stage="edit",
                        project_id=getattr(input_data, "project_id", 0) or 0,
                        chapter_index=getattr(input_data.paragraph_annotation, "chapter_index", 1),
                        paragraph_index=getattr(input_data.paragraph_annotation, "paragraph_index", 1),
                        success=False,
                        error_message=str(e),
                    )
                )
            except RuntimeError:
                pass
            # Record failed performance
            from ..monitoring import record_stage_performance

            record_stage_performance(
                stage="edit_for_tts",
                latency_ms=0,  # We don't have latency on failure
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                success=False,
                provider="unknown",
                model="unknown",
                difficulty=input_data.difficulty,
                error=str(e),
            )
            logger.error(f"TTS edit failed: {e}")
            raise


def edit_for_tts(
    paragraph_text: str,
    paragraph_annotation: ParagraphAnnotation,
    difficulty: Literal["A", "B", "C", "D"],
    forbid_edit: bool = False,
    mock_mode: bool = True,
) -> TtsEditOutput:
    input_data = TtsEditInput(
        paragraph_text=paragraph_text,
        paragraph_annotation=paragraph_annotation,
        difficulty=difficulty,
        forbid_edit=forbid_edit,
    )
    pipeline = EditForTtsPipeline(mock_mode=mock_mode)
    return pipeline.run(input_data)


if __name__ == "__main__":  # pragma: no cover

    logging.basicConfig(level=logging.INFO)
    logger.info("EditForTtsPipeline ready")
