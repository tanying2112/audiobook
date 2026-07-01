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
from src.audiobook_studio.schemas.book import BookMeta, CharacterVoiceBinding, EmotionSnapshot
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
            "src.audiobook_studio.pipeline.agents.SessionLocal", return_value=mock_session
        ) as _mock_session_local, patch(
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
            "src.audiobook_studio.pipeline.agents.SessionLocal", return_value=mock_session
        ) as _mock_session_local, patch(
            "src.audiobook_studio.pipeline.agents.extract_text"
        ) as mock_extract:
            mock_extract.side_effect = Exception("extract failed")
            message = MagicMock()
            message.content = {"file_path": "/fake/path.txt", "mime_type": "text/plain"}
            agent._handle_message(message)
            agent._handle_failure.assert_called_once()
            mock_session.commit.assert_not_called()
            mock_session.close.assert_called_once()

    def test_handle_message_create_new_task_record(self):
        """Test ExtractAgent when no existing task record is found (creates new record)."""
        agent = make_agent(ExtractAgent)
        mock_session = MagicMock()
        # Simulate no existing task record found
        mock_session.query.return_value.filter_by.return_value.first.return_value = None
        mock_extract_result = ExtractionResult(
            raw_text="extracted text",
            language="zh",
            page_count=5,
            has_ocr=False,
            ocr_page_ratio=0.0,
            warnings=[],
        )
        # To capture the task record when it's added to the session
        added_task = None
        def capture_task(task):
            nonlocal added_task
            added_task = task
        mock_session.add.side_effect = capture_task

        with patch(
            "src.audiobook_studio.pipeline.agents.SessionLocal", return_value=mock_session
        ) as _mock_session_local, patch(
            "src.audiobook_studio.pipeline.agents.extract_text"
        ) as mock_extract:
            mock_extract.return_value = mock_extract_result
            message = MagicMock()
            message.content = {
                "file_path": "/fake/path.txt",
                "mime_type": "text/plain",
                "task_type": "extract_test",
            }
            agent._handle_message(message)
            mock_extract.assert_called_once_with(
                file_path="/fake/path.txt", mime_type="text/plain"
            )
            # Verify that a new TaskRecord was created and added to the session
            assert mock_session.add.call_count == 1
            assert added_task is not None
            assert isinstance(added_task, TaskRecord)
            assert added_task.id == agent.context.task_id
            assert added_task.task_type == "extract_test"
            assert added_task.input_data == {
                "file_path": "/fake/path.txt",
                "mime_type": "text/plain",
                "task_type": "extract_test",
            }
            # Verify that the task record was updated after processing
            assert added_task.status == "COMPLETED"
            assert added_task.output_data == mock_extract_result.model_dump()
            assert added_task.completed_at is not None
            mock_session.commit.assert_called_once()
            mock_session.close.assert_called_once()
            agent._handle_failure.assert_not_called()


class TestAnalyzeAgent:
    """Tests for AnalyzeAgent."""

    def test_init(self):
        agent = AnalyzeAgent()
        assert AgentCapability.STRUCTURE_ANALYSIS in agent.capabilities

    def test_handle_message_success(self):
        agent = make_agent(AnalyzeAgent)
        mock_session = MagicMock()
        mock_task_record = MagicMock(spec=TaskRecord)
        mock_book_meta = BookMeta(
            title="测试书名",
            author="测试作者",
            genre="小说",
            difficulty="B",
            language="zh",
            era="现代",
            total_chapters_estimated=10,
            contract_version=1,
        )
        mock_character_voice = CharacterVoiceBinding(
            canonical_name="主角",
            aliases=[],
            gender="male",
            age_range="adult",
            sample_quote="今天天气真好。",
            contract_version=1,
        )
        mock_emotion = EmotionSnapshot(
            chapter=1,
            dominant_emotion="neutral",
            intensity=0.5,
            notes="开场情绪",
            contract_version=1,
        )
        mock_analyze_result = BookAnalysisOutput(
            book_meta=mock_book_meta,
            character_voice_map=[mock_character_voice],
            emotion_snapshots=[mock_emotion],
            story_line_summary="这是一个关于测试的故事，讲述了主角在测试世界中经历的种种冒险与成长历程，故事结构完整，人物形象鲜明。全书通过细腻的笔触描绘了主角内心的挣扎与蜕变，为读者呈现了一个引人入胜的文学世界，值得细细品味，余韵悠长。",
            global_style_notes="notes",
            contract_version=1,
        )
        with patch("src.audiobook_studio.pipeline.agents.SessionLocal") as mock_session_local, patch(
            "src.audiobook_studio.pipeline.agents.analyze_structure"
        ) as mock_analyze:
            mock_session_local.return_value = mock_session
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
            # SessionLocal session is closed by agent in finally block
            mock_session.close.assert_called_once()
            agent._handle_failure.assert_not_called()

    def test_handle_message_exception(self):
        agent = make_agent(AnalyzeAgent)
        mock_session = MagicMock()
        mock_task_record = MagicMock(spec=TaskRecord)
        with patch("src.audiobook_studio.pipeline.agents.SessionLocal") as mock_session_local, patch(
            "src.audiobook_studio.pipeline.agents.analyze_structure"
        ) as mock_analyze:
            mock_session_local.return_value = mock_session
            mock_session.query.return_value.filter_by.return_value.first.return_value = (
                mock_task_record
            )
            mock_analyze.side_effect = Exception("analyze failed")
            message = MagicMock()
            message.content = {
                "raw_text": "test",
                "title_hint": "title",
                "author_hint": "author",
                "target_difficulty": "B",
            }
            agent._handle_message(message)
            agent._handle_failure.assert_called_once()
            mock_session.commit.assert_not_called()
            mock_session.close.assert_called_once()

    def test_handle_message_missing_task_record(self):
        """Test AnalyzeAgent when no existing task record is found (results in failure)."""
        agent = make_agent(AnalyzeAgent)
        mock_session = MagicMock()
        # Simulate no existing task record found
        mock_session.query.return_value.filter_by.return_value.first.return_value = None
        with patch("src.audiobook_studio.pipeline.agents.SessionLocal") as mock_session_local, patch(
            "src.audiobook_studio.pipeline.agents.analyze_structure"
        ) as mock_analyze:
            mock_session_local.return_value = mock_session
            mock_analyze.return_value = MagicMock()  # This won't be called due to the exception below
            message = MagicMock()
            message.content = {
                "raw_text": "test raw text",
                "title_hint": "title",
                "author_hint": "author",
                "target_difficulty": "B",
            }
            agent._handle_message(message)
            # Since task_record is None, assigning status will raise AttributeError
            agent._handle_failure.assert_called_once()
            mock_session.commit.assert_not_called()
            mock_session.close.assert_called_once()


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
            "src.audiobook_studio.pipeline.agents.SessionLocal"
        ) as mock_session_local, patch.object(agent, "pipeline") as mock_pipeline:
            mock_session_local.return_value = mock_session
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
            mock_session.close.assert_called_once()
            agent._handle_failure.assert_not_called()

    def test_handle_message_exception(self):
        agent = make_agent(SynthesizeAgent)
        mock_session = MagicMock()
        mock_task4 = MagicMock(spec=TaskRecord)
        with patch(
            "src.audiobook_studio.pipeline.agents.SessionLocal"
        ) as mock_get_db, patch.object(agent, "pipeline") as mock_pipeline:
            mock_get_db.return_value = mock_session
            mock_session.query.return_value.filter_by.return_value.first.return_value = (
                mock_task4
            )
            mock_pipeline.run.side_effect = Exception("synth failed")
            message = MagicMock()
            message.content = {"text": "test", "voice_params": {}, "book_id": 1}
            agent._handle_message(message)
            agent._handle_failure.assert_called_once()
            mock_session.commit.assert_not_called()
            mock_session.close.assert_called_once()

    def test_handle_message_missing_task_record(self):
        """Test SynthesizeAgent when no existing task record is found (results in failure)."""
        agent = make_agent(SynthesizeAgent)
        mock_session = MagicMock()
        # Simulate no existing task record found
        mock_session.query.return_value.filter_by.return_value.first.return_value = None
        with patch(
            "src.audiobook_studio.pipeline.agents.SessionLocal"
        ) as mock_get_db, patch.object(agent, "pipeline") as mock_pipeline:
            mock_get_db.return_value = mock_session
            mock_pipeline.run.return_value = [MagicMock(spec=AudioSegment)]  # This won't be called
            message = MagicMock()
            message.content = {"text": "test", "voice_params": {}, "book_id": 1}
            agent._handle_message(message)
            # Since task_record is None, assigning status will raise AttributeError
            agent._handle_failure.assert_called_once()
            mock_session.commit.assert_not_called()
            mock_session.close.assert_called_once()


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
            "src.audiobook_studio.pipeline.agents.SessionLocal"
        ) as mock_get_db, patch.object(agent, "pipeline") as mock_pipeline:
            mock_get_db.return_value = mock_session
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
            mock_session.close.assert_called_once()
            agent._handle_failure.assert_not_called()

    def test_handle_message_exception(self):
        agent = make_agent(QualityAgent)
        mock_session = MagicMock()
        mock_task4 = MagicMock(spec=TaskRecord)
        with patch(
            "src.audiobook_studio.pipeline.agents.SessionLocal"
        ) as mock_get_db, patch.object(agent, "pipeline") as mock_pipeline:
            mock_get_db.return_value = mock_session
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
            mock_session.close.assert_called_once()

    def test_handle_message_missing_task_record(self):
        """Test QualityAgent when no existing task record is found (results in failure)."""
        agent = make_agent(QualityAgent)
        mock_session = MagicMock()
        # Simulate no existing task record found
        mock_session.query.return_value.filter_by.return_value.first.return_value = None
        with patch(
            "src.audiobook_studio.pipeline.agents.SessionLocal"
        ) as mock_get_db, patch.object(agent, "pipeline") as mock_pipeline:
            mock_get_db.return_value = mock_session
            mock_pipeline.run.return_value = MagicMock(spec=QualityJudgment)  # This won't be called
            message = MagicMock()
            message.content = {
                "audio_segments": [],
                "reference_text": "ref",
                "book_id": 1,
            }
            agent._handle_message(message)
            # Since task_record is None, assigning status will raise AttributeError
            agent._handle_failure.assert_called_once()
            mock_session.commit.assert_not_called()
            mock_session.close.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
