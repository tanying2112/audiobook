"""Canary validation and stage execution for promotion gate.

包含：
- Stage name mappings
- Input conversion functions (_convert_input_to_model, _get_required_input_fields)
- Golden dataset loading (_load_golden_examples)
- Prompt version loading (_load_prompt_version)
- Stage runner (_run_stage_with_prompt_version)
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Stage name mapping: golden dataset dir -> pipeline stage ───────────────────

GOLDEN_TO_PIPELINE_STAGE = {
    "edit_for_tts": "edit",
    "annotate_paragraph": "annotate",
    "analyze_structure": "analyze",
    "extract": "extract",
    "quality_check": "quality",
    "synthesize": "synthesize",
    "quality_judge": "quality",
    "tts_routing": "synthesize",
}

# Reverse mapping: pipeline stage -> prompt directory name
PIPELINE_STAGE_TO_PROMPT_DIR = {
    "edit": "edit_for_tts",
    "annotate": "annotate_paragraph",
    "analyze": "analyze_structure",
    "extract": "extract",
    "quality": "quality_check",
    "synthesize": "synthesize",
}

# Stage type classification for quality metric selection
STAGE_TYPE = {
    "edit": "text_edit",
    "annotate": "text_annotation",
    "analyze": "structure_analysis",
    "extract": "extraction",
    "quality": "audio_quality",
    "synthesize": "audio_synthesis",
}


def _golden_to_pipeline_stage(stage: str) -> str:
    """Map golden dataset directory name to pipeline stage name."""
    return GOLDEN_TO_PIPELINE_STAGE.get(stage, stage)


def _pipeline_stage_to_prompt_dir(pipeline_stage: str) -> str:
    """Map pipeline stage name to prompt directory name."""
    return PIPELINE_STAGE_TO_PROMPT_DIR.get(pipeline_stage, pipeline_stage)


def _convert_input_to_model(pipeline_stage: str, input_dict: Dict[str, Any]) -> Any:
    """Convert input dict to the appropriate pipeline input model."""
    if pipeline_stage == "edit":
        from ..schemas.paragraph import ParagraphAnnotation
        from ..schemas.tts_edit import TtsEditInput

        # Convert paragraph_annotation dict to ParagraphAnnotation model
        if "paragraph_annotation" in input_dict and isinstance(input_dict["paragraph_annotation"], dict):
            input_dict = dict(input_dict)
            input_dict["paragraph_annotation"] = ParagraphAnnotation(**input_dict["paragraph_annotation"])
        return TtsEditInput(**input_dict)
    elif pipeline_stage == "annotate":
        from ..schemas.paragraph import ParagraphAnnotationInput

        return ParagraphAnnotationInput(**input_dict)
    elif pipeline_stage == "analyze":
        from ..schemas.book import BookAnalysisInput

        return BookAnalysisInput(**input_dict)
    elif pipeline_stage == "extract":
        from ..schemas.extraction import ExtractionInput

        return ExtractionInput(**input_dict)
    elif pipeline_stage == "quality":
        from ..schemas.quality import QualityJudgment

        return QualityJudgment(**input_dict)
    elif pipeline_stage == "synthesize":
        from ..schemas.tts_routing import TtsRoutingInput

        return TtsRoutingInput(**input_dict)
    else:
        # Return as-is for unknown stages
        return input_dict


def _get_required_input_fields(pipeline_stage: str) -> List[str]:
    """Get required input fields for a pipeline stage."""
    if pipeline_stage == "edit":
        return ["paragraph_text", "paragraph_annotation", "difficulty", "forbid_edit"]
    elif pipeline_stage == "annotate":
        return ["paragraph_text", "paragraph_index"]
    elif pipeline_stage == "analyze":
        return ["book_text", "book_meta"]
    elif pipeline_stage == "extract":
        return ["text"]
    elif pipeline_stage == "quality":
        return ["audio_path", "expected_text"]
    elif pipeline_stage == "synthesize":
        return ["text", "voice_id"]
    else:
        return []


# ── Self-iteration mock mode ───────────────────────────────────────────────────

SELF_ITERATION_MOCK_ENV = "SELF_ITERATION_MOCK"


def _self_iteration_mock_enabled() -> bool:
    return os.getenv(SELF_ITERATION_MOCK_ENV, "true").lower() not in ("false", "0", "no")


def _resolve_mock_mode(explicit: Optional[bool]) -> bool:
    """Resolve a mock_mode from an explicit arg, else from SELF_ITERATION_MOCK env."""
    if explicit is not None:
        return explicit
    return _self_iteration_mock_enabled()


def _load_golden_examples(stage: str, split: str = "train") -> List[Dict[str, Any]]:
    """加载黄金数据集，支持 split 参数 (train/val/test).

    新目录结构: data/golden/{split}/{stage}/*.jsonl
    兼容旧结构: tests/golden/{stage}/*.json, *.jsonl
    """
    examples: List[Dict[str, Any]] = []

    # Try new directory structure first
    new_golden_dir = Path("data/golden") / split / stage
    if new_golden_dir.exists():
        for f in sorted(new_golden_dir.glob("*.jsonl")):
            try:
                for line in f.read_text(encoding="utf-8").strip().split("\n"):
                    if line.strip():
                        examples.append(json.loads(line))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load golden JSONL {f}: {e}")
        if examples:
            return examples

    # Fallback to old directory structure
    old_golden_dir = Path("tests/golden") / stage
    if old_golden_dir.exists():
        # Load JSON files
        for f in sorted(old_golden_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                examples.append(data)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load golden example {f}: {e}")

        # Load JSONL files
        for f in sorted(old_golden_dir.glob("*.jsonl")):
            try:
                for line in f.read_text(encoding="utf-8").strip().split("\n"):
                    if line.strip():
                        examples.append(json.loads(line))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load golden JSONL {f}: {e}")

    if not examples:
        logger.warning(f"Golden dataset not found for stage={stage}, split={split}")

    return examples


def _load_prompt_version(stage: str, version: int) -> Optional[str]:
    """加载指定版本的 prompt."""
    prompt_path = Path("prompts") / stage / f"v{version}.j2"
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    return None


def _run_stage_with_prompt_version(
    pipeline_stage: str,
    version: int,
    input_data: Any,
    mock_mode: Optional[bool] = None,
) -> Any:
    """Run a specific pipeline stage with a specific prompt version.

    This temporarily swaps the v1.j2 template with the specified version,
    runs the pipeline, then restores the original.

    Args:
        pipeline_stage: Short pipeline stage name (edit, annotate, analyze, etc.)
        version: Prompt version number
        input_data: Input data for the pipeline (dict or model object)
        mock_mode: Whether to run in mock mode (None = resolve from
            SELF_ITERATION_MOCK env, C-01).
    """
    mock_mode = _resolve_mock_mode(mock_mode)

    # Explicit, auditable record of whether this self-iteration cycle hits
    # the live LLM provider or runs as a mock (S2-1 / C-01). This is the
    # single choke point through which canary validation and A/B pipeline
    # re-runs execute, so the record is unambiguous and grep-able.
    env_val = os.getenv(SELF_ITERATION_MOCK_ENV)
    if mock_mode:
        logger.info(
            f"[SelfIteration] MOCK run — stage={pipeline_stage} version={version} "
            f"(SELF_ITERATION_MOCK={env_val!r}); no live LLM provider calls"
        )
    else:
        logger.info(
            f"[SelfIteration] \ud83d\udd34 REAL-LLM run — invoking live LLM provider for "
            f"stage={pipeline_stage} with prompt version={version} "
            f"(SELF_ITERATION_MOCK={env_val!r})"
        )

    # Convert dict input to appropriate model if needed
    if isinstance(input_data, dict):
        input_data = _convert_input_to_model(pipeline_stage, input_data)

    # Map pipeline stage to prompt directory name
    prompt_dir_name = _pipeline_stage_to_prompt_dir(pipeline_stage)
    prompt_dir = Path("prompts") / prompt_dir_name
    v1_path = prompt_dir / "v1.j2"
    target_path = prompt_dir / f"v{version}.j2"

    if not target_path.exists():
        raise FileNotFoundError(f"Prompt version {version} not found for stage {prompt_dir_name}")

    # Backup original v1.j2
    v1_backup = v1_path.read_text(encoding="utf-8") if v1_path.exists() else None

    try:
        # Copy target version to v1.j2
        target_content = target_path.read_text(encoding="utf-8")
        v1_path.write_text(target_content, encoding="utf-8")

        # Run the stage with the new prompt
        pipeline: Any = None
        if pipeline_stage == "edit":
            from ..pipeline.edit_for_tts import EditForTtsPipeline

            pipeline = EditForTtsPipeline(mock_mode=mock_mode)
            return pipeline.run(input_data)
        elif pipeline_stage == "annotate":
            from ..pipeline.annotate_paragraph import AnnotateParagraphPipeline

            pipeline = AnnotateParagraphPipeline(mock_mode=mock_mode)
            return pipeline.run(input_data)
        elif pipeline_stage == "analyze":
            from ..pipeline.analyze_structure import AnalyzeStructurePipeline

            pipeline = AnalyzeStructurePipeline(mock_mode=mock_mode)
            return pipeline.run(input_data)
        elif pipeline_stage == "extract":
            from ..pipeline.extract import ExtractPipeline

            pipeline = ExtractPipeline(mock_mode=mock_mode)
            return pipeline.run(input_data)
        elif pipeline_stage == "quality":
            from ..pipeline.quality_check import QualityCheckPipeline

            pipeline = QualityCheckPipeline(mock_mode=mock_mode)
            return pipeline.run(input_data)
        elif pipeline_stage == "synthesize":
            from ..pipeline.synthesize import SynthesizePipeline

            pipeline = SynthesizePipeline(mock_mode=mock_mode)
            return pipeline.run(input_data)
        else:
            raise ValueError(f"Unknown pipeline stage: {pipeline_stage}")
    finally:
        # Restore original v1.j2
        if v1_backup is not None:
            v1_path.write_text(v1_backup, encoding="utf-8")
        elif v1_path.exists():
            v1_path.unlink()
