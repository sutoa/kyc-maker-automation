"""LangGraph workflow engine for KYC document processing.

This module defines:
- Base agent node wrapper with logging and state updates
- Critic node wrapper with 3-outcome routing
- Conditional edge functions for workflow transitions
- The complete StateGraph with all agents

Workflow Flow:
extractor -> critic_1 -> reconciler -> critic_2 -> classifier -> critic_3 -> formatter
            |                |                      |
            v (retry)        v (retry)              v (retry)
          extractor        reconciler            classifier
"""

import logging
from datetime import datetime
from typing import Any, Callable, Literal

from langgraph.graph import END, StateGraph

from src.config.loader import get_agent_config, get_transition, get_workflow_config
from src.core.state import (
    MAX_RETRY_COUNT,
    WorkflowState,
    can_retry,
    get_retry_count,
    update_classification_passed,
    update_classification_retry,
    update_extraction_passed,
    update_extraction_retry,
    update_reconciliation_passed,
    update_reconciliation_retry,
    update_workflow_failed,
    update_workflow_started,
)
from src.models.enums import CriticDecision

logger = logging.getLogger(__name__)


# Type alias for agent functions
AgentFunction = Callable[[WorkflowState], WorkflowState]


class WorkflowError(Exception):
    """Raised when workflow execution fails."""

    pass


# --- Agent Node Wrappers ---


def create_agent_node(
    agent_name: str,
    agent_fn: AgentFunction,
    next_agent: str | None = None,
) -> Callable[[WorkflowState], WorkflowState]:
    """Create a wrapped agent node with logging and state updates.

    Args:
        agent_name: Name of the agent (for logging).
        agent_fn: The actual agent function to execute.
        next_agent: Name of the next agent (for state update).

    Returns:
        Wrapped function that handles logging, timing, and state updates.
    """

    def wrapped_agent(state: WorkflowState) -> WorkflowState:
        workflow_id = state.get("workflow_id", "unknown")
        retry_count = _get_phase_retry_count(state, agent_name)

        logger.info(
            f"[{workflow_id}] Starting agent: {agent_name} (retry: {retry_count})"
        )
        start_time = datetime.now()

        try:
            # Update state to show current agent
            state = WorkflowState(
                **{**state, "current_agent": agent_name, "status": "in_progress"}
            )

            # Execute the agent
            new_state = agent_fn(state)

            # Log completion
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            logger.info(
                f"[{workflow_id}] Completed agent: {agent_name} "
                f"(duration: {duration_ms:.0f}ms)"
            )

            # Update current agent to next if specified
            if next_agent:
                new_state = WorkflowState(
                    **{**new_state, "current_agent": next_agent}
                )

            return new_state

        except Exception as e:
            logger.error(
                f"[{workflow_id}] Agent {agent_name} failed: {e}",
                exc_info=True,
            )
            return update_workflow_failed(
                state, f"Agent {agent_name} failed: {str(e)}"
            )

    return wrapped_agent


def _get_phase_retry_count(state: WorkflowState, agent_name: str) -> int:
    """Get retry count for the phase this agent belongs to."""
    if agent_name in ("extractor", "critic_1"):
        return state.get("extraction_retry_count", 0)
    elif agent_name in ("reconciler", "critic_2"):
        return state.get("reconciliation_retry_count", 0)
    elif agent_name in ("classifier", "critic_3"):
        return state.get("classification_retry_count", 0)
    return 0


# --- Critic Node Wrapper ---


def create_critic_node(
    critic_name: str,
    critic_fn: Callable[[WorkflowState], tuple[CriticDecision, str | None]],
    phase: Literal["extraction", "reconciliation", "classification"],
) -> Callable[[WorkflowState], WorkflowState]:
    """Create a wrapped critic node with 3-outcome routing.

    The critic function returns a tuple of (decision, feedback).
    This wrapper handles:
    - Logging the decision
    - Updating state with retry feedback or failure
    - Setting up for the next transition

    Args:
        critic_name: Name of the critic agent.
        critic_fn: Function that returns (CriticDecision, feedback_string).
        phase: Which workflow phase this critic validates.

    Returns:
        Wrapped function that updates state based on critic decision.
    """

    def wrapped_critic(state: WorkflowState) -> WorkflowState:
        workflow_id = state.get("workflow_id", "unknown")
        retry_count = get_retry_count(state, phase)

        logger.info(f"[{workflow_id}] Starting critic: {critic_name}")

        try:
            # Execute the critic
            decision, feedback = critic_fn(state)

            logger.info(
                f"[{workflow_id}] Critic {critic_name} decision: {decision.value}"
            )

            # Handle the decision
            if decision == CriticDecision.PASS:
                return _handle_critic_pass(state, phase)

            elif decision == CriticDecision.FAIL_RETRY:
                if can_retry(state, phase):
                    return _handle_critic_retry(
                        state, phase, feedback or "Retry requested"
                    )
                else:
                    # Max retries reached, treat as fail_max
                    logger.warning(
                        f"[{workflow_id}] Max retries reached for {phase}"
                    )
                    return update_workflow_failed(
                        state,
                        f"Maximum retries ({MAX_RETRY_COUNT}) exceeded for {phase}",
                    )

            else:  # FAIL_MAX
                return update_workflow_failed(
                    state,
                    f"Critic {critic_name} failed with max retries: {feedback or 'No feedback'}",
                )

        except Exception as e:
            logger.error(
                f"[{workflow_id}] Critic {critic_name} failed: {e}",
                exc_info=True,
            )
            return update_workflow_failed(
                state, f"Critic {critic_name} failed: {str(e)}"
            )

    return wrapped_critic


def _handle_critic_pass(
    state: WorkflowState,
    phase: Literal["extraction", "reconciliation", "classification"],
) -> WorkflowState:
    """Handle critic pass decision."""
    if phase == "extraction":
        return update_extraction_passed(state)
    elif phase == "reconciliation":
        return update_reconciliation_passed(state)
    else:  # classification
        return update_classification_passed(state)


def _handle_critic_retry(
    state: WorkflowState,
    phase: Literal["extraction", "reconciliation", "classification"],
    feedback: str,
) -> WorkflowState:
    """Handle critic fail_retry decision."""
    # Create a minimal critic feedback object
    from src.models.workflow import CriticFeedback
    from uuid import uuid4

    critic_feedback = CriticFeedback(
        id=str(uuid4()),
        agent_execution_id=str(uuid4()),
        critic_agent_name=f"critic_{['1', '2', '3'][['extraction', 'reconciliation', 'classification'].index(phase)]}",
        decision=CriticDecision.FAIL_RETRY,
        suggested_corrections=feedback,
        created_at=datetime.now(),
    )

    if phase == "extraction":
        return update_extraction_retry(state, feedback, critic_feedback)
    elif phase == "reconciliation":
        return update_reconciliation_retry(state, feedback, critic_feedback)
    else:  # classification
        return update_classification_retry(state, feedback, critic_feedback)


# --- Conditional Edge Functions ---


def should_continue_after_critic(
    phase: Literal["extraction", "reconciliation", "classification"],
) -> Callable[[WorkflowState], str]:
    """Create a conditional edge function for critic outcomes.

    Returns a function that determines the next node based on:
    - Current state status (failed -> END)
    - Current agent (to determine if retry happened)

    Args:
        phase: The workflow phase for this critic.

    Returns:
        Function that returns the next node name.
    """
    # Map phase to agents
    phase_to_agents = {
        "extraction": ("extractor", "critic_1", "reconciler"),
        "reconciliation": ("reconciler", "critic_2", "classifier"),
        "classification": ("classifier", "critic_3", "formatter"),
    }
    agent, critic, next_agent = phase_to_agents[phase]

    def route(state: WorkflowState) -> str:
        # Check if workflow failed
        if state.get("status") == "failed":
            return "FAILED"

        # Check current agent to determine outcome
        current = state.get("current_agent", "")

        if current == agent:
            # Retry was triggered
            return agent
        elif current in (next_agent, "formatter", ""):
            # Pass - move to next agent
            return next_agent if next_agent != "formatter" else "formatter"
        else:
            # Default to next agent
            return next_agent

    return route


def check_workflow_status(state: WorkflowState) -> str:
    """Check if workflow should continue or end.

    Returns:
        "continue" if workflow should continue, "FAILED" if failed.
    """
    if state.get("status") == "failed":
        return "FAILED"
    return "continue"


# --- StateGraph Builder ---


def build_workflow_graph(
    agent_functions: dict[str, AgentFunction],
    critic_functions: dict[str, Callable[[WorkflowState], tuple[CriticDecision, str | None]]],
) -> StateGraph:
    """Build the complete LangGraph StateGraph for KYC processing.

    Args:
        agent_functions: Map of agent name to agent function.
            Required: extractor, reconciler, classifier, formatter
        critic_functions: Map of critic name to critic function.
            Required: critic_1, critic_2, critic_3

    Returns:
        Compiled StateGraph ready for execution.

    Raises:
        ValueError: If required agents/critics are missing.
    """
    # Validate required functions
    required_agents = ["extractor", "reconciler", "classifier", "formatter"]
    required_critics = ["critic_1", "critic_2", "critic_3"]

    for agent in required_agents:
        if agent not in agent_functions:
            raise ValueError(f"Missing required agent function: {agent}")

    for critic in required_critics:
        if critic not in critic_functions:
            raise ValueError(f"Missing required critic function: {critic}")

    # Create the graph
    graph = StateGraph(WorkflowState)

    # Add agent nodes (wrapped)
    graph.add_node(
        "extractor",
        create_agent_node("extractor", agent_functions["extractor"], "critic_1"),
    )
    graph.add_node(
        "reconciler",
        create_agent_node("reconciler", agent_functions["reconciler"], "critic_2"),
    )
    graph.add_node(
        "classifier",
        create_agent_node("classifier", agent_functions["classifier"], "critic_3"),
    )
    graph.add_node(
        "formatter",
        create_agent_node("formatter", agent_functions["formatter"]),
    )

    # Add critic nodes (wrapped)
    graph.add_node(
        "critic_1",
        create_critic_node("critic_1", critic_functions["critic_1"], "extraction"),
    )
    graph.add_node(
        "critic_2",
        create_critic_node("critic_2", critic_functions["critic_2"], "reconciliation"),
    )
    graph.add_node(
        "critic_3",
        create_critic_node("critic_3", critic_functions["critic_3"], "classification"),
    )

    # Add failure node
    graph.add_node("FAILED", lambda state: state)

    # Set entry point
    graph.set_entry_point("extractor")

    # Add edges
    # Extractor -> Critic 1
    graph.add_edge("extractor", "critic_1")

    # Critic 1 -> conditional (extractor retry or reconciler)
    graph.add_conditional_edges(
        "critic_1",
        should_continue_after_critic("extraction"),
        {
            "extractor": "extractor",
            "reconciler": "reconciler",
            "FAILED": "FAILED",
        },
    )

    # Reconciler -> Critic 2
    graph.add_edge("reconciler", "critic_2")

    # Critic 2 -> conditional (reconciler retry or classifier)
    graph.add_conditional_edges(
        "critic_2",
        should_continue_after_critic("reconciliation"),
        {
            "reconciler": "reconciler",
            "classifier": "classifier",
            "FAILED": "FAILED",
        },
    )

    # Classifier -> Critic 3
    graph.add_edge("classifier", "critic_3")

    # Critic 3 -> conditional (classifier retry or formatter)
    graph.add_conditional_edges(
        "critic_3",
        should_continue_after_critic("classification"),
        {
            "classifier": "classifier",
            "formatter": "formatter",
            "FAILED": "FAILED",
        },
    )

    # Formatter -> END
    graph.add_edge("formatter", END)

    # FAILED -> END
    graph.add_edge("FAILED", END)

    return graph


def compile_workflow(
    agent_functions: dict[str, AgentFunction],
    critic_functions: dict[str, Callable[[WorkflowState], tuple[CriticDecision, str | None]]],
) -> Any:
    """Build and compile the workflow graph.

    Args:
        agent_functions: Map of agent name to agent function.
        critic_functions: Map of critic name to critic function.

    Returns:
        Compiled workflow ready for invocation.
    """
    graph = build_workflow_graph(agent_functions, critic_functions)
    return graph.compile()


# --- Workflow Execution ---


async def run_workflow(
    compiled_workflow: Any,
    initial_state: WorkflowState,
) -> WorkflowState:
    """Execute the compiled workflow.

    Args:
        compiled_workflow: Compiled LangGraph workflow.
        initial_state: Initial workflow state with documents.

    Returns:
        Final workflow state after completion or failure.
    """
    workflow_id = initial_state.get("workflow_id", "unknown")
    logger.info(f"[{workflow_id}] Starting workflow execution")

    # Mark workflow as started
    state = update_workflow_started(initial_state)

    try:
        # Run the workflow
        final_state = await compiled_workflow.ainvoke(state)

        status = final_state.get("status", "unknown")
        logger.info(f"[{workflow_id}] Workflow completed with status: {status}")

        return final_state

    except Exception as e:
        logger.error(f"[{workflow_id}] Workflow execution failed: {e}", exc_info=True)
        return update_workflow_failed(state, f"Workflow execution failed: {str(e)}")


def run_workflow_sync(
    compiled_workflow: Any,
    initial_state: WorkflowState,
) -> WorkflowState:
    """Execute the compiled workflow synchronously.

    Args:
        compiled_workflow: Compiled LangGraph workflow.
        initial_state: Initial workflow state with documents.

    Returns:
        Final workflow state after completion or failure.
    """
    workflow_id = initial_state.get("workflow_id", "unknown")
    logger.info(f"[{workflow_id}] Starting workflow execution (sync)")

    # Mark workflow as started
    state = update_workflow_started(initial_state)

    try:
        # Run the workflow
        final_state = compiled_workflow.invoke(state)

        status = final_state.get("status", "unknown")
        logger.info(f"[{workflow_id}] Workflow completed with status: {status}")

        return final_state

    except Exception as e:
        logger.error(f"[{workflow_id}] Workflow execution failed: {e}", exc_info=True)
        return update_workflow_failed(state, f"Workflow execution failed: {str(e)}")
