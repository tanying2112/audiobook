from datetime import datetime, timezone
from typing import Any, Dict

from ..base import AbstractAgent, AgentCapability, AgentMessage
from ..database import SessionLocal, get_db
from ..models import TaskRecord
from .analyze_structure import analyze_structure
from .extract import extract_text
from .quality_check import QualityCheckPipeline
from .synthesize import SynthesizePipeline


class ExtractAgent(AbstractAgent):
    def __init__(self):
        super().__init__([AgentCapability.TEXT_EXTRACTION])

    def _handle_message(self, message: AgentMessage):
        try:
            db = SessionLocal()
            try:
                task_record = (
                    db.query(TaskRecord).filter_by(id=self.context.task_id).first()
                )

                # Create new task record if not found
                if task_record is None:
                    task_record = TaskRecord(
                        id=self.context.task_id,
                        task_type=message.content.get("task_type", "extract"),
                        input_data=message.content,
                        status="RUNNING",
                        created_at=datetime.now(timezone.utc),
                    )
                    db.add(task_record)

                # Call existing extract pipeline
                extraction_result = extract_text(
                    file_path=message.content["file_path"],
                    mime_type=message.content["mime_type"],
                )

                # Update task status
                task_record.status = "COMPLETED"
                task_record.output_data = extraction_result.model_dump()
                task_record.completed_at = datetime.now(timezone.utc)
                db.commit()
            finally:
                db.close()

        except Exception as e:
            self._handle_failure(e)


class AnalyzeAgent(AbstractAgent):
    def __init__(self):
        super().__init__([AgentCapability.STRUCTURE_ANALYSIS])

    def _handle_message(self, message: AgentMessage):
        try:
            db = next(get_db())
            task_record = (
                db.query(TaskRecord).filter_by(id=self.context.task_id).first()
            )

            # Call existing analysis pipeline
            analysis_result = analyze_structure(
                raw_text=message.content["raw_text"],
                title_hint=message.content.get("title_hint"),
                author_hint=message.content.get("author_hint"),
                target_difficulty=message.content.get("target_difficulty", "B"),
            )

            # Update task status
            task_record.status = "COMPLETED"
            task_record.output_data = analysis_result.model_dump()
            task_record.completed_at = datetime.now(timezone.utc)
            db.commit()

        except Exception as e:
            self._handle_failure(e)


class SynthesizeAgent(AbstractAgent):
    def __init__(self):
        super().__init__([AgentCapability.TTS_SYNTHESIS])
        self.pipeline = SynthesizePipeline()

    def _handle_message(self, message: AgentMessage):
        try:
            db = next(get_db())
            task_record = (
                db.query(TaskRecord).filter_by(id=self.context.task_id).first()
            )

            # Call existing synthesis pipeline
            synthesis_result = self.pipeline.run(
                text=message.content["text"],
                voice_params=message.content["voice_params"],
                quality_level=message.content.get("quality_level", "standard"),
            )

            task_record.status = "COMPLETED"
            task_record.output_data = {
                "audio_segments": [seg.to_dict() for seg in synthesis_result],
                "book_id": message.content.get("book_id"),
            }
            task_record.completed_at = datetime.now(timezone.utc)
            db.commit()

        except Exception as e:
            self._handle_failure(e)


class QualityAgent(AbstractAgent):
    def __init__(self):
        super().__init__([AgentCapability.QUALITY_CONTROL])
        self.pipeline = QualityCheckPipeline()

    def _handle_message(self, message: AgentMessage):
        try:
            db = next(get_db())
            task_record = (
                db.query(TaskRecord).filter_by(id=self.context.task_id).first()
            )

            quality_report = self.pipeline.run(
                audio_segments=message.content["audio_segments"],
                reference_text=message.content["reference_text"],
                book_id=message.content.get("book_id"),
            )

            task_record.status = "COMPLETED"
            task_record.output_data = quality_report.model_dump()
            task_record.completed_at = datetime.now(timezone.utc)
            db.commit()

        except Exception as e:
            self._handle_failure(e)
