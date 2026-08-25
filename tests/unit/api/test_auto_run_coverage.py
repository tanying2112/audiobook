"""Additional tests for auto_run module to boost coverage."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

# Import the module directly for coverage
from src.audiobook_studio.api.auto_run import (
    _generate_run_id,
    _get_checkpoint_manager,
    _stage_order,
    _active_runs,
    AutoRunConfig,
    AutoRunStatusResponse,
    StagePausePoint,
    AutoRunStartRequest,
    AutoRunActionResponse,
    AutopilotConfig,
    IntermediateProduct,
)

class TestAutoRunHelpers:
    """Test helper functions and data models."""
    
    def test_generate_run_id(self):
        """Test run ID generation."""
        run_id = _generate_run_id(123)
        assert run_id.startswith("autorun_123_")
        assert len(run_id) > 20
    
    def test_stage_order(self):
        """Test stage order constant."""
        assert _stage_order == [
            "extract", "analyze", "annotate", "edit", 
            "audio_postprocess", "synthesize", "quality"
        ]
    
    def test_active_runs_dict(self):
        """Test active runs global."""
        assert isinstance(_active_runs, dict)
    
    def test_get_checkpoint_manager(self):
        """Test checkpoint manager factory."""
        with patch('src.audiobook_studio.api.auto_run.CheckpointManager') as mock_cm:
            mgr = _get_checkpoint_manager(42)
            mock_cm.assert_called_once_with(42)
            assert mgr == mock_cm.return_value

class TestAutoRunConfig:
    """Test AutoRunConfig model."""
    
    def test_default_config(self):
        """Test default config values."""
        config = AutoRunConfig()
        assert config.target_difficulty == "B"
        assert config.primary_voice_preference == "female"
        assert config.speech_rate_preference == "standard"
        assert config.cost_limit_usd is None
        assert config.quality_threshold == 0.7
        assert config.max_regeneration_attempts == 3
        assert config.enable_background_music is False
        assert config.enable_sfx is True
    
    def test_custom_config(self):
        """Test custom config values."""
        config = AutoRunConfig(
            target_difficulty="A",
            primary_voice_preference="male",
            speech_rate_preference="fast",
            cost_limit_usd=10.0,
            quality_threshold=0.9,
            max_regeneration_attempts=5,
            enable_background_music=True,
            enable_sfx=False,
        )
        assert config.target_difficulty == "A"
        assert config.primary_voice_preference == "male"
        assert config.speech_rate_preference == "fast"
        assert config.cost_limit_usd == 10.0
        assert config.quality_threshold == 0.9
        assert config.max_regeneration_attempts == 5
        assert config.enable_background_music is True
        assert config.enable_sfx is False

class TestAutoRunStatusResponse:
    """Test AutoRunStatusResponse model."""
    
    def test_default_status(self):
        """Test default status values."""
        resp = AutoRunStatusResponse(project_id=1, run_id="test_run")
        assert resp.project_id == 1
        assert resp.run_id == "test_run"
        assert resp.status == "pending"
        assert resp.current_stage is None
        assert resp.completed_stages == []
        assert resp.progress == 0.0
        assert resp.cost_usd == 0.0
        assert resp.quality_score is None
        assert resp.error_message is None
        assert resp.started_at is None
        assert resp.completed_at is None
        assert resp.can_pause is True
        assert resp.can_resume is False
        assert resp.can_cancel is True
    
    def test_custom_status(self):
        """Test custom status values."""
        resp = AutoRunStatusResponse(
            project_id=2,
            run_id="custom_run",
            status="running",
            current_stage="synthesize",
            completed_stages=["extract", "analyze"],
            progress=0.5,
            cost_usd=5.0,
            quality_score=0.85,
            error_message="test error",
            started_at="2024-01-01T00:00:00Z",
            completed_at="2024-01-01T01:00:00Z",
            can_pause=False,
            can_resume=True,
            can_cancel=False,
        )
        assert resp.status == "running"
        assert resp.current_stage == "synthesize"
        assert resp.completed_stages == ["extract", "analyze"]
        assert resp.progress == 0.5
        assert resp.cost_usd == 5.0
        assert resp.quality_score == 0.85
        assert resp.error_message == "test error"
        assert resp.can_pause is False
        assert resp.can_resume is True
        assert resp.can_cancel is False

class TestStagePausePoint:
    """Test StagePausePoint model."""
    
    def test_default_pause_point(self):
        """Test default pause point."""
        pp = StagePausePoint(stage="synthesize")
        assert pp.stage == "synthesize"
        assert pp.pause_after is True
        assert pp.requires_approval is False
    
    def test_custom_pause_point(self):
        """Test custom pause point."""
        pp = StagePausePoint(
            stage="edit",
            pause_after=False,
            requires_approval=True,
        )
        assert pp.stage == "edit"
        assert pp.pause_after is False
        assert pp.requires_approval is True

class TestAutoRunStartRequest:
    """Test AutoRunStartRequest model."""
    
    def test_default_request(self):
        """Test default request."""
        req = AutoRunStartRequest()
        assert isinstance(req.config, AutoRunConfig)
        assert req.pause_points is None
    
    def test_request_with_pause_points(self):
        """Test request with pause points."""
        pp = [StagePausePoint(stage="synthesize")]
        req = AutoRunStartRequest(pause_points=pp)
        assert req.pause_points == pp

class TestAutoRunActionResponse:
    """Test AutoRunActionResponse model."""
    
    def test_action_response(self):
        """Test action response."""
        resp = AutoRunActionResponse(
            action="pause",
            status="pending",
            message="Pipeline will pause",
            run_id="run_123",
        )
        assert resp.action == "pause"
        assert resp.status == "pending"
        assert resp.message == "Pipeline will pause"
        assert resp.run_id == "run_123"

class TestAutopilotConfig:
    """Test AutopilotConfig model."""
    
    def test_autopilot_config(self):
        """Test autopilot config."""
        config = AutopilotConfig(
            target_difficulty="B",
            primary_voice_preference="female",
            speech_rate_preference="standard",
            cost_limit_usd=5.0,
            quality_threshold=0.8,
            max_regeneration_attempts=3,
            enable_background_music=True,
            enable_sfx=True,
            reasoning="Test reasoning",
            confidence=0.9,
        )
        assert config.target_difficulty == "B"
        assert config.confidence == 0.9

class TestIntermediateProduct:
    """Test IntermediateProduct model."""
    
    def test_intermediate_product(self):
        """Test intermediate product."""
        prod = IntermediateProduct(
            stage="extract",
            project_id=1,
            chapter_id=2,
            product_type="text",
            data={"raw_text": "test"},
            created_at="2024-01-01T00:00:00Z",
            can_view=True,
            can_edit=False,
        )
        assert prod.stage == "extract"
        assert prod.project_id == 1
        assert prod.chapter_id == 2
        assert prod.product_type == "text"
        assert prod.data == {"raw_text": "test"}
        assert prod.can_view is True
        assert prod.can_edit is False

class TestGenerateAutopilotConfig:
    """Test _generate_autopilot_config function."""
    
    @pytest.mark.asyncio
    async def test_generate_autopilot_config(self):
        """Test autopilot config generation."""
        from src.audiobook_studio.api.auto_run import _generate_autopilot_config
        from sqlalchemy import select
        
        # Mock project with chapters using proper mock objects
        mock_project = MagicMock()
        
        # Create chapter mock that supports iteration
        mock_chapter = MagicMock()
        mock_chapter.raw_text = "test text"
        mock_chapter.extracted_text = "extracted text"
        mock_chapter.analyzed_json = None
        
        # Make chapters iterable
        mock_project.chapters = [mock_chapter]
        
        mock_db = AsyncMock()
        # mock_result must be MagicMock (not AsyncMock) because scalar_one_or_none is sync
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        with patch('src.audiobook_studio.api.auto_run.select', side_effect=select):
            config = await _generate_autopilot_config(1, mock_db)
            assert isinstance(config, AutopilotConfig)
            assert config.target_difficulty in ["A", "B", "C", "D"]
            assert config.primary_voice_preference in ["male", "female", "neutral"]
            assert config.speech_rate_preference in ["slow", "standard", "fast"]
            assert config.cost_limit_usd >= 1.0
            assert config.cost_limit_usd <= 50.0
            assert 0 <= config.quality_threshold <= 1
            assert config.max_regeneration_attempts in [2, 3]
            assert isinstance(config.enable_background_music, bool)
            assert config.enable_sfx is True
            assert config.confidence == 0.85
