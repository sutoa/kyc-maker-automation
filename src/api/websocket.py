"""WebSocket server for real-time workflow updates.

This module provides:
- WebSocket endpoint /ws/workflows/{id} for real-time updates
- Connection management (accept, close, broadcast)
- Event types for workflow progress updates

Event Types (per contracts/api.md):
- agent_started: Agent begins processing
- agent_completed: Agent finished successfully
- critic_decision: Critic made a pass/fail decision
- retry_triggered: Agent retry initiated
- workflow_completed: Workflow finished successfully
- workflow_failed: Workflow failed with error
"""

import asyncio
import json
import logging
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# --- Event Types ---


class WebSocketEventType(str, Enum):
    """WebSocket event types for workflow updates."""

    # Agent lifecycle events
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"

    # Critic events
    CRITIC_DECISION = "critic_decision"

    # Retry events
    RETRY_TRIGGERED = "retry_triggered"

    # Workflow lifecycle events
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"

    # Connection events
    CONNECTED = "connected"
    ERROR = "error"


class WebSocketEvent(BaseModel):
    """WebSocket event payload."""

    event: WebSocketEventType
    workflow_id: str
    timestamp: datetime
    data: dict[str, Any] | None = None

    class Config:
        use_enum_values = True


# --- Connection Manager ---


class ConnectionManager:
    """Manages WebSocket connections for workflow updates.

    Handles:
    - Accepting new connections
    - Tracking connections per workflow
    - Broadcasting events to connected clients
    - Cleaning up disconnected clients
    """

    def __init__(self):
        """Initialize the connection manager."""
        # Map workflow_id -> list of WebSocket connections
        self._connections: dict[str, list[WebSocket]] = {}
        # Lock for thread-safe connection management
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, workflow_id: str) -> None:
        """Accept and register a new WebSocket connection.

        Args:
            websocket: The WebSocket connection to accept.
            workflow_id: The workflow ID this connection is monitoring.
        """
        await websocket.accept()

        async with self._lock:
            if workflow_id not in self._connections:
                self._connections[workflow_id] = []
            self._connections[workflow_id].append(websocket)

        logger.info(
            f"WebSocket connected for workflow {workflow_id}. "
            f"Total connections: {len(self._connections.get(workflow_id, []))}"
        )

        # Send connection confirmation
        await self.send_personal(
            websocket,
            WebSocketEvent(
                event=WebSocketEventType.CONNECTED,
                workflow_id=workflow_id,
                timestamp=datetime.utcnow(),
                data={"message": "Connected to workflow updates"},
            ),
        )

    async def disconnect(self, websocket: WebSocket, workflow_id: str) -> None:
        """Remove a WebSocket connection.

        Args:
            websocket: The WebSocket connection to remove.
            workflow_id: The workflow ID this connection was monitoring.
        """
        async with self._lock:
            if workflow_id in self._connections:
                try:
                    self._connections[workflow_id].remove(websocket)
                except ValueError:
                    pass  # Already removed

                # Clean up empty workflow entries
                if not self._connections[workflow_id]:
                    del self._connections[workflow_id]

        logger.info(f"WebSocket disconnected for workflow {workflow_id}")

    async def send_personal(self, websocket: WebSocket, event: WebSocketEvent) -> None:
        """Send an event to a specific connection.

        Args:
            websocket: The target WebSocket connection.
            event: The event to send.
        """
        try:
            await websocket.send_json(event.model_dump(mode="json"))
        except Exception as e:
            logger.warning(f"Failed to send WebSocket message: {e}")

    async def broadcast(self, workflow_id: str, event: WebSocketEvent) -> None:
        """Broadcast an event to all connections monitoring a workflow.

        Args:
            workflow_id: The workflow ID to broadcast to.
            event: The event to broadcast.
        """
        connections = self._connections.get(workflow_id, [])
        if not connections:
            logger.debug(f"No WebSocket connections for workflow {workflow_id}")
            return

        # Serialize once for all connections
        event_json = event.model_dump(mode="json")

        # Send to all connections, handling failures gracefully
        disconnected = []
        for connection in connections:
            try:
                await connection.send_json(event_json)
            except Exception as e:
                logger.warning(
                    f"Failed to broadcast to WebSocket for workflow {workflow_id}: {e}"
                )
                disconnected.append(connection)

        # Clean up disconnected clients
        if disconnected:
            async with self._lock:
                for conn in disconnected:
                    try:
                        self._connections[workflow_id].remove(conn)
                    except (ValueError, KeyError):
                        pass

    async def broadcast_all(self, event: WebSocketEvent) -> None:
        """Broadcast an event to all connected clients.

        Args:
            event: The event to broadcast.
        """
        for workflow_id in list(self._connections.keys()):
            await self.broadcast(workflow_id, event)

    def get_connection_count(self, workflow_id: str) -> int:
        """Get the number of connections for a workflow.

        Args:
            workflow_id: The workflow ID to check.

        Returns:
            Number of active connections.
        """
        return len(self._connections.get(workflow_id, []))

    def get_total_connections(self) -> int:
        """Get the total number of active connections.

        Returns:
            Total number of connections across all workflows.
        """
        return sum(len(conns) for conns in self._connections.values())


# Global connection manager instance
manager = ConnectionManager()


# --- Event Builder Functions ---


def create_agent_started_event(
    workflow_id: str,
    agent_name: str,
    retry_count: int = 0,
) -> WebSocketEvent:
    """Create an agent_started event.

    Args:
        workflow_id: The workflow ID.
        agent_name: Name of the agent starting.
        retry_count: Current retry count.

    Returns:
        WebSocketEvent for agent_started.
    """
    return WebSocketEvent(
        event=WebSocketEventType.AGENT_STARTED,
        workflow_id=workflow_id,
        timestamp=datetime.utcnow(),
        data={
            "agent_name": agent_name,
            "retry_count": retry_count,
        },
    )


def create_agent_completed_event(
    workflow_id: str,
    agent_name: str,
    duration_ms: float,
    output_summary: str | None = None,
) -> WebSocketEvent:
    """Create an agent_completed event.

    Args:
        workflow_id: The workflow ID.
        agent_name: Name of the completed agent.
        duration_ms: Execution duration in milliseconds.
        output_summary: Brief summary of output (optional).

    Returns:
        WebSocketEvent for agent_completed.
    """
    return WebSocketEvent(
        event=WebSocketEventType.AGENT_COMPLETED,
        workflow_id=workflow_id,
        timestamp=datetime.utcnow(),
        data={
            "agent_name": agent_name,
            "duration_ms": duration_ms,
            "output_summary": output_summary,
        },
    )


def create_critic_decision_event(
    workflow_id: str,
    critic_name: str,
    decision: str,
    feedback: str | None = None,
) -> WebSocketEvent:
    """Create a critic_decision event.

    Args:
        workflow_id: The workflow ID.
        critic_name: Name of the critic agent.
        decision: The decision (pass, fail_retry, fail_max).
        feedback: Feedback message if applicable.

    Returns:
        WebSocketEvent for critic_decision.
    """
    return WebSocketEvent(
        event=WebSocketEventType.CRITIC_DECISION,
        workflow_id=workflow_id,
        timestamp=datetime.utcnow(),
        data={
            "critic_name": critic_name,
            "decision": decision,
            "feedback": feedback,
        },
    )


def create_retry_triggered_event(
    workflow_id: str,
    agent_name: str,
    retry_count: int,
    reason: str,
) -> WebSocketEvent:
    """Create a retry_triggered event.

    Args:
        workflow_id: The workflow ID.
        agent_name: Name of the agent being retried.
        retry_count: Current retry count after increment.
        reason: Reason for retry.

    Returns:
        WebSocketEvent for retry_triggered.
    """
    return WebSocketEvent(
        event=WebSocketEventType.RETRY_TRIGGERED,
        workflow_id=workflow_id,
        timestamp=datetime.utcnow(),
        data={
            "agent_name": agent_name,
            "retry_count": retry_count,
            "reason": reason,
        },
    )


def create_workflow_completed_event(
    workflow_id: str,
    duration_seconds: float,
    summary: dict[str, Any] | None = None,
) -> WebSocketEvent:
    """Create a workflow_completed event.

    Args:
        workflow_id: The workflow ID.
        duration_seconds: Total workflow duration.
        summary: Summary statistics (optional).

    Returns:
        WebSocketEvent for workflow_completed.
    """
    return WebSocketEvent(
        event=WebSocketEventType.WORKFLOW_COMPLETED,
        workflow_id=workflow_id,
        timestamp=datetime.utcnow(),
        data={
            "duration_seconds": duration_seconds,
            "summary": summary,
        },
    )


def create_workflow_failed_event(
    workflow_id: str,
    error: str,
    failed_agent: str | None = None,
) -> WebSocketEvent:
    """Create a workflow_failed event.

    Args:
        workflow_id: The workflow ID.
        error: Error message.
        failed_agent: Name of agent that failed (optional).

    Returns:
        WebSocketEvent for workflow_failed.
    """
    return WebSocketEvent(
        event=WebSocketEventType.WORKFLOW_FAILED,
        workflow_id=workflow_id,
        timestamp=datetime.utcnow(),
        data={
            "error": error,
            "failed_agent": failed_agent,
        },
    )


# --- WebSocket Endpoint Handler ---


async def websocket_endpoint(websocket: WebSocket, workflow_id: str) -> None:
    """Handle WebSocket connections for workflow updates.

    This function is designed to be registered as a WebSocket route handler.

    Args:
        websocket: The WebSocket connection.
        workflow_id: The workflow ID to monitor.
    """
    await manager.connect(websocket, workflow_id)

    try:
        while True:
            # Keep connection alive, waiting for messages
            # Clients can send ping/pong or other messages if needed
            data = await websocket.receive_text()

            # Handle client messages (e.g., ping)
            if data == "ping":
                await websocket.send_text("pong")
            elif data == "status":
                # Send current connection count
                count = manager.get_connection_count(workflow_id)
                await websocket.send_json(
                    {"type": "status", "connections": count}
                )

    except WebSocketDisconnect:
        await manager.disconnect(websocket, workflow_id)
    except Exception as e:
        logger.error(f"WebSocket error for workflow {workflow_id}: {e}")
        await manager.disconnect(websocket, workflow_id)
