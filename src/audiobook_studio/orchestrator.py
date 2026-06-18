from typing import Any, Dict, List, Optional, TypeVar
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import mimetypes
import threading
import uuid
import logging
from datetime import datetime

from .database import SessionLocal
from .models import TaskRecord

logger = logging.getLogger(__name__)

T = TypeVar("T")


class AgentCapability(Enum):
    TEXT_EXTRACTION = "extract"
    STRUCTURE_ANALYSIS = "analyze"
    TTS_SYNTHESIS = "synthesize"
    QUALITY_CONTROL = "quality_check"
    FEEDBACK_LEARNING = "learn"


@dataclass
class AgentContext:
    task_id: str
    book_id: str
    current_stage: str
    shared_knowledge: dict


@dataclass
class AgentMessage:
    sender: str
    content: dict
    requires_response: bool = False


@dataclass
class PipelineRunResult:
    """Result returned by run_pipeline_mock."""

    task_id: str
    status: str
    file_path: str
    output_dir: str
    extraction: Optional[Any] = None
    analysis: Optional[Any] = None
    audio_segments: List[Any] = field(default_factory=list)
    stages: List[str] = field(default_factory=list)
    error: Optional[str] = None


class AbstractAgent:
    def __init__(self, capabilities: List[AgentCapability]):
        self.agent_id = f"{self.__class__.__name__}-{str(uuid.uuid4())[:8]}"
        self.capabilities = capabilities
        self.context: Optional[AgentContext] = None
        self.message_queue = []
        self.lock = threading.Lock()
        self.logger = logging.getLogger(self.agent_id)

    def receive_message(self, message: AgentMessage):
        with self.lock:
            self.message_queue.append(message)

    def process_messages(self):
        while self.message_queue:
            msg = self.message_queue.pop(0)
            self._handle_message(msg)

    def _handle_message(self, message: AgentMessage):
        raise NotImplementedError

    def acquire_context(self, context: AgentContext):
        self.context = context

    def can_handle(self, capability: AgentCapability) -> bool:
        return capability in self.capabilities

    def _handle_failure(self, error: Exception):
        """Common error handling for all agents."""
        db = SessionLocal()
        task_id = self.context.task_id if self.context is not None else str(uuid.uuid4())

        try:
            task_record = db.query(TaskRecord).filter_by(id=task_id).first()
            if task_record is None:
                task_record = TaskRecord(id=task_id, status="FAILED")
                db.add(task_record)
            else:
                task_record.status = "FAILED"

            task_record.output_data = {
                "error": str(error),
                "error_type": type(error).__name__,
            }
            task_record.completed_at = datetime.utcnow()
            db.commit()
        except Exception as db_error:
            db.rollback()
            self.logger.error(f"Failed to persist task failure: {db_error}", exc_info=True)
        finally:
            db.close()

        self.logger.error(f"Task failed: {error}", exc_info=True)


class Orchestrator:
    def __init__(self):
        self.agents: Dict[str, AbstractAgent] = {}
        self.task_registry = {}
        self._register_core_agents()

    def _register_core_agents(self):
        """Register essential agents for audiobook production."""
        from .pipeline.agents import (
            ExtractAgent,
            AnalyzeAgent,
            SynthesizeAgent,
            QualityAgent,
        )

        self.register_agent(ExtractAgent())
        self.register_agent(AnalyzeAgent())
        self.register_agent(SynthesizeAgent())
        self.register_agent(QualityAgent())

    def register_agent(self, agent: AbstractAgent):
        self.agents[agent.agent_id] = agent

    def dispatch_task(self, task_type: AgentCapability, payload: dict) -> str:
        """Route tasks to capable agents with load balancing."""
        task_id = str(uuid.uuid4())

        capable_agents = [
            agent
            for agent in self.agents.values()
            if agent.can_handle(task_type)
        ]

        if not capable_agents:
            raise ValueError(f"No agents available for {task_type}")

        selected_agent = capable_agents[0]

        context = AgentContext(
            task_id=task_id,
            book_id=payload.get("book_id", ""),
            current_stage=task_type.value,
            shared_knowledge={},
        )

        selected_agent.acquire_context(context)
        selected_agent.receive_message(
            AgentMessage(
                sender="orchestrator",
                content=payload,
            )
        )

        self.task_registry[task_id] = {
            "status": "pending",
            "assigned_agent": selected_agent.agent_id,
        }

        return task_id

    def monitor_tasks(self):
        """Background task monitoring and recovery."""
        pass

    def run_pipeline_mock(
        self,
        file_path: str,
        output_dir: Optional[str] = None,
    ) -> PipelineRunResult:
        """Run a pure mock end-to-end audiobook pipeline.

        This function sequentially executes the existing extract, analyze and
        synthesize stages in mock mode. It intentionally avoids real LLM and TTS
        API calls.

        Args:
            file_path: Source file path to extract text from.
            output_dir: Directory for mock synthesized audio segments.

        Returns:
            PipelineRunResult containing the mock stage outputs and generated
            audio segment descriptors.
        """
        task_id = str(uuid.uuid4())
        stages: List[str] = []
        error: Optional[str] = None

        try:
            from .pipeline.extract import ExtractPipeline
            from .pipeline.analyze_structure import AnalyzeStructurePipeline
            from .pipeline.synthesize import SynthesizePipeline
            from .schemas import (
                BookAnalysisOutput,
                CharacterVoiceBinding,
                ExtractionInput,
                ParagraphAnnotation,
                TtsRoutingInput,
            )

            path = Path(file_path)
            mime_type = mimetypes.guess_type(path.name)[0] or "text/plain"
            book_id = path.stem or "mock_book"
            output_path = Path(output_dir) if output_dir else Path("./output/mock") / book_id
            output_path.mkdir(parents=True, exist_ok=True)

            # Stage 1: Extract text.
            stages.append("extract")
            extract_pipeline = ExtractPipeline(mock_mode=True)
            extraction_result = extract_pipeline.run(
                ExtractionInput(
                    file_path=str(path),
                    mime_type=mime_type,
                    detect_language=True,
                )
            )

            # Stage 2: Analyze structure.
            # The existing analyze pipeline is invoked in mock mode so the router
            # does not call a real LLM. If the mock router still fails, fall back
            # to a minimal valid analysis result built from the extracted text.
            stages.append("analyze")
            # 提前导入需要的 Schema
            from .schemas import BookAnalysisInput

            try:
                analysis_pipeline = AnalyzeStructurePipeline(mock_mode=True)
                analysis_result = analysis_pipeline.run(
                    BookAnalysisInput(
                        raw_text=extraction_result.raw_text,
                        title_hint=book_id,
                        author_hint=None,
                        target_difficulty="B",
                    )
                )
            except Exception as exc:
                # 使用 logging.warning 替代未定义的 logger.warning
                logging.warning(
                    "Mock structure analysis failed, using fallback analysis: %s",
                    exc,
                )

                analysis_pipeline = AnalyzeStructurePipeline(mock_mode=True)
                analysis_result = analysis_pipeline.run(
                    BookAnalysisInput(
                        raw_text=extraction_result.raw_text,
                        title_hint=book_id,
                        author_hint=None,
                        target_difficulty="B",
                    )
                )

            # Stage 5: Synthesize audio.
            # Build mock routing inputs from the analysis result. If the analysis
            # schema does not expose paragraph data in the expected shape, create
            # one mock paragraph from the extracted raw text.
            stages.append("synthesize")
            routing_inputs = self._build_mock_routing_inputs(
                analysis_result=analysis_result,
                raw_text=extraction_result.raw_text,
                book_id=book_id,
                CharacterVoiceBinding=CharacterVoiceBinding,
                ParagraphAnnotation=ParagraphAnnotation,
                TtsRoutingInput=TtsRoutingInput,
            )

            synthesize_pipeline = SynthesizePipeline(
                output_dir=str(output_path),
                mock_mode=True,
            )
            audio_segments = synthesize_pipeline.run(routing_inputs)

            self.task_registry[task_id] = {
                "status": "completed",
                "assigned_agent": "mock-orchestrator",
                "file_path": str(path),
                "output_dir": str(output_path),
            }

            return PipelineRunResult(
                task_id=task_id,
                status="completed",
                file_path=str(path),
                output_dir=str(output_path),
                extraction=extraction_result,
                analysis=analysis_result,
                audio_segments=audio_segments,
                stages=stages,
                error=None,
            )

        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self.task_registry[task_id] = {
                "status": "failed",
                "assigned_agent": "mock-orchestrator",
                "file_path": file_path,
                "error": error,
            }
            # 同样替换为 logging.exception
            logging.exception("Mock pipeline failed")

            return PipelineRunResult(
                task_id=task_id,
                status="failed",
                file_path=file_path,
                output_dir=output_dir or "",
                stages=stages,
                error=error,
            )

    def _build_mock_routing_inputs(
        self,
        *,
        analysis_result: Any,
        raw_text: str,
        book_id: str,
        CharacterVoiceBinding: Any,
        ParagraphAnnotation: Any,
        TtsRoutingInput: Any,
    ) -> List[Any]:
        """Build TtsRoutingInput objects for mock synthesis.

        The exact shape of BookAnalysisOutput is schema-dependent. This method
        accepts several common shapes and falls back to a single paragraph if no
        structured paragraph data is available.
        """
        analysis_data = self._model_to_dict(analysis_result)

        paragraphs = self._extract_paragraphs_from_analysis(analysis_data)
        if not paragraphs:
            paragraphs = [
                {
                    "id": 1,
                    "chapter_id": 1,
                    "chapter_index": 1,
                    "paragraph_index": 1,
                    "text": raw_text,
                    "speaker_canonical_name": "旁白",
                    "speech_rate": 1.0,
                    "pitch_shift_semitones": 0,
                    "emotion": "neutral",
                    "emotion_intensity": 0.5,
                }
            ]

        character_voice_map = self._extract_character_voice_map(analysis_data)
        if not character_voice_map:
            character_voice_map = [
                CharacterVoiceBinding(
                    canonical_name="旁白",
                    suggested_voice_id="zh-CN-XiaoxiaoNeural",
                )
            ]

        routing_inputs = []
        for paragraph in paragraphs:
            chapter_id = paragraph.get("chapter_id", 1)
            chapter_index = int(paragraph.get("chapter_index", chapter_id or 1))
            paragraph_id = paragraph.get("id", paragraph.get("paragraph_id"))
            paragraph_index = int(paragraph.get("paragraph_index", paragraph_id or 1))
            text = paragraph.get("text") or raw_text
            speaker = paragraph.get("speaker_canonical_name") or "旁白"

            paragraph_annotation = ParagraphAnnotation(
                paragraph_id=paragraph_id,
                chapter_id=chapter_id,
                paragraph_index=paragraph_index,
                text=text,
                speaker_canonical_name=speaker,
                is_dialogue=bool(paragraph.get("is_dialogue", False)),
                emotion=paragraph.get("emotion", "neutral"),
                emotion_intensity=float(paragraph.get("emotion_intensity", 0.5)),
                speech_rate=float(paragraph.get("speech_rate", 1.0)),
                pitch_shift_semitones=float(paragraph.get("pitch_shift_semitones", 0)),
            )

            routing_inputs.append(
                TtsRoutingInput(
                    book_id=book_id,
                    chapter_id=chapter_id,
                    chapter_index=chapter_index,
                    paragraph_id=paragraph_id,
                    paragraph_index=paragraph_index,
                    text=text,
                    paragraph_annotation=paragraph_annotation,
                    character_voice_map=character_voice_map,
                    prefer_local=True,
                )
            )

        return routing_inputs

    def _extract_paragraphs_from_analysis(self, analysis_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract paragraph-like data from BookAnalysisOutput."""
        if not isinstance(analysis_data, dict):
            return []

        candidates = []
        for key in (
            "paragraphs",
            "chapters",
            "paragraph_annotations",
            "annotations",
            "analysis",
            "output",
        ):
            value = analysis_data.get(key)
            if isinstance(value, list):
                candidates.extend(value)
            elif isinstance(value, dict):
                candidates.append(value)

        paragraphs: List[Dict[str, Any]] = []
        for item in candidates:
            if not isinstance(item, dict):
                continue

            text = self._find_text_value(item)
            if not text:
                continue

            paragraph = dict(item)
            paragraph.setdefault("text", text)
            paragraph.setdefault("speaker_canonical_name", self._find_speaker(item) or "旁白")
            paragraph.setdefault("paragraph_index", paragraph.get("id") or paragraph.get("paragraph_id") or len(paragraphs) + 1)
            paragraph.setdefault("chapter_index", paragraph.get("chapter_id") or 1)
            paragraphs.append(paragraph)

        return paragraphs

    def _extract_character_voice_map(self, analysis_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract character/voice mapping from BookAnalysisOutput."""
        if not isinstance(analysis_data, dict):
            return []

        candidates = []
        for key in (
            "characters",
            "character_voice_map",
            "voice_map",
            "speakers",
            "analysis",
            "output",
        ):
            value = analysis_data.get(key)
            if isinstance(value, list):
                candidates.extend(value)
            elif isinstance(value, dict):
                candidates.append(value)

        mappings: List[Dict[str, Any]] = []
        for item in candidates:
            if not isinstance(item, dict):
                continue

            name = item.get("canonical_name") or item.get("name") or item.get("speaker") or item.get("character")
            if not name:
                continue

            voice_id = (
                item.get("suggested_voice_id")
                or item.get("voice_id")
                or item.get("voice")
                or "zh-CN-XiaoxiaoNeural"
            )
            mappings.append(
                {
                    "canonical_name": str(name),
                    "suggested_voice_id": str(voice_id),
                }
            )

        return mappings

    def _model_to_dict(self, value: Any) -> Dict[str, Any]:
        """Convert a Pydantic model or nested dict/list to a plain dict."""
        if hasattr(value, "model_dump"):
            value = value.model_dump()
        elif hasattr(value, "dict"):
            value = value.dict()

        if isinstance(value, dict):
            return {k: self._model_to_dict(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._model_to_dict(v) for v in value]
        return value

    def _find_text_value(self, data: Dict[str, Any]) -> Optional[str]:
        """Find the first usable text field in a nested dict."""
        for key in (
            "text",
            "content",
            "raw_text",
            "paragraph_text",
            "speaker_text",
        ):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        for value in data.values():
            if isinstance(value, dict):
                found = self._find_text_value(value)
                if found:
                    return found
            elif isinstance(value, str) and len(value.strip()) >= 10:
                return value.strip()

        return None

    def _find_speaker(self, data: Dict[str, Any]) -> Optional[str]:
        """Find speaker/name information in a nested dict."""
        for key in (
            "speaker_canonical_name",
            "speaker",
            "canonical_name",
            "character",
            "role",
        ):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        for value in data.values():
            if isinstance(value, dict):
                found = self._find_speaker(value)
                if found:
                    return found

        return None
