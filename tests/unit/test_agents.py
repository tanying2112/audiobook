"""Unit tests for the agents module."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.base import AgentCapability
from src.audiobook_studio.database import SessionLocal, get_db
from src.audiobook_studio.models import TaskRecord
from src.audiobook_studio.pipeline.agents import (
    AnalyzeAgent,
    ExtractAgent,
    QualityAgent,
    SynthesizeAgent,
)
from src.audiobook_studio.pipeline.analyze_structure import BookAnalysisOutput
from src.audiobook_studio.pipeline.extract import ExtractionResult
from src.audiobook_studio.pipeline.quality_check import QualityJudgment
from src.audiobook_studio.pipeline.synthesize import AudioSegment


def make_agent(agent_class):
    """Create an agent with a mocked context."""
    agent = agent_class()
    agent.context = MagicMock()
    agent.context.task_id = 1
    agent._handle_failure = MagicMock()
    return agent


class TestExtractAgent:
    """Tests for ExtractAgent."""

    def test_init(self):
        agent = ExtractAgent()
        assert AgentCapability.TEXT_EXTRACTION in agent.capabilities

    def test_handle_message_success(self):
        agent = make_agent(ExtractAgent)
        mock_session = MagicMock()
        mock_task_record = MagicMock(spec=TaskRecord)
        mock_session.query.return_value.filter_by.return_value.first.return_value = (
            mock_task_record
        )
        mock_extract_result = ExtractionResult(
            raw_text="extracted text",
            language="zh",
            page_count=5,
            has_ocr=False,
            ocr_page_ratio=0.0,
            warnings=[],
        )
        with patch(
            "src.audiobook_studio.database.SessionLocal", return_value=mock_session
        ) as mock_session_local, patch(
            "src.audiobook_studio.pipeline.agents.extract_text"
        ) as mock_extract:
            mock_extract.return_value = mock_extract_result
            message = MagicMock()
            message.content = {"file_path": "/fake/path.txt", "mime_type": "text/plain"}
            agent._handle_message(message)
            mock_extract.assert_called_once_with(
                file_path="/fake/path.txt", mime_type="text/plain"
            )
            assert mock_task_record.status == "COMPLETED"
            assert mock_task_record.output_data == mock_extract_result.model_dump()
            assert mock_task_record.completed_at is not None
            mock_session.commit.assert_called_once()
            mock_session.close.assert_called_once()
            agent._handle_failure.assert_not_called()

    def test_handle_message_exception(self):
        agent = make_agent(ExtractAgent)
        mock_session = MagicMock()
        mock_task_record = MagicMock(spec=TaskRecord)
        with patch(
            "src.audiobook_studio.database.SessionLocal", return_value=mock_session
        ) as mock_session_local, patch(
            "src.audiobook_studio.pipeline.agents.extract_text"
        ) as mock_extract:
            mock_extract.side_effect = Exception("extract failed")
            message = MagicMock()
            message.content = {"file_path": "/fake/path.txt", "mime_type": "text/plain"}
            agent._handle_message(message)
            agent._handle_failure.assert_called_once()
            mock_session.commit.assert_not_called()
            mock_session.close.assert_called_once()


class TestAnalyzeAgent:
    """Tests for AnalyzeAgent."""

    def test_init(self):
        agent = AnalyzeAgent()
        assert AgentCapability.STRUCTURE_ANALYSIS in agent.capabilities

    def test_handle_message_success(self):
        agent = make_agent(AnalyzeAgent)
        mock_session = MagicMock()
        mock_task_record = MagicMock(spec=TaskRecord)
        mock_analyze_result = BookAnalysisOutput(
            book_meta=MagicMock(),
            character_voice_map=[],
            emotion_snapshots=[],
            story_line_summary="summary",
            global_style_notes="notes",
            contract_version=1,
        )
        with patch("src.audiobook_studio.pipeline.agents.get_db") as mock_get_db, patch(
            "src.audiobook_studio.pipeline.agents.analyze_structure"
        ) as mock_analyze:
            mock_get_db.return_value = iter([mock_session])  # get_db is a generator
            mock_session.query.return_value.filter_by.return_value.first.return_value = (
                mock_task_record
            )
            mock_analyze.return_value = mock_analyze_result
            message = MagicMock()
            message.content = {
                "raw_text": "test raw text",
                "title_hint": "title",
                "author_hint": "author",
                "target_difficulty": "B",
            }
            agent._handle_message(message)
            mock_analyze.assert_called_once_with(
                raw_text="test raw text",
                title_hint="title",
                author_hint="author",
                target_difficulty="B",
            )
            assert mock_task_record.status == "COMPLETED"
            assert mock_task_record.output_data == mock_analyze_result.model_dump()
            assert mock_task_record.completed_at is not None
            mock_session.commit.assert_called_once()
            # get_db session is not closed by agent (see code)
            mock_session.close.assert_not_called()
            agent._handle_failure.assert_not_called()

    def test_handle_message_exception(self):
        agent = make_agent(AnalyzeAgent)
        mock_session = MagicMock()
        mock_task_record = MagicMock(spec=TaskRecord)
        with patch("src.audiobook_studio.pipeline.agents.get_db") as mock_get_db, patch(
            "src.audiobook_studio.pipeline.agents.analyze_structure"
        ) as mock_analyze:
            mock_get_db.return_value = iter([mock_session])
            mock_session.query.return_value.filter_by.return_value.first.return_value = (
                mock_task_record
            )
            mock_analyze.side_effect = Exception("analyze failed")
            message = MagicMock()
            message.content = {
                "raw_text": "test",
                "title_hint": "title",
                "author_roles": "author",
                "target_difficulty": "B",
            }
            agent._handle_message(message)
            agent._handle_failure.assert_called_once()
            mock_session.commit.assert_not_called()


class TestSynthesizeAgent:
    """Tests for SynthesizeAgent."""

    def test_init(self):
        agent = SynthesizeAgent()
        assert AgentCapability.TTS_SYNTHESIS in agent.capabilities
        assert hasattr(agent, "pipeline")

    def test_handle_message_success(self):
        agent = make_agent(SynthesizeAgent)
        mock_session = MagicMock()
        mock_task4 = MagicMock(spec=TaskRecord)
        mock_segment = MagicMock(spec=AudioSegment)
        mock_segment.to_dict.return_value = {"dummy": "segment"}
        with patch(
            "src.audiobook_studio.pipeline.agents.get_db"
        ) as mock_get_db, patch.object(agent, "pipeline") as mock_pipeline:
            mock_get_db.return_value = iter([mock_session])
            mock_session.query.return_value.filter_by.return_value.first.return_value = (
                mock_task4
            )
            mock_pipeline.run.return_value = [mock_segment]
            message = MagicMock()
            message.content = {
                "text": "test text",
                "voice_params": {"voice_id": "test_voice"},
                "book_id": 1,
            }
            agent._handle_message(message)
            mock_pipeline.run.assert_called_once_with(
                text="test text",
                voice_params={"voice_id": "test_voice"},
                quality_level="standard",
            )
            assert mock_task4.status == "COMPLETED"
            assert mock_task4.output_data is not None
            assert "audio_segments" in mock_task4.output_data
            assert len(mock_task4.output_data["audio_segments"]) == 1
            assert mock_task4.output_data["audio_segments"][0] == {"dummy": "segment"}
            assert mock_task4.output_data["book_id"] == 1
            assert mock_task4.completed_at is not None
            mock_session.commit.assert_called_once()
            mock_session.close.assert_not_called()
            agent._handle_failure.assert_not_called()

    def test_handle_message_exception(self):
        agent = make_agent(SynthesizeAgent)
        mock_session = MagicMock()
        mock_task4 = MagicMock(spec=TaskRecord)
        with patch(
            "src.audiobook_studio.pipeline.agents.get_db"
        ) as mock_get_db, patch.object(agent, "pipeline") as mock_pipeline:
            mock_get_db.return_value = iter([mock_session])
            mock_session.query.return_value.filter_by.return_value.first.return_value = (
                mock_task4
            )
            mock_pipeline.run.side_effect = Exception("synth failed")
            message = MagicMock()
            message.content = {"text": "test", "voice_params": {}, "book_id": 1}
            agent._handle_message(message)
            agent._handle_failure.assert_called_once()
            mock_session.commit.assert_not_called()


class TestQualityAgent:
    """Tests for QualityAgent."""

    def test_init(self):
        agent = QualityAgent()
        assert AgentCapability.QUALITY_CONTROL in agent.capabilities
        assert hasattr(agent, "pipeline")

    def test_handle_message_success(self):
        agent = make_agent(QualityAgent)
        mock_session = MagicMock()
        mock_task4 = MagicMock(spec=TaskRecord)
        mock_judgment = MagicMock(spec=QualityJudgment)
        mock_judgment.model_dump.return_value = {"dummy": "judgment"}
        with patch(
            "src.audiobook_studio.pipeline.agents.get_db"
        ) as mock_get_db, patch.object(agent, "pipeline") as mock_pipeline:
            mock_get_db.return_value = iter([mock_session])
            mock_session.query.return_value.filter_by.return_value.first.return_value = (
                mock_task4
            )
            mock_pipeline.run.return_value = mock_judgment
            message = MagicMock()
            message.content = {
                "audio_segments": [{"dummy": "segment"}],
                "reference_text": "ref text",
                "book_id": 1,
            }
            agent._handle_message(message)
            mock_pipeline.run.assert_called_once_with(
                audio_segments=[{"dummy": "segment"}],
                reference_text="ref text",
                book_id=1,
            )
            assert mock_task4.status == "COMPLETED"
            assert mock_task4.output_data == {"dummy": "judgment"}
            assert mock_task4.completed_at is not None
            mock_session.commit.assert_called_once()
            mock_session.close.assert_not_called()
            agent._handle_failure.assert_not_called()

    def test_handle_message_exception(self):
        agent = make_agent(QualityAgent)
        mock_session = MagicMock()
        mock_task4 = MagicMock(spec=TaskRecord)
        with patch(
            "src.audiobook_studio.pipeline.agents.get_db"
        ) as mock_get_db, patch.object(agent, "pipeline") as mock_pipeline:
            mock_get_db.return_value = iter([mock_session])
            mock_session.query.return_value.filter_by.return_value.first.return_value = (
                mock_task4
            )
            mock_pipeline.run.side_effect = Exception("quality failed")
            message = MagicMock()
            message.content = {
                "audio_segments": [],
                "reference_text": "ref",
                "book_id": 1,
            }
            agent._handle_message(message)
            agent._handle_failure.assert_called_once()
            mock_session.commit.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
