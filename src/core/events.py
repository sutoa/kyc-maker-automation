"""Event emitter for workflow lifecycle events.

This module provides:
- Event emitter functions for all workflow events
- Integration with WebSocket broadcasting
- Async-compatible event emission

Events emitted:
- agent_started: When an agent begins processing
- agent_completed: When an agent finishes successfully
- critic_decision: When a critic makes a pass/fail decision
- retry_triggered: When a retry is initiated
- workflow_completed: When workflow finishes successfully
- workflow_failed: When workflow fails
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable

from src.api.websocket import (
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

logger = logging.getLogger(__name__)


# --- Event Emitter Class ---


class WorkflowEventEmitter:
    """Event emitter for workflow lifecycle events.

    This class provides methods to emit events during workflow execution.
    Events are broadcast to all connected WebSocket clients.

    The emitter supports both sync and async contexts.
    """

    def __init__(self, workflow_id: str):
        """Initialize the event emitter.

        Args:
            workflow_id: The workflow ID for this emitter.
        """
        self.workflow_id = workflow_id
        self._event_loop: asyncio.AbstractEventLoop | None = None

    def _get_or_create_loop(self) -> asyncio.AbstractEventLoop:
        """Get the current event loop or create one."""
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            # No running loop, create one
            return asyncio.new_event_loop()

    def _emit_sync(self, event: WebSocketEvent) -> None:
        """Emit an event synchronously.

        Attempts to use the running event loop, or creates a new one if needed.
        """
        try:
            loop = asyncio.get_running_loop()
            # Already in async context, schedule the broadcast
            asyncio.create_task(manager.broadcast(self.workflow_id, event))
        except RuntimeError:
            # Not in async context, run in new loop
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(manager.broadcast(self.workflow_id, event))
            finally:
                loop.close()

    async def _emit_async(self, event: WebSocketEvent) -> None:
        """Emit an event asynchronously."""
        await manager.broadcast(self.workflow_id, event)

    # --- Agent Events ---

    def emit_agent_started(
        self,
        agent_name: str,
        retry_count: int = 0,
    ) -> None:
        """Emit an agent_started event.

        Args:
            agent_name: Name of the agent starting.
            retry_count: Current retry count.
        """
        event = create_agent_started_event(
            workflow_id=self.workflow_id,
            agent_name=agent_name,
            retry_count=retry_count,
        )
        logger.debug(f"[{self.workflow_id}] Emitting agent_started: {agent_name}")
        self._emit_sync(event)

    async def emit_agent_started_async(
        self,
        agent_name: str,
        retry_count: int = 0,
    ) -> None:
        """Emit an agent_started event asynchronously.

        Args:
            agent_name: Name of the agent starting.
            retry_count: Current retry count.
        """
        event = create_agent_started_event(
            workflow_id=self.workflow_id,
            agent_name=agent_name,
            retry_count=retry_count,
        )
        logger.debug(f"[{self.workflow_id}] Emitting agent_started: {agent_name}")
        await self._emit_async(event)

    def emit_agent_completed(
        self,
        agent_name: str,
        duration_ms: float,
        output_summary: str | None = None,
    ) -> None:
        """Emit an agent_completed event.

        Args:
            agent_name: Name of the completed agent.
            duration_ms: Execution duration in milliseconds.
            output_summary: Brief summary of output.
        """
        event = create_agent_completed_event(
            workflow_id=self.workflow_id,
            agent_name=agent_name,
            duration_ms=duration_ms,
            output_summary=output_summary,
        )
        logger.debug(f"[{self.workflow_id}] Emitting agent_completed: {agent_name}")
        self._emit_sync(event)

    async def emit_agent_completed_async(
        self,
        agent_name: str,
        duration_ms: float,
        output_summary: str | None = None,
    ) -> None:
        """Emit an agent_completed event asynchronously.

        Args:
            agent_name: Name of the completed agent.
            duration_ms: Execution duration in milliseconds.
            output_summary: Brief summary of output.
        """
        event = create_agent_completed_event(
            workflow_id=self.workflow_id,
            agent_name=agent_name,
            duration_ms=duration_ms,
            output_summary=output_summary,
        )
        logger.debug(f"[{self.workflow_id}] Emitting agent_completed: {agent_name}")
        await self._emit_async(event)

    # --- Critic Events ---

    def emit_critic_decision(
        self,
        critic_name: str,
        decision: str,
        feedback: str | None = None,
    ) -> None:
        """Emit a critic_decision event.

        Args:
            critic_name: Name of the critic agent.
            decision: The decision (pass, fail_retry, fail_max).
            feedback: Feedback message if applicable.
        """
        event = create_critic_decision_event(
            workflow_id=self.workflow_id,
            critic_name=critic_name,
            decision=decision,
            feedback=feedback,
        )
        logger.debug(
            f"[{self.workflow_id}] Emitting critic_decision: {critic_name} -> {decision}"
        )
        self._emit_sync(event)

    async def emit_critic_decision_async(
        self,
        critic_name: str,
        decision: str,
        feedback: str | None = None,
    ) -> None:
        """Emit a critic_decision event asynchronously.

        Args:
            critic_name: Name of the critic agent.
            decision: The decision (pass, fail_retry, fail_max).
            feedback: Feedback message if applicable.
        """
        event = create_critic_decision_event(
            workflow_id=self.workflow_id,
            critic_name=critic_name,
            decision=decision,
            feedback=feedback,
        )
        logger.debug(
            f"[{self.workflow_id}] Emitting critic_decision: {critic_name} -> {decision}"
        )
        await self._emit_async(event)

    # --- Retry Events ---

    def emit_retry_triggered(
        self,
        agent_name: str,
        retry_count: int,
        reason: str,
    ) -> None:
        """Emit a retry_triggered event.

        Args:
            agent_name: Name of the agent being retried.
            retry_count: Current retry count after increment.
            reason: Reason for retry.
        """
        event = create_retry_triggered_event(
            workflow_id=self.workflow_id,
            agent_name=agent_name,
            retry_count=retry_count,
            reason=reason,
        )
        logger.debug(
            f"[{self.workflow_id}] Emitting retry_triggered: {agent_name} (count: {retry_count})"
        )
        self._emit_sync(event)

    async def emit_retry_triggered_async(
        self,
        agent_name: str,
        retry_count: int,
        reason: str,
    ) -> None:
        """Emit a retry_triggered event asynchronously.

        Args:
            agent_name: Name of the agent being retried.
            retry_count: Current retry count after increment.
            reason: Reason for retry.
        """
        event = create_retry_triggered_event(
            workflow_id=self.workflow_id,
            agent_name=agent_name,
            retry_count=retry_count,
            reason=reason,
        )
        logger.debug(
            f"[{self.workflow_id}] Emitting retry_triggered: {agent_name} (count: {retry_count})"
        )
        await self._emit_async(event)

    # --- Workflow Lifecycle Events ---

    def emit_workflow_completed(
        self,
        duration_seconds: float,
        summary: dict[str, Any] | None = None,
    ) -> None:
        """Emit a workflow_completed event.

        Args:
            duration_seconds: Total workflow duration.
            summary: Summary statistics.
        """
        event = create_workflow_completed_event(
            workflow_id=self.workflow_id,
            duration_seconds=duration_seconds,
            summary=summary,
        )
        logger.debug(f"[{self.workflow_id}] Emitting workflow_completed")
        self._emit_sync(event)

    async def emit_workflow_completed_async(
        self,
        duration_seconds: float,
        summary: dict[str, Any] | None = None,
    ) -> None:
        """Emit a workflow_completed event asynchronously.

        Args:
            duration_seconds: Total workflow duration.
            summary: Summary statistics.
        """
        event = create_workflow_completed_event(
            workflow_id=self.workflow_id,
            duration_seconds=duration_seconds,
            summary=summary,
        )
        logger.debug(f"[{self.workflow_id}] Emitting workflow_completed")
        await self._emit_async(event)

    def emit_workflow_failed(
        self,
        error: str,
        failed_agent: str | None = None,
    ) -> None:
        """Emit a workflow_failed event.

        Args:
            error: Error message.
            failed_agent: Name of agent that failed.
        """
        event = create_workflow_failed_event(
            workflow_id=self.workflow_id,
            error=error,
            failed_agent=failed_agent,
        )
        logger.debug(f"[{self.workflow_id}] Emitting workflow_failed: {error}")
        self._emit_sync(event)

    async def emit_workflow_failed_async(
        self,
        error: str,
        failed_agent: str | None = None,
    ) -> None:
        """Emit a workflow_failed event asynchronously.

        Args:
            error: Error message.
            failed_agent: Name of agent that failed.
        """
        event = create_workflow_failed_event(
            workflow_id=self.workflow_id,
            error=error,
            failed_agent=failed_agent,
        )
        logger.debug(f"[{self.workflow_id}] Emitting workflow_failed: {error}")
        await self._emit_async(event)


# --- Factory Function ---


def create_event_emitter(workflow_id: str) -> WorkflowEventEmitter:
    """Create an event emitter for a workflow.

    Args:
        workflow_id: The workflow ID.

    Returns:
        WorkflowEventEmitter instance.
    """
    return WorkflowEventEmitter(workflow_id)


# --- Global Emitter Registry ---

_emitters: dict[str, WorkflowEventEmitter] = {}


def get_event_emitter(workflow_id: str) -> WorkflowEventEmitter:
    """Get or create an event emitter for a workflow.

    This maintains a registry of emitters to avoid creating duplicates.

    Args:
        workflow_id: The workflow ID.

    Returns:
        WorkflowEventEmitter instance.
    """
    if workflow_id not in _emitters:
        _emitters[workflow_id] = create_event_emitter(workflow_id)
    return _emitters[workflow_id]


def remove_event_emitter(workflow_id: str) -> None:
    """Remove an event emitter from the registry.

    Call this when a workflow completes to clean up resources.

    Args:
        workflow_id: The workflow ID.
    """
    if workflow_id in _emitters:
        del _emitters[workflow_id]
