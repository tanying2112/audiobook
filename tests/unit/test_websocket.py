"""Tests for websocket module."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocket
from fastapi.websockets import WebSocketDisconnect

from src.audiobook_studio.api.websocket import (
    ConnectionManager,
    PipelineEventType,
    manager,
    emit_pipeline_event,
    handle_client_message,
    pipeline_websocket,
)


class TestConnectionManager:
    """Tests for ConnectionManager class."""

    def test_init(self):
        """Test ConnectionManager initialization."""
        manager = ConnectionManager()
        assert manager.active_connections == {}
        assert manager.connection_to_project == {}

    @pytest.mark.asyncio
    async def test_connect(self):
        """Test connecting a WebSocket."""
        manager = ConnectionManager()
        websocket = AsyncMock(spec=WebSocket)
        project_id = 1

        await manager.connect(websocket, project_id)

        websocket.accept.assert_awaited_once()
        assert project_id in manager.active_connections
        assert websocket in manager.active_connections[project_id]
        assert manager.connection_to_project[websocket] == project_id

    def test_disconnect(self):
        """Test disconnecting a WebSocket."""
        manager = ConnectionManager()
        websocket = AsyncMock(spec=WebSocket)
        project_id = 1

        # Set up connection
        manager.active_connections[project_id] = {websocket}
        manager.connection_to_project[websocket] = project_id

        # Disconnect
        manager.disconnect(websocket)

        # Check cleanup
        assert websocket not in manager.active_connections.get(project_id, set())
        assert project_id not in manager.connection_to_project
        # Note: We don't remove empty project sets in disconnect for efficiency
        # They are cleaned up in broadcast_to_project when empty

    def test_disconnect_not_connected(self):
        """Test disconnecting a WebSocket that wasn't connected."""
        manager = ConnectionManager()
        websocket = AsyncMock(spec=WebSocket)

        # Should not raise
        manager.disconnect(websocket)

    @pytest.mark.asyncio
    async def test_broadcast_to_project(self):
        """Test broadcasting to a project."""
        manager = ConnectionManager()
        websocket1 = AsyncMock(spec=WebSocket)
        websocket2 = AsyncMock(spec=WebSocket)
        project_id = 1

        # Set up connections
        await manager.connect(websocket1, project_id)
        await manager.connect(websocket2, project_id)

        message = {"type": "test", "data": "message"}
        await manager.broadcast_to_project(project_id, message)

        # Both websockets should receive the message
        websocket1.send_text.assert_awaited_once()
        websocket2.send_text.assert_awaited_once()

        # Check the message content
        call_args_1 = websocket1.send_text.call_args[0][0]
        call_args_2 = websocket2.send_text.call_args[0][0]
        assert json.loads(call_args_1) == message
        assert json.loads(call_args_2) == message

    @pytest.mark.asyncio
    async def test_broadcast_to_project_with_disconnect(self):
        """Test broadcasting handles disconnected clients."""
        manager = ConnectionManager()
        websocket1 = AsyncMock(spec=WebSocket)
        websocket2 = AsyncMock(spec=WebSocket)
        project_id = 1

        # Set up connections
        await manager.connect(websocket1, project_id)
        await manager.connect(websocket2, project_id)

        # Make websocket2 fail on send
        websocket2.send_text.side_effect = Exception("Disconnected")

        message = {"type": "test", "data": "message"}
        await manager.broadcast_to_project(project_id, message)

        # websocket1 should still get the message
        websocket1.send_text.assert_awaited_once()
        # websocket2 should have been attempted
        websocket2.send_text.assert_awaited_once()
        # websocket2 should be disconnected due to failure
        assert websocket2 not in manager.connection_to_project

    @pytest.mark.asyncio
    async def test_send_to_connection(self):
        """Test sending to a specific connection."""
        manager = ConnectionManager()
        websocket = AsyncMock(spec=WebSocket)

        message = {"type": "test", "data": "message"}
        await manager.send_to_connection(websocket, message)

        websocket.send_text.assert_awaited_once()
        call_args = websocket.send_text.call_args[0][0]
        assert json.loads(call_args) == message

    @pytest.mark.asyncio
    async def test_send_to_connection_failure(self):
        """Test sending to a connection that fails."""
        manager = ConnectionManager()
        websocket = AsyncMock(spec=WebSocket)
        websocket.send_text.side_effect = Exception("Send failed")

        message = {"type": "test", "data": "message"}
        # Should not raise, just log error
        await manager.send_to_connection(websocket, message)

        websocket.send_text.assert_awaited_once()


class TestPipelineEventType:
    """Tests for PipelineEventType class."""

    def test_event_types_exist(self):
        """Test that all expected event types exist."""
        assert hasattr(PipelineEventType, "STAGE_ENTER")
        assert hasattr(PipelineEventType, "STAGE_EXIT")
        assert hasattr(PipelineEventType, "STAGE_PROGRESS")
        assert hasattr(PipelineEventType, "CHAPTER_COMPLETE")
        assert hasattr(PipelineEventType, "PARAGRAPH_COMPLETE")
        assert hasattr(PipelineEventType, "ERROR")
        assert hasattr(PipelineEventType, "PAUSED")
        assert hasattr(PipelineEventType, "RESUMED")
        assert hasattr(PipelineEventType, "COMPLETED")

        # Check values
        assert PipelineEventType.STAGE_ENTER == "stage_enter"
        assert PipelineEventType.STAGE_EXIT == "stage_exit"
        assert PipelineEventType.STAGE_PROGRESS == "stage_progress"
        assert PipelineEventType.CHAPTER_COMPLETE == "chapter_complete"
        assert PipelineEventType.PARAGRAPH_COMPLETE == "paragraph_complete"
        assert PipelineEventType.ERROR == "error"
        assert PipelineEventType.PAUSED == "paused"
        assert PipelineEventType.RESUMED == "resumed"
        assert PipelineEventType.COMPLETED == "completed"


class TestEmitPipelineEvent:
    """Tests for emit_pipeline_event function."""

    @pytest.mark.asyncio
    async def test_emit_pipeline_event_minimal(self):
        """Test emitting a pipeline event with minimal parameters."""
        with patch("src.audiobook_studio.api.websocket.manager") as mock_manager:
            mock_manager.broadcast_to_project = AsyncMock()

            await emit_pipeline_event(
                project_id=1,
                event_type="test_event",
            )

            mock_manager.broadcast_to_project.assert_awaited_once()
            args = mock_manager.broadcast_to_project.call_args
            assert args[0][0] == 1  # project_id
            message = args[0][1]
            assert message["type"] == "test_event"
            assert message["project_id"] == 1
            assert "timestamp" in message

    @pytest.mark.asyncio
    async def test_emit_pipeline_event_with_all_params(self):
        """Test emitting a pipeline event with all parameters."""
        with patch("src.audiobook_studio.api.websocket.manager") as mock_manager:
            mock_manager.broadcast_to_project = AsyncMock()

            await emit_pipeline_event(
                project_id=1,
                event_type="stage_enter",
                stage="annotate",
                chapter_id=5,
                paragraph_index=10,
                progress=0.5,
                data={"custom": "data"},
            )

            mock_manager.broadcast_to_project.assert_awaited_once()
            args = mock_manager.broadcast_to_project.call_args
            assert args[0][0] == 1  # project_id
            message = args[0][1]
            assert message["type"] == "stage_enter"
            assert message["project_id"] == 1
            assert message["stage"] == "annotate"
            assert message["chapter_id"] == 5
            assert message["paragraph_index"] == 10
            assert message["progress"] == 0.5
            assert message["data"] == {"custom": "data"}
            assert "timestamp" in message


class TestHandleClientMessage:
    """Tests for handle_client_message function."""

    @pytest.mark.asyncio
    async def test_handle_pause_message(self):
        """Handling pause message."""
        websocket = AsyncMock()
        project_id = 1
        message = {"type": "pause"}

        await handle_client_message(websocket, project_id, message)

        websocket.send_text.assert_awaited_once()
        call_args = websocket.send_text.call_args[0][0]
        response = json.loads(call_args)
        assert response["type"] == "ack"
        assert response["action"] == "pause"
        assert response["status"] == "pending_implementation"

    @pytest.mark.asyncio
    async def test_handle_resume_message(self):
        """Handling resume message."""
        websocket = AsyncMock()
        project_id = 1
        message = {"type": "resume"}

        await handle_client_message(websocket, project_id, message)

        websocket.send_text.assert_awaited_once()
        call_args = websocket.send_text.call_args[0][0]
        response = json.loads(call_args)
        assert response["type"] == "ack"
        assert response["action"] == "resume"
        assert response["status"] == "pending_implementation"

    @pytest.mark.asyncio
    async def test_handle_status_message(self):
        """Handling status message."""
        websocket = AsyncMock()
        project_id = 1
        message = {"type": "status"}

        await handle_client_message(websocket, project_id, message)

        websocket.send_text.assert_awaited_once()
        call_args = websocket.send_text.call_args[0][0]
        response = json.loads(call_args)
        assert response["type"] == "status"
        assert response["project_id"] == 1
        assert response["status"] == "unknown"

    @pytest.mark.asyncio
    async def test_handle_unknown_message(self):
        """Handling unknown message type."""
        websocket = AsyncMock()
        project_id = 1
        message = {"type": "unknown"}

        await handle_client_message(websocket, project_id, message)

        # Should not send any response for unknown message types
        websocket.send_text.assert_not_awaited()


class TestPipelineWebsocket:
    """Tests for pipeline_websocket endpoint."""

    @pytest.mark.asyncio
    async def test_pipeline_websocket_connect_and_disconnect(self):
        """Test WebSocket connection and disconnection."""
        websocket = AsyncMock()
        project_id = 1

        with patch("src.audiobook_studio.api.websocket.manager") as mock_manager:
            mock_manager.connect = AsyncMock()
            mock_manager.disconnect = MagicMock()

            # Simulate WebSocketDisconnect on first receive
            websocket.receive_text.side_effect = WebSocketDisconnect()

            await pipeline_websocket(websocket, project_id)

            # Check connection handling
            mock_manager.connect.assert_awaited_once_with(websocket, project_id)
            mock_manager.disconnect.assert_called_once_with(websocket)

            # Check initial connection message
            websocket.send_text.assert_awaited()
            call_args = websocket.send_text.call_args[0][0]
            response = json.loads(call_args)
            assert response["type"] == "connected"
            assert response["project_id"] == 1
            assert "timestamp" in response

    @pytest.mark.asyncio
    async def test_pipeline_websocket_with_messages(self):
        """Test WebSocket handling client messages."""
        websocket = AsyncMock()
        project_id = 1

        with patch("src.audiobook_studio.api.websocket.manager") as mock_manager:
            mock_manager.connect = AsyncMock()
            mock_manager.disconnect = MagicMock()
            with patch("src.audiobook_studio.api.websocket.handle_client_message") as mock_handler:
                # First message: a client message
                # Second message: WebSocketDisconnect to end the loop
                websocket.receive_text.side_effect = [
                    json.dumps({"type": "pause"}),
                    WebSocketDisconnect()
                ]

                await pipeline_websocket(websocket, project_id)

                # Check that handle_client_message was called
                mock_handler.assert_called_once()
                args = mock_handler.call_args
                assert args[0][0] == websocket
                assert args[0][1] == project_id
                assert args[0][2] == {"type": "pause"}

    @pytest.mark.asyncio
    async def test_pipeline_websocket_keepalive(self):
        """Test WebSocket keepalive on timeout."""
        websocket = AsyncMock()
        project_id = 1

        with patch("src.audiobook_studio.api.websocket.manager") as mock_manager:
            mock_manager.connect = AsyncMock()
            mock_manager.disconnect = MagicMock()
            with patch("src.audiobook_studio.api.websocket.asyncio.wait_for") as mock_wait_for:
                # First call: timeout (to trigger keepalive)
                # Second call: WebSocketDisconnect to end
                mock_wait_for.side_effect = [
                    asyncio.TimeoutError(),
                    WebSocketDisconnect()
                ]

                await pipeline_websocket(websocket, project_id)

                # Should have sent keepalive message
                websocket.send_text.assert_any_await()
                # Check for keepalive message
                call_args_list = [call[0][0] for call in websocket.send_text.call_args_list]
                keepalive_found = any(
                    json.loads(arg)["type"] == "keepalive"
                    for arg in call_args_list
                    if arg.startswith('{')
                )
                assert keepalive_found

    @pytest.mark.asyncio
    async def test_pipeline_websocket_exception_handling(self):
        """Test WebSocket exception handling."""
        websocket = AsyncMock()
        project_id = 1

        with patch("src.audiobook_studio.api.websocket.manager") as mock_manager:
            mock_manager.connect = AsyncMock()
            mock_manager.disconnect = MagicMock()
            websocket.receive_text.side_effect = Exception("Test error")

            await pipeline_websocket(websocket, project_id)

            # Should still disconnect on exception
            mock_manager.disconnect.assert_called_once_with(websocket)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])