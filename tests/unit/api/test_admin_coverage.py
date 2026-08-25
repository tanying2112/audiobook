"""Additional tests for admin module to boost coverage."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from src.audiobook_studio.api.admin import (
    router,
    warmup_engines,
)

class TestAdminEndpoints:
    """Test admin endpoints with mocked dependencies."""
    
    @pytest.mark.asyncio
    async def test_warmup_engines(self):
        """Test warmup_engines endpoint."""
        mock_background_tasks = MagicMock()
        
        with patch('src.audiobook_studio.di.get_app_container') as mock_container:
            mock_registry = AsyncMock()
            mock_registry.warmup = AsyncMock(return_value={"kokoro": True, "edge": False})
            
            mock_container_instance = MagicMock()
            mock_container_instance.get.return_value = mock_registry
            mock_container.return_value = mock_container_instance
            
            result = await warmup_engines(mock_background_tasks)
            assert result == {"status": "warming_up"}
            mock_background_tasks.add_task.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_warmup_engines_no_registry(self):
        """Test warmup when no registry in container."""
        mock_background_tasks = MagicMock()
        
        with patch('src.audiobook_studio.di.get_app_container') as mock_container:
            mock_container_instance = MagicMock()
            mock_container_instance.get.return_value = None
            mock_container.return_value = mock_container_instance
            
            result = await warmup_engines(mock_background_tasks)
            assert result == {"status": "warming_up"}
            mock_background_tasks.add_task.assert_called_once()

    def test_router_tags(self):
        """Test router has correct tags."""
        assert router.tags == ["admin"]
    
    def test_router_routes(self):
        """Test router has warmup route."""
        routes = [r.path for r in router.routes]
        assert "/admin/warmup" in routes
