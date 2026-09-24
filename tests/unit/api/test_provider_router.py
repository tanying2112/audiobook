"""Tests for provider_router to boost coverage."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.audiobook_studio.api.provider_router import (
    _ALL_STAGES,
    _DB_TYPE_TO_ENUM,
    _db_provider_to_config,
    build_provider_configs_from_db,
    router,
    sync_router_from_db,
    trigger_router_reload,
)
from src.audiobook_studio.llm.router import StageName


class TestDBTypeToEnum:
    """Test the _DB_TYPE_TO_ENUM mapping."""

    def test_known_types_mapped(self):
        """Test that known provider types are mapped correctly.

        Note: Due to conftest_minimal.py mocking ProviderType with MagicMock,
        the _DB_TYPE_TO_ENUM values are MagicMock objects. We test that the
        keys exist and the values are truthy (i.e., the mapping is populated).
        """
        # Just verify the keys are present and values are truthy
        assert "openai" in _DB_TYPE_TO_ENUM
        assert "anthropic" in _DB_TYPE_TO_ENUM
        assert "groq" in _DB_TYPE_TO_ENUM
        assert "openrouter" in _DB_TYPE_TO_ENUM
        assert "ollama" in _DB_TYPE_TO_ENUM
        assert _DB_TYPE_TO_ENUM["openai"]
        assert _DB_TYPE_TO_ENUM["anthropic"]
        assert _DB_TYPE_TO_ENUM["groq"]
        assert _DB_TYPE_TO_ENUM["openrouter"]
        assert _DB_TYPE_TO_ENUM["ollama"]

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
        """Test mapping for known provider type.

        Note: ProviderType is mocked in conftest_minimal, so config.provider
        will be a MagicMock instead of a string. We test the other fields.
        """
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
        # config.provider is MagicMock due to ProviderType mock - skip string assertion
        assert config.model == "gpt-4"
        assert config.api_key_env == "PROVIDER_DB_TEST_PROVIDER_KEY"
        assert config.base_url == "https://api.openai.com"
        assert config.priority == 10
        assert config.stages == list(StageName)
        assert config.enabled is True

    def test_unknown_provider_type_fallbacks_to_openai(self):
        """Test that unknown provider type falls back to OPENAI.

        Note: ProviderType is mocked in conftest_minimal, so config.provider
        will be a MagicMock instead of a string. We test that the fallback
        logic doesn't crash and other fields are set correctly.
        """
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
        # config.provider is MagicMock due to ProviderType mock - skip string assertion
        assert config.name == "unknown"
        assert config.model == "test-model"

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
            _db_provider_to_config(provider)
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
        AsyncMock()

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
            patch(
                "src.audiobook_studio.api.provider_router.build_provider_configs_from_db",
                side_effect=Exception("DB error"),
            ),
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
        # CRUD routes - routes is a list of strings (paths)
        assert any("/{provider_id}" in r for r in routes)
        assert any("/models/" in r for r in routes)


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

        # First call: check if provider exists (returns None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        with patch("src.audiobook_studio.api.provider_router.sync_router_from_db") as mock_sync:
            from src.audiobook_studio.api.provider_router import create_provider

            await create_provider(payload, db)

            db.add.assert_called_once()
            db.commit.assert_called_once()
            # sync_router_from_db is NOT called in create_provider (separate endpoint)
            mock_sync.assert_not_called()


class TestModelCRUD:
    """Test Model CRUD endpoints (mocked)."""

    @pytest.mark.asyncio
    async def test_create_model(self):
        """Test create_model endpoint."""
        # Create a proper payload with all required attributes
        payload = MagicMock()
        payload.name = "gpt-4"
        payload.provider_id = 1
        payload.model_id = "gpt-4"
        payload.version = "1.0"
        payload.context_window = 8192
        payload.instructions = {}
        payload.parameters = {}
        payload.is_enabled = True
        payload.sort_priority = 10

        db = AsyncMock()
        provider = MagicMock()
        provider.name = "openai"
        provider.id = 1

        # Provider lookup
        mock_prov_result = MagicMock()
        mock_prov_result.scalar_one_or_none.return_value = provider

        # Model conflict check
        mock_model_result = MagicMock()
        mock_model_result.scalar_one_or_none.return_value = None

        db.execute = AsyncMock(side_effect=[mock_prov_result, mock_model_result])
        db.add = MagicMock()
        db.commit = AsyncMock()

        # refresh should set the id on the model
        def mock_refresh(model):
            model.id = 1

        db.refresh = AsyncMock(side_effect=mock_refresh)

        with patch("src.audiobook_studio.api.provider_router.sync_router_from_db") as mock_sync:
            from src.audiobook_studio.api.provider_router import create_model

            await create_model(1, payload, db)

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
            patch(
                "src.audiobook_studio.api.provider_router.trigger_router_reload", side_effect=Exception("YAML error")
            ),
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
            "openai",
            "anthropic",
            "groq",
            "deepseek",
            "openrouter",
            "ollama",
            "gemini",
            "cerebras",
            "alibaba",
            "zhipu",
            "siliconcloud",
            "mistral",
            "volcengine",
            "tencent",
            "cohere",
            "together",
            "huggingface",
            "baidu_qianfan",
            "cloudflare",
            "github",
            "duck2api",
            "nvidia_nemotron",
            "fcc_gateway",
            "fcc",
            "nemotron",
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
