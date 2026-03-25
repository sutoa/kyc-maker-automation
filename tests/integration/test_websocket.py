"""Integration tests for WebSocket event flow.

Tests:
- WebSocket connection and disconnection
- Event broadcasting to connected clients
- Event types and payloads
- Multiple client handling
"""

import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.websocket import (
    ConnectionManager,
    WebSocketEvent,
    WebSocketEventType,
    create_agent_completed_event,
    create_agent_started_event,
    create_critic_decision_event,
    create_retry_triggered_event,
    create_workflow_completed_event,
    create_workflow_failed_event,
    manager,
)
from src.core.events import (
    WorkflowEventEmitter,
    create_event_emitter,
    get_event_emitter,
    remove_event_emitter,
)


# --- Test Fixtures ---


@pytest.fixture
def connection_manager():
    """Create a fresh ConnectionManager for testing."""
    return ConnectionManager()


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket connection."""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    ws.send_text = AsyncMock()
    ws.receive_text = AsyncMock()
    return ws


@pytest.fixture
def workflow_id():
    """Generate a test workflow ID."""
    return "test-workflow-123"


@pytest.fixture
def event_emitter(workflow_id):
    """Create an event emitter for testing."""
    emitter = create_event_emitter(workflow_id)
    yield emitter
    remove_event_emitter(workflow_id)


# --- WebSocket Event Types Tests ---


class TestWebSocketEventTypes:
    """Tests for WebSocket event type definitions."""

    def test_all_event_types_defined(self):
        """Test that all required event types are defined."""
        assert WebSocketEventType.AGENT_STARTED == "agent_started"
        assert WebSocketEventType.AGENT_COMPLETED == "agent_completed"
        assert WebSocketEventType.CRITIC_DECISION == "critic_decision"
        assert WebSocketEventType.RETRY_TRIGGERED == "retry_triggered"
        assert WebSocketEventType.WORKFLOW_STARTED == "workflow_started"
        assert WebSocketEventType.WORKFLOW_COMPLETED == "workflow_completed"
        assert WebSocketEventType.WORKFLOW_FAILED == "workflow_failed"
        assert WebSocketEventType.CONNECTED == "connected"
        assert WebSocketEventType.ERROR == "error"

    def test_websocket_event_model(self, workflow_id):
        """Test WebSocketEvent model creation."""
        event = WebSocketEvent(
            event=WebSocketEventType.AGENT_STARTED,
            workflow_id=workflow_id,
            timestamp=datetime.utcnow(),
            data={"agent_name": "extractor"},
        )

        assert event.event == WebSocketEventType.AGENT_STARTED
        assert event.workflow_id == workflow_id
        assert event.data["agent_name"] == "extractor"

    def test_websocket_event_serialization(self, workflow_id):
        """Test WebSocketEvent JSON serialization."""
        event = WebSocketEvent(
            event=WebSocketEventType.AGENT_STARTED,
            workflow_id=workflow_id,
            timestamp=datetime.utcnow(),
            data={"agent_name": "extractor", "retry_count": 0},
        )

        json_data = event.model_dump(mode="json")

        assert json_data["event"] == "agent_started"
        assert json_data["workflow_id"] == workflow_id
        assert "timestamp" in json_data
        assert json_data["data"]["agent_name"] == "extractor"


# --- Event Builder Tests ---


class TestEventBuilders:
    """Tests for event builder functions."""

    def test_create_agent_started_event(self, workflow_id):
        """Test agent_started event creation."""
        event = create_agent_started_event(
            workflow_id=workflow_id,
            agent_name="extractor",
            retry_count=1,
        )

        assert event.event == WebSocketEventType.AGENT_STARTED
        assert event.workflow_id == workflow_id
        assert event.data["agent_name"] == "extractor"
        assert event.data["retry_count"] == 1

    def test_create_agent_completed_event(self, workflow_id):
        """Test agent_completed event creation."""
        event = create_agent_completed_event(
            workflow_id=workflow_id,
            agent_name="extractor",
            duration_ms=1500.5,
            output_summary="Extracted 5 persons",
        )

        assert event.event == WebSocketEventType.AGENT_COMPLETED
        assert event.data["agent_name"] == "extractor"
        assert event.data["duration_ms"] == 1500.5
        assert event.data["output_summary"] == "Extracted 5 persons"

    def test_create_critic_decision_event(self, workflow_id):
        """Test critic_decision event creation."""
        event = create_critic_decision_event(
            workflow_id=workflow_id,
            critic_name="critic_1",
            decision="pass",
            feedback=None,
        )

        assert event.event == WebSocketEventType.CRITIC_DECISION
        assert event.data["critic_name"] == "critic_1"
        assert event.data["decision"] == "pass"
        assert event.data["feedback"] is None

    def test_create_critic_decision_event_with_feedback(self, workflow_id):
        """Test critic_decision event with feedback."""
        event = create_critic_decision_event(
            workflow_id=workflow_id,
            critic_name="critic_1",
            decision="fail_retry",
            feedback="Missing source references",
        )

        assert event.data["decision"] == "fail_retry"
        assert event.data["feedback"] == "Missing source references"

    def test_create_retry_triggered_event(self, workflow_id):
        """Test retry_triggered event creation."""
        event = create_retry_triggered_event(
            workflow_id=workflow_id,
            agent_name="extractor",
            retry_count=2,
            reason="Missing mandatory fields",
        )

        assert event.event == WebSocketEventType.RETRY_TRIGGERED
        assert event.data["agent_name"] == "extractor"
        assert event.data["retry_count"] == 2
        assert event.data["reason"] == "Missing mandatory fields"

    def test_create_workflow_completed_event(self, workflow_id):
        """Test workflow_completed event creation."""
        summary = {"total_persons": 5, "csm_count": 2, "non_csm_count": 3}
        event = create_workflow_completed_event(
            workflow_id=workflow_id,
            duration_seconds=45.5,
            summary=summary,
        )

        assert event.event == WebSocketEventType.WORKFLOW_COMPLETED
        assert event.data["duration_seconds"] == 45.5
        assert event.data["summary"] == summary

    def test_create_workflow_failed_event(self, workflow_id):
        """Test workflow_failed event creation."""
        event = create_workflow_failed_event(
            workflow_id=workflow_id,
            error="LLM service unavailable",
            failed_agent="extractor",
        )

        assert event.event == WebSocketEventType.WORKFLOW_FAILED
        assert event.data["error"] == "LLM service unavailable"
        assert event.data["failed_agent"] == "extractor"


# --- ConnectionManager Tests ---


class TestConnectionManager:
    """Tests for WebSocket connection management."""

    @pytest.mark.asyncio
    async def test_connect_accepts_websocket(
        self, connection_manager, mock_websocket, workflow_id
    ):
        """Test that connect accepts the WebSocket connection."""
        await connection_manager.connect(mock_websocket, workflow_id)

        mock_websocket.accept.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_sends_connected_event(
        self, connection_manager, mock_websocket, workflow_id
    ):
        """Test that connect sends a connected event."""
        await connection_manager.connect(mock_websocket, workflow_id)

        # Verify send_json was called with connected event
        mock_websocket.send_json.assert_called_once()
        call_args = mock_websocket.send_json.call_args[0][0]
        assert call_args["event"] == "connected"
        assert call_args["workflow_id"] == workflow_id

    @pytest.mark.asyncio
    async def test_connect_registers_connection(
        self, connection_manager, mock_websocket, workflow_id
    ):
        """Test that connect registers the connection."""
        await connection_manager.connect(mock_websocket, workflow_id)

        assert connection_manager.get_connection_count(workflow_id) == 1

    @pytest.mark.asyncio
    async def test_disconnect_removes_connection(
        self, connection_manager, mock_websocket, workflow_id
    ):
        """Test that disconnect removes the connection."""
        await connection_manager.connect(mock_websocket, workflow_id)
        await connection_manager.disconnect(mock_websocket, workflow_id)

        assert connection_manager.get_connection_count(workflow_id) == 0

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all_connections(
        self, connection_manager, workflow_id
    ):
        """Test that broadcast sends to all connected clients."""
        # Create multiple mock connections
        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        ws1.send_json = AsyncMock()
        ws2 = AsyncMock()
        ws2.accept = AsyncMock()
        ws2.send_json = AsyncMock()

        await connection_manager.connect(ws1, workflow_id)
        await connection_manager.connect(ws2, workflow_id)

        # Create and broadcast event
        event = create_agent_started_event(workflow_id, "extractor", 0)
        await connection_manager.broadcast(workflow_id, event)

        # Both connections should receive the event
        assert ws1.send_json.call_count == 2  # connected + broadcast
        assert ws2.send_json.call_count == 2  # connected + broadcast

    @pytest.mark.asyncio
    async def test_broadcast_to_nonexistent_workflow(self, connection_manager):
        """Test that broadcast to nonexistent workflow is handled gracefully."""
        event = create_agent_started_event("nonexistent-id", "extractor", 0)

        # Should not raise
        await connection_manager.broadcast("nonexistent-id", event)

    @pytest.mark.asyncio
    async def test_multiple_workflows(self, connection_manager):
        """Test handling multiple workflows simultaneously."""
        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        ws1.send_json = AsyncMock()
        ws2 = AsyncMock()
        ws2.accept = AsyncMock()
        ws2.send_json = AsyncMock()

        await connection_manager.connect(ws1, "workflow-1")
        await connection_manager.connect(ws2, "workflow-2")

        assert connection_manager.get_connection_count("workflow-1") == 1
        assert connection_manager.get_connection_count("workflow-2") == 1
        assert connection_manager.get_total_connections() == 2

    @pytest.mark.asyncio
    async def test_send_personal(self, connection_manager, mock_websocket, workflow_id):
        """Test sending a personal message to a single connection."""
        await connection_manager.connect(mock_websocket, workflow_id)
        mock_websocket.send_json.reset_mock()

        event = create_agent_started_event(workflow_id, "extractor", 0)
        await connection_manager.send_personal(mock_websocket, event)

        mock_websocket.send_json.assert_called_once()


# --- WorkflowEventEmitter Tests ---


class TestWorkflowEventEmitter:
    """Tests for WorkflowEventEmitter class."""

    def test_emitter_creation(self, workflow_id):
        """Test emitter creation with workflow ID."""
        emitter = create_event_emitter(workflow_id)

        assert emitter.workflow_id == workflow_id

    def test_get_event_emitter_reuses_instance(self, workflow_id):
        """Test that get_event_emitter returns same instance."""
        emitter1 = get_event_emitter(workflow_id)
        emitter2 = get_event_emitter(workflow_id)

        assert emitter1 is emitter2

        # Clean up
        remove_event_emitter(workflow_id)

    def test_remove_event_emitter(self, workflow_id):
        """Test removing an event emitter."""
        emitter1 = get_event_emitter(workflow_id)
        remove_event_emitter(workflow_id)
        emitter2 = get_event_emitter(workflow_id)

        # Should be different instances
        assert emitter1 is not emitter2

        # Clean up
        remove_event_emitter(workflow_id)

    @pytest.mark.asyncio
    async def test_emit_agent_started_async(self, workflow_id):
        """Test async agent_started emission."""
        emitter = create_event_emitter(workflow_id)

        with patch.object(manager, "broadcast", new_callable=AsyncMock) as mock_broadcast:
            await emitter.emit_agent_started_async("extractor", 0)

            mock_broadcast.assert_called_once()
            call_args = mock_broadcast.call_args
            assert call_args[0][0] == workflow_id
            event = call_args[0][1]
            assert event.event == WebSocketEventType.AGENT_STARTED

    @pytest.mark.asyncio
    async def test_emit_agent_completed_async(self, workflow_id):
        """Test async agent_completed emission."""
        emitter = create_event_emitter(workflow_id)

        with patch.object(manager, "broadcast", new_callable=AsyncMock) as mock_broadcast:
            await emitter.emit_agent_completed_async(
                "extractor", 1500.5, "Extracted 5 persons"
            )

            mock_broadcast.assert_called_once()
            event = mock_broadcast.call_args[0][1]
            assert event.event == WebSocketEventType.AGENT_COMPLETED
            assert event.data["duration_ms"] == 1500.5

    @pytest.mark.asyncio
    async def test_emit_critic_decision_async(self, workflow_id):
        """Test async critic_decision emission."""
        emitter = create_event_emitter(workflow_id)

        with patch.object(manager, "broadcast", new_callable=AsyncMock) as mock_broadcast:
            await emitter.emit_critic_decision_async("critic_1", "pass", None)

            mock_broadcast.assert_called_once()
            event = mock_broadcast.call_args[0][1]
            assert event.event == WebSocketEventType.CRITIC_DECISION
            assert event.data["decision"] == "pass"

    @pytest.mark.asyncio
    async def test_emit_retry_triggered_async(self, workflow_id):
        """Test async retry_triggered emission."""
        emitter = create_event_emitter(workflow_id)

        with patch.object(manager, "broadcast", new_callable=AsyncMock) as mock_broadcast:
            await emitter.emit_retry_triggered_async(
                "extractor", 1, "Missing fields"
            )

            mock_broadcast.assert_called_once()
            event = mock_broadcast.call_args[0][1]
            assert event.event == WebSocketEventType.RETRY_TRIGGERED
            assert event.data["retry_count"] == 1

    @pytest.mark.asyncio
    async def test_emit_workflow_completed_async(self, workflow_id):
        """Test async workflow_completed emission."""
        emitter = create_event_emitter(workflow_id)
        summary = {"csm_count": 2, "non_csm_count": 3}

        with patch.object(manager, "broadcast", new_callable=AsyncMock) as mock_broadcast:
            await emitter.emit_workflow_completed_async(45.5, summary)

            mock_broadcast.assert_called_once()
            event = mock_broadcast.call_args[0][1]
            assert event.event == WebSocketEventType.WORKFLOW_COMPLETED
            assert event.data["duration_seconds"] == 45.5
            assert event.data["summary"] == summary

    @pytest.mark.asyncio
    async def test_emit_workflow_failed_async(self, workflow_id):
        """Test async workflow_failed emission."""
        emitter = create_event_emitter(workflow_id)

        with patch.object(manager, "broadcast", new_callable=AsyncMock) as mock_broadcast:
            await emitter.emit_workflow_failed_async(
                "LLM service unavailable", "extractor"
            )

            mock_broadcast.assert_called_once()
            event = mock_broadcast.call_args[0][1]
            assert event.event == WebSocketEventType.WORKFLOW_FAILED
            assert event.data["error"] == "LLM service unavailable"
            assert event.data["failed_agent"] == "extractor"


# --- Integration with Workflow Tests ---


class TestWorkflowEventIntegration:
    """Tests for event emission integration with workflow execution."""

    @pytest.mark.asyncio
    async def test_event_sequence_for_successful_workflow(self, workflow_id):
        """Test that events are emitted in correct sequence for success."""
        emitter = create_event_emitter(workflow_id)
        events_received = []

        async def capture_event(wf_id, event):
            events_received.append(event.event)

        with patch.object(manager, "broadcast", side_effect=capture_event):
            # Simulate workflow execution
            await emitter.emit_agent_started_async("extractor", 0)
            await emitter.emit_agent_completed_async("extractor", 1000, "Extracted 3")
            await emitter.emit_critic_decision_async("critic_1", "pass", None)
            await emitter.emit_agent_started_async("reconciler", 0)
            await emitter.emit_agent_completed_async("reconciler", 500, "Reconciled")
            await emitter.emit_critic_decision_async("critic_2", "pass", None)
            await emitter.emit_agent_started_async("classifier", 0)
            await emitter.emit_agent_completed_async("classifier", 800, "Classified")
            await emitter.emit_critic_decision_async("critic_3", "pass", None)
            await emitter.emit_agent_started_async("formatter", 0)
            await emitter.emit_agent_completed_async("formatter", 100, "Formatted")
            await emitter.emit_workflow_completed_async(3.5, {"csm_count": 2})

        # Verify event sequence
        expected_sequence = [
            WebSocketEventType.AGENT_STARTED,
            WebSocketEventType.AGENT_COMPLETED,
            WebSocketEventType.CRITIC_DECISION,
            WebSocketEventType.AGENT_STARTED,
            WebSocketEventType.AGENT_COMPLETED,
            WebSocketEventType.CRITIC_DECISION,
            WebSocketEventType.AGENT_STARTED,
            WebSocketEventType.AGENT_COMPLETED,
            WebSocketEventType.CRITIC_DECISION,
            WebSocketEventType.AGENT_STARTED,
            WebSocketEventType.AGENT_COMPLETED,
            WebSocketEventType.WORKFLOW_COMPLETED,
        ]
        assert events_received == expected_sequence

    @pytest.mark.asyncio
    async def test_event_sequence_for_retry(self, workflow_id):
        """Test that retry events are emitted correctly."""
        emitter = create_event_emitter(workflow_id)
        events_received = []

        async def capture_event(wf_id, event):
            events_received.append((event.event, event.data))

        with patch.object(manager, "broadcast", side_effect=capture_event):
            # Simulate extraction with retry
            await emitter.emit_agent_started_async("extractor", 0)
            await emitter.emit_agent_completed_async("extractor", 1000, "Extracted")
            await emitter.emit_critic_decision_async(
                "critic_1", "fail_retry", "Missing fields"
            )
            await emitter.emit_retry_triggered_async(
                "extractor", 1, "Missing fields"
            )
            await emitter.emit_agent_started_async("extractor", 1)
            await emitter.emit_agent_completed_async("extractor", 1200, "Re-extracted")
            await emitter.emit_critic_decision_async("critic_1", "pass", None)

        # Verify retry was captured
        event_types = [e[0] for e in events_received]
        assert WebSocketEventType.RETRY_TRIGGERED in event_types

        # Find retry event and verify data
        retry_event = next(
            e for e in events_received if e[0] == WebSocketEventType.RETRY_TRIGGERED
        )
        assert retry_event[1]["retry_count"] == 1
        assert retry_event[1]["reason"] == "Missing fields"

    @pytest.mark.asyncio
    async def test_event_sequence_for_failure(self, workflow_id):
        """Test that failure events are emitted correctly."""
        emitter = create_event_emitter(workflow_id)
        events_received = []

        async def capture_event(wf_id, event):
            events_received.append(event)

        with patch.object(manager, "broadcast", side_effect=capture_event):
            await emitter.emit_agent_started_async("extractor", 0)
            await emitter.emit_workflow_failed_async(
                "LLM service unavailable", "extractor"
            )

        # Verify failure event
        assert len(events_received) == 2
        failure_event = events_received[-1]
        assert failure_event.event == WebSocketEventType.WORKFLOW_FAILED
        assert "LLM service unavailable" in failure_event.data["error"]
