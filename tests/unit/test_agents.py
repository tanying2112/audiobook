"""Unit tests for the agents module."""
import os
os.environ["MOCK_LLM"] = "true"

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch, Mock

from src.audiobook_studio.pipeline.agents import (
    ExtractAgent,
    AnalyzeAgent,
    SynthesizeAgent,
    QualityAgent,
)
from src.audiobook_studio.base import AgentMessage, AgentContext, AgentCapability


class TestExtractAgent:
    """Tests for ExtractAgent."""

    def test_init(self):
        """Test ExtractAgent initialization."""
        agent = ExtractAgent()
        assert AgentCapability.TEXT_EXTRACTION in agent.capabilities

    def test_handle_message_calls_extract_text(self):
        """Test _handle_message calls extract_text with correct params."""
        agent = ExtractAgent()
        agent.context = AgentContext(
            task_id="1", book_id="book1", current_stage="extract", shared_knowledge={}
        )

        mock_result = Mock()
        mock_result.dict.return_value = {"text": "extracted"}

        with patch('src.audiobook_studio.pipeline.agents.SessionLocal') as mock_session:
            with patch('src.audiobook_studio.pipeline.agents.extract_text', return_value=mock_result) as mock_extract:
                mock_db = MagicMock()
                mock_session.return_value = mock_db
                mock_task = MagicMock()
                mock_db.query.return_value.filter_by.return_value.first.return_value = mock_task

                msg = AgentMessage(
                    sender="test", 
                    content={"file_path": "/test.pdf", "mime_type": "application/pdf"}
                )
                agent._handle_message(msg)

                mock_extract.assert_called_once_with(
                    file_path="/test.pdf",
                    mime_type="application/pdf",
                )


class TestAnalyzeAgent:
    """Tests for AnalyzeAgent."""

    def test_init(self):
        """Test AnalyzeAgent initialization."""
        agent = AnalyzeAgent()
        assert AgentCapability.STRUCTURE_ANALYSIS in agent.capabilities

    def test_handle_message_calls_analyze_structure(self):
        """Test _handle_message calls analyze_structure."""
        agent = AnalyzeAgent()
        agent.context = AgentContext(
            task_id="2", book_id="book2", current_stage="analyze", shared_knowledge={}
        )

        mock_result = Mock()
        mock_result.dict.return_value = {"chapters": []}

        with patch('src.audiobook_studio.pipeline.agents.get_db') as mock_get_db:
            with patch('src.audiobook_studio.pipeline.agents.analyze_structure', return_value=mock_result) as mock_analyze:
                mock_db = MagicMock()
                mock_get_db.return_value = mock_db
                mock_task = MagicMock()
                mock_db.query.return_value.filter_by.return_value.first.return_value = mock_task

                msg = AgentMessage(
                    sender="test", 
                    content={"raw_text": "test text"}
                )
                agent._handle_message(msg)

                mock_analyze.assert_called_once()


class TestSynthesizeAgent:
    """Tests for SynthesizeAgent."""

    def test_init(self):
        """Test SynthesizeAgent initialization."""
        agent = SynthesizeAgent()
        assert AgentCapability.TTS_SYNTHESIS in agent.capabilities
        assert hasattr(agent, 'pipeline')

    def test_handle_message_calls_run(self):
        """Test _handle_message calls pipeline.run."""
        agent = SynthesizeAgent()
        agent.context = AgentContext(
            task_id="3", book_id="book3", current_stage="synthesize", shared_knowledge={}
        )

        mock_segment = Mock()
        mock_segment.to_dict.return_value = {"audio": "segment.wav"}
        mock_result = [mock_segment]

        with patch('src.audiobook_studio.pipeline.agents.get_db') as mock_get_db:
            with patch.object(agent.pipeline, 'run', return_value=mock_result) as mock_run:
                mock_db = MagicMock()
                mock_get_db.return_value = mock_db
                mock_task = MagicMock()
                mock_db.query.return_value.filter_by.return_value.first.return_value = mock_task

                msg = AgentMessage(
                    sender="test",
                    content={
                        "text": "Hello world",
                        "voice_params": {"voice": "test"},
                        "book_id": 1
                    }
                )
                agent._handle_message(msg)

                mock_run.assert_called_once()


class TestQualityAgent:
    """Tests for QualityAgent."""

    def test_init(self):
        """Test QualityAgent initialization."""
        agent = QualityAgent()
        assert AgentCapability.QUALITY_CONTROL in agent.capabilities
        assert hasattr(agent, 'pipeline')

    def test_handle_message_calls_run(self):
        """Test _handle_message calls pipeline.run."""
        agent = QualityAgent()
        agent.context = AgentContext(
            task_id="4", book_id="book4", current_stage="quality", shared_knowledge={}
        )

        mock_result = Mock()
        mock_result.dict.return_value = {"score": 0.95}

        with patch('src.audiobook_studio.pipeline.agents.get_db') as mock_get_db:
            with patch.object(agent.pipeline, 'run', return_value=mock_result) as mock_run:
                mock_db = MagicMock()
                mock_get_db.return_value = mock_db
                mock_task = MagicMock()
                mock_db.query.return_value.filter_by.return_value.first.return_value = mock_task

                msg = AgentMessage(
                    sender="test",
                    content={
                        "audio_segments": [],
                        "reference_text": "reference text",
                        "book_id": 1
                    }
                )
                agent._handle_message(msg)

                mock_run.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
