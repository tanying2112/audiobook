"""Tests for api/auto_run.py — schemas, helpers, endpoints, background logic."""

import asyncio
import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.audiobook_studio.api.auto_run  # Ensure module is imported for coverage

# ===========================================================================
# Schema / dataclass tests
# ===========================================================================


class TestAutoRunSchemas:
    def test_auto_run_config_defaults(self):
        from src.audiobook_studio.api.auto_run import AutoRunConfig

        cfg = AutoRunConfig()
        assert cfg.target_difficulty == "B"
        assert cfg.primary_voice_preference == "female"
        assert cfg.speech_rate_preference == "standard"
        assert cfg.cost_limit_usd is None
        assert cfg.quality_threshold == 0.7
        assert cfg.max_regeneration_attempts == 3
        assert cfg.enable_background_music is False
        assert cfg.enable_sfx is True

    def test_auto_run_config_custom(self):
        from src.audiobook_studio.api.auto_run import AutoRunConfig

        cfg = AutoRunConfig(
            target_difficulty="A",
            cost_limit_usd=10.0,
            quality_threshold=0.9,
            enable_background_music=True,
        )
        assert cfg.target_difficulty == "A"
        assert cfg.cost_limit_usd == 10.0
        assert cfg.quality_threshold == 0.9
        assert cfg.enable_background_music is True

    def test_auto_run_status_response_defaults(self):
        from src.audiobook_studio.api.auto_run import AutoRunStatusResponse

        resp = AutoRunStatusResponse(project_id=1, run_id="r1")
        assert resp.status == "pending"
        assert resp.current_stage is None
        assert resp.completed_stages == []
        assert resp.progress == 0.0
        assert resp.cost_usd == 0.0
        assert resp.quality_score is None  # Fixed: was voltage_score
        assert resp.can_pause is True
        assert resp.can_resume is False
        assert resp.can_cancel is True

    def test_auto_run_action_response(self):
        from src.audiobook_studio.api.auto_run import AutoRunActionResponse

        resp = AutoRunActionResponse(
            action="pause",
            status="pending",
            message="ok",
            run_id="r1",
        )
        assert resp.action == "pause"
        assert resp.run_id == "r1"

    def test_intermediate_product(self):
        from src.audiobook_studio.api.auto_run import IntermediateProduct

        p = IntermediateProduct(
            stage="extract",
            project_id=1,
            product_type="text",
            data={"k": "v"},
            created_at="2025-01-01",
        )
        assert p.stage == "extract"
        assert p.can_view is True
        assert p.can_edit is False

    def test_auto_run_start_request_defaults(self):
        from src.audiobook_studio.api.auto_run import AutoRunStartRequest

        req = AutoRunStartRequest()
        assert req.config is not None
        assert req.pause_points is None

    def test_stage_pause_point(self):
        from src.audiobook_studio.api.auto_run import StagePausePoint

        sp = StagePausePoint(stage="extract", pause_after=True, requires_approval=False)
        assert sp.stage == "extract"
        assert sp.pause_after is True
        assert sp.requires_approval is False
