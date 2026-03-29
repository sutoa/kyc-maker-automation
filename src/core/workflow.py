"""LangGraph workflow engine for KYC document processing.

This module defines:
- Base agent node wrapper with logging and state updates
- Critic node wrapper with 3-outcome routing
- Conditional edge functions for workflow transitions
- The complete StateGraph with all agents
- Event emission for real-time WebSocket updates

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

from src.config.loader import (
    load_workflows_config,
    resolve_callable,
)
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

# Import event emitter (optional - graceful degradation if not available)
try:
    from src.core.events import get_event_emitter
    EVENTS_ENABLED = True
except ImportError:
    EVENTS_ENABLED = False
    get_event_emitter = None

# Import audit service (optional - graceful degradation if not available)
try:
    from src.services.audit import AuditService, create_audit_service
    from src.services.database import get_db
    AUDIT_ENABLED = True
except ImportError:
    AUDIT_ENABLED = False
    AuditService = None
    create_audit_service = None
    get_db = None

logger = logging.getLogger(__name__)


def _get_audit_service():
    """Get an audit service instance if available.

    Returns:
        AuditService instance or None if not available.
    """
    if not AUDIT_ENABLED or not get_db or not create_audit_service:
        return None
    try:
        db = next(get_db())
        return create_audit_service(db)
    except Exception as e:
        logger.warning(f"Failed to create audit service: {e}")
        return None


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

        # Emit agent_started event
        if EVENTS_ENABLED and get_event_emitter:
            try:
                emitter = get_event_emitter(workflow_id)
                emitter.emit_agent_started(agent_name, retry_count)
            except Exception as e:
                logger.warning(f"Failed to emit agent_started event: {e}")

        # Log agent_started to audit trail
        if AUDIT_ENABLED:
            try:
                audit = _get_audit_service()
                if audit:
                    audit.log_agent_started(
                        workflow_run_id=workflow_id,
                        agent_name=agent_name,
                        retry_count=retry_count,
                        input_summary={"documents": len(state.get("documents", []))},
                    )
            except Exception as e:
                logger.warning(f"Failed to log agent_started to audit: {e}")

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

            # Emit agent_completed event
            if EVENTS_ENABLED and get_event_emitter:
                try:
                    emitter = get_event_emitter(workflow_id)
                    # Generate output summary based on agent type
                    output_summary = _generate_output_summary(agent_name, new_state)
                    emitter.emit_agent_completed(agent_name, duration_ms, output_summary)
                except Exception as e:
                    logger.warning(f"Failed to emit agent_completed event: {e}")

            # Log agent_completed to audit trail
            if AUDIT_ENABLED:
                try:
                    audit = _get_audit_service()
                    if audit:
                        output_summary_dict = _generate_output_summary_dict(agent_name, new_state)
                        audit.log_agent_completed(
                            workflow_run_id=workflow_id,
                            agent_name=agent_name,
                            duration_ms=duration_ms,
                            output_summary=output_summary_dict,
                        )
                except Exception as e:
                    logger.warning(f"Failed to log agent_completed to audit: {e}")

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
            # Emit workflow_failed event
            if EVENTS_ENABLED and get_event_emitter:
                try:
                    emitter = get_event_emitter(workflow_id)
                    emitter.emit_workflow_failed(str(e), agent_name)
                except Exception as emit_err:
                    logger.warning(f"Failed to emit workflow_failed event: {emit_err}")

            # Log agent_failed to audit trail
            if AUDIT_ENABLED:
                try:
                    audit = _get_audit_service()
                    if audit:
                        audit.log_agent_failed(
                            workflow_run_id=workflow_id,
                            agent_name=agent_name,
                            error=str(e),
                        )
                except Exception as audit_err:
                    logger.warning(f"Failed to log agent_failed to audit: {audit_err}")

            return update_workflow_failed(
                state, f"Agent {agent_name} failed: {str(e)}"
            )

    return wrapped_agent


def _generate_output_summary(agent_name: str, state: WorkflowState) -> str | None:
    """Generate a brief output summary for an agent.

    Args:
        agent_name: Name of the agent.
        state: Current workflow state after agent execution.

    Returns:
        Brief summary string or None.
    """
    if agent_name == "extractor":
        persons = state.get("extracted_persons", [])
        return f"Extracted {len(persons)} person(s)"
    elif agent_name == "reconciler":
        persons = state.get("reconciled_persons", [])
        groups = state.get("duplicate_groups", [])
        return f"Reconciled to {len(persons)} person(s), {len(groups)} duplicate group(s)"
    elif agent_name == "classifier":
        persons = state.get("classified_persons", [])
        csm = sum(1 for p in persons if getattr(p, "classification", "") == "CSM")
        return f"Classified {len(persons)} person(s): {csm} CSM"
    elif agent_name == "formatter":
        csm = state.get("csm_list", [])
        non_csm = state.get("non_csm_list", [])
        return f"Output: {len(csm)} CSM, {len(non_csm)} NON_CSM"
    return None


def _generate_output_summary_dict(agent_name: str, state: WorkflowState) -> dict[str, Any]:
    """Generate an output summary dictionary for audit logging.

    Args:
        agent_name: Name of the agent.
        state: Current workflow state after agent execution.

    Returns:
        Dictionary with summary statistics for audit trail.
    """
    if agent_name == "extractor":
        persons = state.get("extracted_persons", [])
        return {"persons_extracted": len(persons)}
    elif agent_name == "reconciler":
        persons = state.get("reconciled_persons", [])
        groups = state.get("duplicate_groups", [])
        return {
            "persons_reconciled": len(persons),
            "duplicate_groups": len(groups),
        }
    elif agent_name == "classifier":
        persons = state.get("classified_persons", [])
        csm = sum(1 for p in persons if getattr(p, "classification", "") == "CSM")
        non_csm = len(persons) - csm
        return {
            "persons_classified": len(persons),
            "csm_count": csm,
            "non_csm_count": non_csm,
        }
    elif agent_name == "formatter":
        csm = state.get("csm_list", [])
        non_csm = state.get("non_csm_list", [])
        return {
            "csm_count": len(csm),
            "non_csm_count": len(non_csm),
        }
    return {}


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

            # Emit critic_decision event
            if EVENTS_ENABLED and get_event_emitter:
                try:
                    emitter = get_event_emitter(workflow_id)
                    emitter.emit_critic_decision(critic_name, decision.value, feedback)
                except Exception as e:
                    logger.warning(f"Failed to emit critic_decision event: {e}")

            # Log critic_decision to audit trail
            if AUDIT_ENABLED:
                try:
                    audit = _get_audit_service()
                    if audit:
                        audit.log_critic_decision(
                            workflow_run_id=workflow_id,
                            critic_name=critic_name,
                            decision=decision.value,
                            feedback=feedback,
                        )
                except Exception as e:
                    logger.warning(f"Failed to log critic_decision to audit: {e}")

            # Always write last_critic_feedback so routing functions
            # (src.core.conditions.route_critic_*) can read the latest decision.
            from src.models.workflow import CriticFeedback
            from uuid import uuid4
            state = WorkflowState(**{
                **state,
                "last_critic_feedback": CriticFeedback(
                    id=str(uuid4()),
                    agent_execution_id=str(uuid4()),
                    critic_agent_name=critic_name,
                    decision=decision,
                    suggested_corrections=feedback,
                    created_at=datetime.now(),
                ),
            })

            # Handle the decision
            if decision == CriticDecision.PASS:
                return _handle_critic_pass(state, phase)

            elif decision == CriticDecision.FAIL_RETRY:
                if can_retry(state, phase):
                    agent_name = _get_agent_for_phase(phase)
                    # Emit retry_triggered event
                    if EVENTS_ENABLED and get_event_emitter:
                        try:
                            emitter = get_event_emitter(workflow_id)
                            emitter.emit_retry_triggered(
                                agent_name,
                                retry_count + 1,
                                feedback or "Retry requested",
                            )
                        except Exception as e:
                            logger.warning(f"Failed to emit retry_triggered event: {e}")

                    # Log retry_triggered to audit trail
                    if AUDIT_ENABLED:
                        try:
                            audit = _get_audit_service()
                            if audit:
                                audit.log_retry_triggered(
                                    workflow_run_id=workflow_id,
                                    agent_name=agent_name,
                                    retry_count=retry_count + 1,
                                    reason=feedback or "Retry requested",
                                    critic_feedback=feedback,
                                )
                        except Exception as e:
                            logger.warning(f"Failed to log retry_triggered to audit: {e}")

                    return _handle_critic_retry(
                        state, phase, feedback or "Retry requested"
                    )
                else:
                    # Max retries reached, treat as fail_max
                    logger.warning(
                        f"[{workflow_id}] Max retries reached for {phase}"
                    )
                    error_msg = f"Maximum retries ({MAX_RETRY_COUNT}) exceeded for {phase}"
                    failed_agent = _get_agent_for_phase(phase)
                    # Emit workflow_failed event
                    if EVENTS_ENABLED and get_event_emitter:
                        try:
                            emitter = get_event_emitter(workflow_id)
                            emitter.emit_workflow_failed(error_msg, failed_agent)
                        except Exception as e:
                            logger.warning(f"Failed to emit workflow_failed event: {e}")

                    # Log workflow_failed to audit trail
                    if AUDIT_ENABLED:
                        try:
                            audit = _get_audit_service()
                            if audit:
                                audit.log_workflow_failed(
                                    workflow_run_id=workflow_id,
                                    error=error_msg,
                                    failed_agent=failed_agent,
                                )
                        except Exception as e:
                            logger.warning(f"Failed to log workflow_failed to audit: {e}")

                    return update_workflow_failed(state, error_msg)

            else:  # FAIL_MAX
                error_msg = f"Critic {critic_name} failed with max retries: {feedback or 'No feedback'}"
                failed_agent = _get_agent_for_phase(phase)
                # Emit workflow_failed event
                if EVENTS_ENABLED and get_event_emitter:
                    try:
                        emitter = get_event_emitter(workflow_id)
                        emitter.emit_workflow_failed(error_msg, failed_agent)
                    except Exception as e:
                        logger.warning(f"Failed to emit workflow_failed event: {e}")

                # Log workflow_failed to audit trail
                if AUDIT_ENABLED:
                    try:
                        audit = _get_audit_service()
                        if audit:
                            audit.log_workflow_failed(
                                workflow_run_id=workflow_id,
                                error=error_msg,
                                failed_agent=failed_agent,
                            )
                    except Exception as e:
                        logger.warning(f"Failed to log workflow_failed to audit: {e}")

                return update_workflow_failed(state, error_msg)

        except Exception as e:
            logger.error(
                f"[{workflow_id}] Critic {critic_name} failed: {e}",
                exc_info=True,
            )
            error_msg = f"Critic {critic_name} failed: {str(e)}"
            # Emit workflow_failed event
            if EVENTS_ENABLED and get_event_emitter:
                try:
                    emitter = get_event_emitter(workflow_id)
                    emitter.emit_workflow_failed(error_msg, critic_name)
                except Exception as emit_err:
                    logger.warning(f"Failed to emit workflow_failed event: {emit_err}")

            # Log workflow_failed to audit trail
            if AUDIT_ENABLED:
                try:
                    audit = _get_audit_service()
                    if audit:
                        audit.log_workflow_failed(
                            workflow_run_id=workflow_id,
                            error=error_msg,
                            failed_agent=critic_name,
                        )
                except Exception as audit_err:
                    logger.warning(f"Failed to log workflow_failed to audit: {audit_err}")

            return update_workflow_failed(state, error_msg)

    return wrapped_critic


def _get_agent_for_phase(phase: str) -> str:
    """Get the agent name for a workflow phase.

    Args:
        phase: The workflow phase name.

    Returns:
        The agent name for that phase.
    """
    phase_to_agent = {
        "extraction": "extractor",
        "reconciliation": "reconciler",
        "classification": "classifier",
    }
    return phase_to_agent.get(phase, phase)


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
    # Create a minimal critic feedback object for the retry state update
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


# --- StateGraph Builder ---


def build_workflow_graph(
    agent_functions: dict[str, AgentFunction],
    critic_functions: dict[str, Callable[[WorkflowState], tuple[CriticDecision, str | None]]],
    workflows_config: dict[str, Any] | None = None,
) -> StateGraph:
    """Build the LangGraph StateGraph driven by workflows.yaml (v1.2).

    Reads nodes and edges from the YAML config so that graph topology
    changes require only YAML edits, not Python changes.

    Args:
        agent_functions: Map of agent name → agent function.
        critic_functions: Map of critic name → critic function (returns decision tuple).
        workflows_config: Pre-loaded workflows config (loaded from file if not provided).

    Returns:
        StateGraph ready for compilation.

    Raises:
        ValueError: If a node references a function not in the provided maps.
        ConfigError: If workflows config cannot be loaded.
    """
    if workflows_config is None:
        workflows_config = load_workflows_config()

    nodes_cfg = workflows_config.get("nodes", {})
    edges_cfg = workflows_config.get("edges", [])
    workflow_meta = workflows_config.get("workflow", {})

    # Combine both function maps for lookup
    all_functions: dict[str, Any] = {**agent_functions, **critic_functions}

    graph = StateGraph(WorkflowState)

    # --- Add nodes from YAML ---
    for node_name, node_def in nodes_cfg.items():
        node_type = node_def.get("type")

        if node_type == "end":
            # End nodes are handled via graph.add_edge(..., END) — skip
            continue

        if node_type == "agent":
            agent_key = node_def.get("agent", node_name)

            if agent_key in critic_functions:
                # Determine phase from agent key for the critic wrapper
                phase = _phase_for_critic(agent_key)
                wrapped = create_critic_node(
                    agent_key,
                    critic_functions[agent_key],
                    phase,
                )
            elif agent_key in agent_functions:
                wrapped = create_agent_node(
                    agent_key,
                    agent_functions[agent_key],
                )
            else:
                raise ValueError(
                    f"Node '{node_name}' references agent '{agent_key}' "
                    f"but no matching function was provided"
                )

            graph.add_node(node_name, wrapped)

    # --- Set entry point from YAML ---
    entry_point = workflow_meta.get("entry_point", "__start__")
    if entry_point == "__start__":
        # __start__ is a LangGraph sentinel; first unconditional edge from it
        # sets the real entry node
        for edge in edges_cfg:
            if edge.get("from") == "__start__" and "to" in edge:
                graph.set_entry_point(edge["to"])
                break
    else:
        graph.set_entry_point(entry_point)

    # --- Add edges from YAML ---
    for edge in edges_cfg:
        from_node = edge.get("from")

        if from_node == "__start__":
            continue  # handled above via set_entry_point

        if "to" in edge:
            # Unconditional edge
            to_node = edge["to"]
            if to_node == "end" or to_node not in nodes_cfg:
                graph.add_edge(from_node, END)
            else:
                graph.add_edge(from_node, to_node)

        elif "condition" in edge:
            # Conditional edge — load routing function from dotted path
            condition_cfg = edge["condition"]
            fn_path = condition_cfg["fn"]
            routing_fn = resolve_callable(fn_path)

            raw_routes = condition_cfg.get("routes", {})
            # Map "end" sentinel and "default" key to LangGraph END
            routes_map = {}
            for key, target in raw_routes.items():
                if key == "default":
                    continue
                if target == "end" or target not in nodes_cfg:
                    routes_map[key] = END
                else:
                    routes_map[key] = target

            graph.add_conditional_edges(from_node, routing_fn, routes_map)

    return graph


def _phase_for_critic(critic_name: str) -> Literal["extraction", "reconciliation", "classification"]:
    """Map critic agent key to its workflow phase.

    Args:
        critic_name: The critic agent key (e.g. "critic_1").

    Returns:
        Phase name for use in create_critic_node().
    """
    phase_map = {
        "critic_1": "extraction",
        "critic_2": "reconciliation",
        "critic_3": "classification",
    }
    phase = phase_map.get(critic_name)
    if phase is None:
        raise ValueError(
            f"Unknown critic '{critic_name}'. "
            f"Expected one of: {list(phase_map.keys())}"
        )
    return phase


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
    start_time = datetime.now()

    # Mark workflow as started
    state = update_workflow_started(initial_state)

    # Log workflow_started to audit trail
    documents = initial_state.get("documents", [])
    if AUDIT_ENABLED:
        try:
            audit = _get_audit_service()
            if audit:
                audit.log_workflow_started(
                    workflow_run_id=workflow_id,
                    document_count=len(documents),
                )
        except Exception as e:
            logger.warning(f"Failed to log workflow_started to audit: {e}")

    try:
        # Run the workflow
        final_state = await compiled_workflow.ainvoke(state)

        status = final_state.get("status", "unknown")
        duration_seconds = (datetime.now() - start_time).total_seconds()
        logger.info(f"[{workflow_id}] Workflow completed with status: {status}")

        # Emit workflow completion event
        if EVENTS_ENABLED and get_event_emitter:
            try:
                emitter = get_event_emitter(workflow_id)
                if status == "completed":
                    summary = _generate_workflow_summary(final_state)
                    await emitter.emit_workflow_completed_async(duration_seconds, summary)
                elif status == "failed":
                    error = final_state.get("failure_reason", "Unknown error")
                    await emitter.emit_workflow_failed_async(error)
            except Exception as e:
                logger.warning(f"Failed to emit workflow completion event: {e}")

        # Log workflow completion to audit trail
        if AUDIT_ENABLED:
            try:
                audit = _get_audit_service()
                if audit:
                    if status == "completed":
                        summary = _generate_workflow_summary(final_state)
                        audit.log_workflow_completed(
                            workflow_run_id=workflow_id,
                            duration_seconds=duration_seconds,
                            csm_count=summary.get("csm_count", 0),
                            non_csm_count=summary.get("non_csm_count", 0),
                        )
                    elif status == "failed":
                        error = final_state.get("failure_reason", "Unknown error")
                        audit.log_workflow_failed(
                            workflow_run_id=workflow_id,
                            error=error,
                        )
            except Exception as e:
                logger.warning(f"Failed to log workflow completion to audit: {e}")

        return final_state

    except Exception as e:
        logger.error(f"[{workflow_id}] Workflow execution failed: {e}", exc_info=True)
        error_msg = f"Workflow execution failed: {str(e)}"
        # Emit workflow_failed event
        if EVENTS_ENABLED and get_event_emitter:
            try:
                emitter = get_event_emitter(workflow_id)
                await emitter.emit_workflow_failed_async(error_msg)
            except Exception as emit_err:
                logger.warning(f"Failed to emit workflow_failed event: {emit_err}")

        # Log workflow_failed to audit trail
        if AUDIT_ENABLED:
            try:
                audit = _get_audit_service()
                if audit:
                    audit.log_workflow_failed(
                        workflow_run_id=workflow_id,
                        error=error_msg,
                    )
            except Exception as audit_err:
                logger.warning(f"Failed to log workflow_failed to audit: {audit_err}")

        return update_workflow_failed(state, error_msg)


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
    start_time = datetime.now()

    # Mark workflow as started
    state = update_workflow_started(initial_state)

    # Log workflow_started to audit trail
    documents = initial_state.get("documents", [])
    if AUDIT_ENABLED:
        try:
            audit = _get_audit_service()
            if audit:
                audit.log_workflow_started(
                    workflow_run_id=workflow_id,
                    document_count=len(documents),
                )
        except Exception as e:
            logger.warning(f"Failed to log workflow_started to audit: {e}")

    try:
        # Run the workflow
        final_state = compiled_workflow.invoke(state)

        status = final_state.get("status", "unknown")
        duration_seconds = (datetime.now() - start_time).total_seconds()
        logger.info(f"[{workflow_id}] Workflow completed with status: {status}")

        # Emit workflow completion event
        if EVENTS_ENABLED and get_event_emitter:
            try:
                emitter = get_event_emitter(workflow_id)
                if status == "completed":
                    summary = _generate_workflow_summary(final_state)
                    emitter.emit_workflow_completed(duration_seconds, summary)
                elif status == "failed":
                    error = final_state.get("failure_reason", "Unknown error")
                    emitter.emit_workflow_failed(error)
            except Exception as e:
                logger.warning(f"Failed to emit workflow completion event: {e}")

        # Log workflow completion to audit trail
        if AUDIT_ENABLED:
            try:
                audit = _get_audit_service()
                if audit:
                    if status == "completed":
                        summary = _generate_workflow_summary(final_state)
                        audit.log_workflow_completed(
                            workflow_run_id=workflow_id,
                            duration_seconds=duration_seconds,
                            csm_count=summary.get("csm_count", 0),
                            non_csm_count=summary.get("non_csm_count", 0),
                        )
                    elif status == "failed":
                        error = final_state.get("failure_reason", "Unknown error")
                        audit.log_workflow_failed(
                            workflow_run_id=workflow_id,
                            error=error,
                        )
            except Exception as e:
                logger.warning(f"Failed to log workflow completion to audit: {e}")

        return final_state

    except Exception as e:
        logger.error(f"[{workflow_id}] Workflow execution failed: {e}", exc_info=True)
        error_msg = f"Workflow execution failed: {str(e)}"
        # Emit workflow_failed event
        if EVENTS_ENABLED and get_event_emitter:
            try:
                emitter = get_event_emitter(workflow_id)
                emitter.emit_workflow_failed(error_msg)
            except Exception as emit_err:
                logger.warning(f"Failed to emit workflow_failed event: {emit_err}")

        # Log workflow_failed to audit trail
        if AUDIT_ENABLED:
            try:
                audit = _get_audit_service()
                if audit:
                    audit.log_workflow_failed(
                        workflow_run_id=workflow_id,
                        error=error_msg,
                    )
            except Exception as audit_err:
                logger.warning(f"Failed to log workflow_failed to audit: {audit_err}")

        return update_workflow_failed(state, error_msg)


def _generate_workflow_summary(state: WorkflowState) -> dict[str, Any]:
    """Generate a summary of workflow results.

    Args:
        state: Final workflow state.

    Returns:
        Summary dictionary with statistics.
    """
    csm_list = state.get("csm_list", [])
    non_csm_list = state.get("non_csm_list", [])
    documents = state.get("documents", [])

    return {
        "total_documents": len(documents),
        "total_persons": len(csm_list) + len(non_csm_list),
        "csm_count": len(csm_list),
        "non_csm_count": len(non_csm_list),
        "extraction_retries": state.get("extraction_retry_count", 0),
        "reconciliation_retries": state.get("reconciliation_retry_count", 0),
        "classification_retries": state.get("classification_retry_count", 0),
    }
