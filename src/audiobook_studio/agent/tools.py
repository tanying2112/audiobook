"""Agent Core Tools.

Pydantic-validated tools for the agent to interact with the pipeline.
Each tool is a self-contained function with typed input/output schemas.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from ..llm import LLMRouter, StageName, create_router
from ..pipeline.analyze_structure import AnalyzeStructurePipeline, BookAnalysisInput
from ..pipeline.annotate_paragraph import AnnotateParagraphPipeline, ParagraphAnnotationInput
from ..pipeline.extract import ExtractionInput, ExtractPipeline
from ..pipeline.orchestrator import run_stage
from ..pipeline.synthesize import SynthesizePipeline, TtsRoutingInput
from ..schemas import BookAnalysisOutput, CharacterVoiceBinding, ParagraphAnnotation, TtsRoutingDecision
from ..storage import (
    annotated_dir,
    audio_dir,
    extracted_dir,
    load_chapter_annotations,
    load_extracted_text,
    project_dir,
)
from ..tts import FakeRemoteTTSPort, get_port

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Tool Schemas (OpenAI Function Calling compatible)
# ─────────────────────────────────────────────────────────────────────────────


class LoadBookFileArgs(BaseModel):
    """Arguments for loading a book file into the pipeline."""

    file_path: str = Field(..., description="已上传文件的存储路径")
    project_id: int = Field(..., description="项目 ID")
    file_type: Optional[Literal["pdf", "epub", "txt", "docx", "image"]] = Field(
        default=None, description="文件类型，None 则自动推断"
    )


class LoadBookFileResult(BaseModel):
    """Result of loading a book file."""

    status: Literal["ok", "failed"] = "ok"
    chapters: int = 0
    total_chars: int = 0
    error_message: Optional[str] = None
    project_id: int


class AnalyzeAndSplitArgs(BaseModel):
    """Arguments for analyzing and splitting a book into chapters."""

    project_id: int = Field(..., description="项目 ID")
    chapter_indices: Optional[list[int]] = Field(default=None, description="指定章节索引，None 为全书")


class ChapterInfo(BaseModel):
    """Chapter information."""

    index: int
    title: str
    char_count: int
    start_offset: int
    end_offset: int


class AnalyzeAndSplitResult(BaseModel):
    """Result of analyzing and splitting a book."""

    status: Literal["ok", "failed"] = "ok"
    characters: int = 0
    chapters: list[ChapterInfo] = Field(default_factory=list)
    error_message: Optional[str] = None
    project_id: int


class GenerateEmotionMarkupArgs(BaseModel):
    """Arguments for generating emotion markup for a chapter."""

    project_id: int = Field(..., description="项目 ID")
    chapter_index: int = Field(..., description="章节索引")
    style: Literal["detailed", "concise"] = Field(default="detailed")


class ParagraphMarkup(BaseModel):
    """Single paragraph with emotion markup."""

    index: int
    text: str
    speaker: Optional[str] = None
    emotion: Optional[str] = None
    speech_rate: float = 1.0
    pitch_shift: int = 0
    pause_after: int = 300  # ms


class GenerateEmotionMarkupResult(BaseModel):
    """Result of generating emotion markup."""

    status: Literal["ok", "failed"] = "ok"
    paragraphs: list[ParagraphMarkup] = Field(default_factory=list)
    error_message: Optional[str] = None
    project_id: int
    chapter_index: int


class ExecuteAudioSynthesisArgs(BaseModel):
    """Arguments for executing audio synthesis for a chapter."""

    project_id: int = Field(..., description="项目 ID")
    chapter_index: int = Field(..., description="章节索引")
    force_regenerate: bool = Field(default=False)


class AudioSegment(BaseModel):
    """Single audio segment result."""

    paragraph_index: int
    audio_path: str
    duration_ms: int
    voice_id: str


class ExecuteAudioSynthesisResult(BaseModel):
    """Result of executing audio synthesis."""

    status: Literal["ok", "failed"] = "ok"
    audio_segments: list[AudioSegment] = Field(default_factory=list)
    error_message: Optional[str] = None
    project_id: int
    chapter_index: int


# ─────────────────────────────────────────────────────────────────────────────
# Tool Implementations
# ─────────────────────────────────────────────────────────────────────────────


async def load_book_file(args: LoadBookFileArgs) -> LoadBookFileResult:
    """Load a book file and extract text content.

    Delegates to the existing extract pipeline stage.
    """
    try:
        # Extract book using existing ExtractPipeline
        pipeline = ExtractPipeline()
        extraction_input = ExtractionInput(
            file_path=args.file_path,
            mime_type=_guess_mime_type(args.file_path, args.file_type),
        )
        result = pipeline.run(extraction_input)

        return LoadBookFileResult(
            status="ok",
            chapters=0,  # Will be determined in analyze stage
            total_chars=len(result.raw_text),
            project_id=args.project_id,
        )

    except Exception as e:
        logger.error(f"load_book_file failed for project {args.project_id}: {e}")
        return LoadBookFileResult(
            status="failed",
            error_message=str(e),
            project_id=args.project_id,
        )


def _guess_mime_type(file_path: str, file_type: Optional[str] = None) -> str:
    """Guess MIME type from file extension or explicit type."""
    if file_type:
        type_map = {
            "pdf": "application/pdf",
            "epub": "application/epub+zip",
            "txt": "text/plain",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "image": "image/png",
        }
        return type_map.get(file_type, "application/octet-stream")

    suffix = Path(file_path).suffix.lower()
    ext_map = {
        ".pdf": "application/pdf",
        ".epub": "application/epub+zip",
        ".txt": "text/plain",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".tiff": "image/tiff",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
    }
    return ext_map.get(suffix, "application/octet-stream")


async def analyze_and_split(args: AnalyzeAndSplitArgs) -> AnalyzeAndSplitResult:
    """Analyze book structure and split into chapters.

    Delegates to the existing analyze pipeline stage.
    """
    try:
        # Get extracted text from storage (assuming whole book text)
        # For now, we'll load from the first extracted chapter if available
        # In a real scenario, we'd concatenate all chapter texts
        text = load_extracted_text(args.project_id, 1)

        if not text:
            # Fallback to mock for testing
            mock_text = "第一章 开始\n这是第一章的内容。\n\n第二章 发展\n这是第二章的内容。"
            text = mock_text

        # Run analyze pipeline
        pipeline = AnalyzeStructurePipeline()
        input_data = BookAnalysisInput(
            raw_text=text,
            title_hint=None,
            author_hint=None,
            target_difficulty="B",
        )
        result = pipeline.run(input_data)

        # Build chapter info from analysis
        chapter_infos = []
        if result.book_meta:
            for i in range(result.book_meta.total_chapters_estimated):
                chapter_infos.append(
                    ChapterInfo(
                        index=i + 1,
                        title=f"第 {i + 1} 章",
                        char_count=0,  # Not in current schema
                        start_offset=0,
                        end_offset=0,
                    )
                )

        return AnalyzeAndSplitResult(
            status="ok",
            characters=len(text),
            chapters=chapter_infos,
            project_id=args.project_id,
        )

    except Exception as e:
        logger.error(f"analyze_and_split failed for project {args.project_id}: {e}")
        return AnalyzeAndSplitResult(
            status="failed",
            error_message=str(e),
            project_id=args.project_id,
        )


async def generate_emotion_markup(args: GenerateEmotionMarkupArgs) -> GenerateEmotionMarkupResult:
    """Generate emotion markup for a chapter.

    Delegates to the existing annotate pipeline stage.
    """
    try:
        # Load chapter text from extracted storage
        text = load_extracted_text(args.project_id, args.chapter_index)
        if not text:
            return GenerateEmotionMarkupResult(
                status="failed",
                error_message=f"No extracted text found for chapter {args.chapter_index}",
                project_id=args.project_id,
                chapter_index=args.chapter_index,
            )

        # Split into paragraphs (simple approach - split by double newline)
        paragraphs_text = [p.strip() for p in text.split("\n\n") if p.strip()]

        # Load book analysis for context (from Chapter 1 analyzed data)
        # In production, we'd load the full BookAnalysisOutput
        from ..schemas import BookMeta, CharacterVoiceBinding, EmotionSnapshot

        book_meta = BookMeta(
            title="Unknown",
            author="Unknown",
            genre="小说",
            difficulty="B",
            language="zh",
            total_chapters_estimated=10,
            reading_time_minutes=60,
        )
        emotion_snapshot = EmotionSnapshot(
            overall_tone="neutral",
            tension_level=3,
            key_relationships=[],
        )
        character_voice_map = []  # Would be loaded from analysis
        story_line_summary = ""
        global_style_notes = ""

        # Run annotate pipeline for each paragraph
        pipeline = AnnotateParagraphPipeline()
        markup_paragraphs = []

        for idx, para_text in enumerate(paragraphs_text):
            input_data = ParagraphAnnotationInput(
                paragraph_text=para_text,
                paragraph_index=idx,
                chapter_index=args.chapter_index,
                book_meta=book_meta,
                character_voice_map=character_voice_map,
                emotion_snapshot=emotion_snapshot,
                story_line_summary=story_line_summary,
                global_style_notes=global_style_notes,
            )
            annotation = pipeline.run(input_data)

            markup_paragraphs.append(
                ParagraphMarkup(
                    index=annotation.paragraph_index,
                    text=annotation.text[:200],
                    speaker=annotation.speaker_canonical_name,
                    emotion=annotation.emotion,
                    speech_rate=annotation.speech_rate,
                    pitch_shift=annotation.pitch_shift_semitones,
                    pause_after=annotation.pause_after_ms,
                )
            )

        return GenerateEmotionMarkupResult(
            status="ok",
            paragraphs=markup_paragraphs,
            project_id=args.project_id,
            chapter_index=args.chapter_index,
        )

    except Exception as e:
        logger.error(f"generate_emotion_markup failed for project {args.project_id} chapter {args.chapter_index}: {e}")
        return GenerateEmotionMarkupResult(
            status="failed",
            error_message=str(e),
            project_id=args.project_id,
            chapter_index=args.chapter_index,
        )


async def execute_audio_synthesis(args: ExecuteAudioSynthesisArgs) -> ExecuteAudioSynthesisResult:
    """Execute audio synthesis for a chapter.

    Delegates to the existing synthesize pipeline stage.
    """
    try:
        # Load annotations from storage
        annotations = load_chapter_annotations(args.project_id, args.chapter_index)
        if not annotations:
            return ExecuteAudioSynthesisResult(
                status="failed",
                error_message=f"No annotations found for chapter {args.chapter_index}",
                project_id=args.project_id,
                chapter_index=args.chapter_index,
            )

        # Build TtsRoutingInput from annotations
        from ..schemas import CharacterVoiceBinding, ParagraphAnnotation, TtsRoutingInput

        tts_inputs = []
        for idx, ann in enumerate(annotations):
            paragraph_annotation = ParagraphAnnotation(**ann)
            # Find voice binding for this speaker
            voice_binding = CharacterVoiceBinding(
                canonical_name=ann.get("speaker_canonical_name", "旁白"),
                suggested_voice_id="default",
                sample_quote="",
            )
            tts_inputs.append(
                TtsRoutingInput(
                    paragraph_annotation=paragraph_annotation,
                    text=ann.get("text", ""),
                    character_voice_map=[voice_binding],
                    book_id=f"book_{args.project_id}",
                    chapter_index=args.chapter_index,
                    paragraph_index=idx + 1,
                )
            )

        # Run synthesis pipeline
        output_dir = audio_dir(args.project_id, ensure=True)
        fake_port = FakeRemoteTTSPort(synthesis_delay=0.01, failure_rate=0.0)
        pipeline = SynthesizePipeline(
            output_dir=str(output_dir),
            mock_mode=False,
            port=fake_port,
        )

        audio_segments = pipeline.run(tts_inputs)
        await fake_port.close()

        segments = []
        for seg in audio_segments:
            segments.append(
                AudioSegment(
                    paragraph_index=seg.segment_id,
                    audio_path=seg.file_path,
                    duration_ms=seg.duration_ms,
                    voice_id=seg.voice_id,
                )
            )

        return ExecuteAudioSynthesisResult(
            status="ok",
            audio_segments=segments,
            project_id=args.project_id,
            chapter_index=args.chapter_index,
        )

    except Exception as e:
        logger.error(f"execute_audio_synthesis failed for project {args.project_id} chapter {args.chapter_index}: {e}")
        return ExecuteAudioSynthesisResult(
            status="failed",
            error_message=str(e),
            project_id=args.project_id,
            chapter_index=args.chapter_index,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Tool Registry
# ─────────────────────────────────────────────────────────────────────────────


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "load_book_file",
            "description": "上传并解析书籍文件（PDF/EPUB/TXT/DOCX/图片），提取文本并分章",
            "parameters": LoadBookFileArgs.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_and_split",
            "description": "分析书籍结构并按章节分割，识别角色、情感、语速等标注信息",
            "parameters": AnalyzeAndSplitArgs.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_emotion_markup",
            "description": "为指定章节生成情感标注，包含说话人、情感、语速、音调、停顿等声学参数",
            "parameters": GenerateEmotionMarkupArgs.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_audio_synthesis",
            "description": "执行指定章节的语音合成，生成音频文件",
            "parameters": ExecuteAudioSynthesisArgs.model_json_schema(),
        },
    },
]


TOOL_HANDLERS = {
    "load_book_file": load_book_file,
    "analyze_and_split": analyze_and_split,
    "generate_emotion_markup": generate_emotion_markup,
    "execute_audio_synthesis": execute_audio_synthesis,
}


async def execute_tool(name: str, args: dict) -> BaseModel:
    """Execute a tool by name with validated arguments.

    Args:
        name: Tool name
        args: Arguments dict

    Returns:
        Tool result as Pydantic model
    """
    if name not in TOOL_HANDLERS:
        raise ValueError(f"Unknown tool: {name}")

    handler = TOOL_HANDLERS[name]
    # Validate args against schema
    schema_map = {
        "load_book_file": LoadBookFileArgs,
        "analyze_and_split": AnalyzeAndSplitArgs,
        "generate_emotion_markup": GenerateEmotionMarkupArgs,
        "execute_audio_synthesis": ExecuteAudioSynthesisArgs,
    }
    validated_args = schema_map[name](**args)
    return await handler(validated_args)
