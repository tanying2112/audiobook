"""Tests for provider_router to boost coverage."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.audiobook_studio.api.provider_router import (
    router,
    _db_provider_to_config,
    build_provider_configs_from_db,
    sync_router_from_db,
    trigger_router_reload,
    _DB_TYPE_TO_ENUM,
    _ALL_STAGES,
)
from src.audiobook_studio.models.provider import Provider, Model as ModelModel
from src.audiobook_studio.llm.config_loader import ProviderConfig, ProviderType
from src.audiobook_studio.llm.router import StageName


class TestDBTypeToEnum:
    """Test the _DB_TYPE_TO_ENUM mapping."""

    def test_known_types_mapped(self):
        """Test that known provider types are mapped correctly."""
        assert _DB_TYPE_TO_ENUM["openai"] == "OPENAI"
        assert _DB_TYPE_TO_ENUM["anthropic"] == "ANTHROPIC"
        assert _DB_TYPE_TO_ENUM["groq"] == "GROQ"
        assert _DB_TYPE_TO_ENUM["openrouter"] == "OPENROUTER"
        assert _DB_TYPE_TO_ENUM["ollama"] == "OLLAMA"

    def test_unknown_type_fallbacks_to_openai(self):
        """Test that unknown types fall back to OPENAI."""
        assert _DB_TYPE_TO_ENUM.get("unknown_provider") is None
        # The fallback logic is in _db_provider_to_config, not the dict itself


class TestAllStages:
    """Test _ALL_STAGES constant."""

    def test_all_stages_populated(self):
        """Test that _ALL_STAGES contains all StageName values."""
        assert len(_ALL_STAGES) > 0
        assert all(isinstance(s, StageName) for s in _ALL_STAGES)


class TestDBProviderToConfig:
    """Test _db_provider_to_config function."""

    def test_known_provider_type(self):
        """Test mapping for known provider type."""
        provider = MagicMock()
        provider.provider_type = "openai"
        provider.models = []
        provider.default_model = "gpt-4"
        provider.name = "test-provider"
        provider.api_key = "test-key"
        provider.api_base = "https://api.openai.com"
        provider.sort_priority = 10
        provider.is_enabled = True

        with patch.dict("os.environ", {}, clear=True):
            config = _db_provider_to_config(provider)

        assert config.name == "test-provider"
        assert config.provider == "OPENAI"
        assert config.model == "gpt-4"
        assert config.api_key_env == "PROVIDER_DB_TEST_PROVIDER_KEY"
        assert config.base_url == "https://api.openai.com"
        assert config.priority == 10
        assert config.stages == list(StageName)
        assert config.enabled is True

    def test_unknown_provider_type_fallbacks_to_openai(self):
        """Test that unknown provider type falls back to OPENAI."""
        provider = MagicMock()
        provider.provider_type = "unknown_type"
        provider.models = []
        provider.default_model = "test-model"
        provider.name = "unknown"
        provider.api_key = None
        provider.api_base = None
        provider.sort_priority = 100
        provider.is_enabled = True

        config = _db_provider_to_config(provider)
        assert config.provider == "OPENAI"  # fallback

    def test_default_model_fallback_to_first_model(self):
        """Test default_model falls back to first enabled model."""
        model = MagicMock()
        model.is_enabled = True
        model.model_id = "first-model"
        model.name = "first"

        provider = MagicMock()
        provider.provider_type = "openai"
        provider.models = [model]
        provider.default_model = None
        provider.name = "test"
        provider.api_key = None
        provider.api_base = None
        provider.sort_priority = 10
        provider.is_enabled = True

        config = _db_provider_to_config(provider)
        assert config.model == "first-model"

    def test_api_key_exported_to_env(self):
        """Test that API key is exported to environment variable."""
        provider = MagicMock()
        provider.provider_type = "anthropic"
        provider.models = []
        provider.default_model = "claude-3"
        provider.name = "test-anthropic"
        provider.api_key = "sk-test-key"
        provider.api_base = "https://api.anthropic.com"
        provider.sort_priority = 50
        provider.is_enabled = True
        provider.models = []

        with patch.dict("os.environ", {}, clear=True):
            config = _db_provider_to_config(provider)
            import os
            assert os.environ.get("PROVIDER_DB_TEST_ANTHROPIC_KEY") == "sk-test-key"

    def test_no_models_fallback_to_name(self):
        """Test model falls back to provider name when no models."""
        provider = MagicMock()
        provider.provider_type = "openai"
        provider.models = []
        provider.default_model = None
        provider.name = "fallback-provider"
        provider.api_key = None
        provider.api_base = None
        provider.sort_priority = 10
        provider.is_enabled = True

        config = _db_provider_to_config(provider)
        assert config.model == "fallback-provider"


class TestBuildProviderConfigsFromDB:
    """Test build_provider_configs_from_db function."""

    @pytest.mark.asyncio
    async def test_build_provider_configs_from_db(self):
        """Test building provider configs from DB."""
        provider = MagicMock()
        provider.provider_type = "openai"
        provider.models = []
        provider.default_model = "gpt-4"
        provider.name = "test"
        provider.api_key = "test-key"
        provider.api_base = "https://api.openai.com"
        provider.sort_priority = 10
        provider.is_enabled = True
        provider.models = []

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [provider]
        db.execute = AsyncMock(return_value=mock_result)

        with patch("src.audiobook_studio.api.provider_router._db_provider_to_config") as mock_map:
            mock_map.return_value = MagicMock()
            configs = await build_provider_configs_from_db(db)

            db.execute.assert_called_once()
            assert len(configs) == 1
            mock_map.assert_called_once_with(provider)

    @pytest.mark.asyncio
    async def test_build_provider_configs_empty_db(self):
        """Test building configs when no providers in DB."""
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)

        configs = await build_provider_configs_from_db(db)
        assert configs == []


class TestSyncRouterFromDB:
    """Test sync_router_from_db function."""

    @pytest.mark.asyncio
    async def test_sync_router_from_db_success(self):
        """Test successful router sync."""
        db = AsyncMock()

        with (
            patch("src.audiobook_studio.api.provider_router.build_provider_configs_from_db") as mock_build,
            patch("src.audiobook_studio.api.provider_router.get_llm_router") as mock_get_router,
        ):
            mock_configs = [MagicMock()]
            mock_build.return_value = mock_configs

            mock_router = MagicMock()
            mock_router.apply_provider_configs = MagicMock()
            mock_get_router.return_value = mock_router

            await sync_router_from_db(MagicMock())

            mock_build.assert_called_once()
            mock_get_router.assert_called_once()
            mock_router.apply_provider_configs.assert_called_once_with(mock_configs)

    @pytest.mark.asyncio
    async def test_sync_router_from_db_exception_handled(self):
        """Test that exceptions are caught and logged."""
        db = MagicMock()

        with (
            patch("src.audiobook_studio.api.provider_router.build_provider_configs_from_db", side_effect=Exception("DB error")),
            patch("src.audiobook_studio.api.provider_router.logger") as mock_logger,
        ):
            # Should not raise
            await sync_router_from_db(db)

            mock_logger.warning.assert_called_once()
            assert "router sync skipped" in str(mock_logger.warning.call_args)


class TestTriggerRouterReload:
    """Test trigger_router_reload function."""

    def test_trigger_router_reload_success(self):
        """Test successful router reload."""
        with patch("src.audiobook_studio.api.provider_router.reload_llm_router") as mock_reload:
            trigger_router_reload()
            mock_reload.assert_called_once()

    def test_trigger_router_reload_exception_handled(self):
        """Test that exceptions are caught and logged."""
        with (
            patch("src.audiobook_studio.api.provider_router.reload_llm_router", side_effect=Exception("reload failed")),
            patch("src.audiobook_studio.api.provider_router.logger") as mock_logger,
        ):
            trigger_router_reload()
            mock_logger.warning.assert_called_once()
            assert "router reload skipped" in str(mock_logger.warning.call_args)


class TestRouterEndpoints:
    """Test router endpoints (basic structure)."""

    def test_router_tags(self):
        """Test router has correct tags."""
        assert router.tags == ["provider-management"]

    def test_router_routes(self):
        """Test router has expected routes."""
        routes = [r.path for r in router.routes]
        assert "/reload" in routes
        # CRUD routes
        assert any("/{provider_id}" in r.path for r in routes)
        assert any("/models/" in r.path for r in routes)


class TestProviderCRUD:
    """Test Provider CRUD endpoints (mocked)."""

    @pytest.mark.asyncio
    async def test_create_provider(self):
        """Test create_provider endpoint."""
        payload = MagicMock()
        payload.name = "test"
        payload.display_name = "Test"
        payload.description = "Test"
        payload.provider_type = "openai"
        payload.api_base = "https://api.openai.com"
        payload.api_key = "test-key"
        payload.auth_type = "bearer"
        payload.default_model = "gpt-4"
        payload.max_tokens = 4096
        payload.temperature = 0.7
        payload.is_enabled = True
        payload.sort_priority = 10

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        with (
            patch("src.audiobook_studio.api.provider_router.ProviderModel") as mock_provider_model,
            patch("src.audiobook_studio.api.provider_router.sync_router_from_db") as mock_sync,
        ):
            mock_provider = MagicMock()
            mock_provider_model.return_value = mock_provider
            mock_provider.id = 1

            db.add = MagicMock()
            db.commit = AsyncMock()
            db.refresh = AsyncMock()

            from src.audiobook_studio.api.provider_router import create_provider
            result = await create_provider(payload, db)

            mock_provider_model.assert_called_once()
            db.add.assert_called_once()
            db.commit.assert_called_once()
            mock_sync.assert_called_once()


class TestModelCRUD:
    """Test Model CRUD endpoints (mocked)."""

    @pytest.mark.asyncio
    async def test_create_model(self):
        """Test create_model endpoint."""
        payload = MagicMock()
        payload.name = "gpt-4"
        payload.model_id = "gpt-4"
        payload.version = "1.0"
        payload.context_window = 8192
        payload.instructions = None
        payload.parameters = None
        payload.is_enabled = True
        payload.sort_priority = 10

        db = AsyncMock()
        provider = MagicMock()
        provider.name = "openai"
        provider.id = 1

        # Provider lookup
        mock_prov_result = MagicMock()
        mock_prov_result.scalar_one_or_none.return_value = MagicMock(name="openai")
        
        # Model conflict check
        mock_model_result = MagicMock()
        mock_model_result.scalar_one_or_none.return_value = None

        db.execute = AsyncMock(side_effect=[mock_prov_result, mock_model_result])
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        with patch("src.audiobook_studio.api.provider_router.sync_router_from_db") as mock_sync:
            from src.audiobook_studio.api.provider_router import create_model
            result = await create_model(1, MagicMock(name="gpt-4"), db)

            db.add.assert_called_once()
            db.commit.assert_called_once()
            mock_sync.assert_called_once()


class TestHotReload:
    """Test hot-reload endpoint."""

    @pytest.mark.asyncio
    async def test_reload_providers(self):
        """Test reload_providers endpoint."""
        db = AsyncMock()

        with (
            patch("src.audiobook_studio.api.provider_router.sync_router_from_db") as mock_sync,
            patch("src.audiobook_studio.api.provider_router.trigger_router_reload") as mock_reload,
        ):
            mock_sync.return_value = None
            mock_reload.return_value = None

            from src.audiobook_studio.api.provider_router import reload_providers
            result = await reload_providers(db)

            assert result["db_sync"] == "ok"
            assert result["yaml_reload"] == "ok"
            assert result["errors"] == []
            mock_sync.assert_called_once_with(db)
            mock_reload.assert_called_once()

    @pytest.mark.asyncio
    async def test_reload_providers_with_errors(self):
        """Test reload_providers handles errors gracefully."""
        db = AsyncMock()

        with (
            patch("src.audiobook_studio.api.provider_router.sync_router_from_db", side_effect=Exception("DB error")),
            patch("src.audiobook_studio.api.provider_router.trigger_router_reload", side_effect=Exception("YAML error")),
        ):
            from src.audiobook_studio.api.provider_router import reload_providers
            result = await reload_providers(db)

            assert result["db_sync"] == "failed"
            assert result["yaml_reload"] == "failed"
            assert len(result["errors"]) == 2


class TestRouterConstants:
    """Test router constants."""

    def test_db_type_to_enum_completeness(self):
        """Test that common provider types are mapped."""
        expected_keys = [
            "openai", "anthropic", "groq", "deepseek", "openrouter",
            "ollama", "gemini", "cerebras", "alibaba", "zhipu",
            "siliconcloud", "mistral", "volcengine", "tencent", "cohere",
            "together", "huggingface", "baidu_qianfan", "cloudflare",
            "github", "duck2api", "nvidia_nemotron", "fcc_gateway",
            "fcc", "nemotron",
        ]
        for key in expected_keys:
            assert key in _DB_TYPE_TO_ENUM, f"Missing mapping for {key}"

    def test_all_stages_populated(self):
        """Test that _ALL_STAGES is populated from StageName."""
        assert len(_ALL_STAGES) > 0
        # Should contain all StageName enum values
        from src.audiobook_studio.llm.router import StageName
        assert len(_ALL_STAGES) == len(list(StageName))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
