"""LangGraph workflow engine for KYC document processing.

This module defines:
- Generic agent node wrapper with logging, events, and audit trail
- YAML-driven StateGraph builder (nodes + edges from workflows.yaml)
- Workflow compilation with checkpointer, observability, and runtime config
- Workflow execution helpers (async and sync)

All graph topology, agent configuration, and runtime settings are read
from workflows.yaml and agents.yaml. No hardcoded agent names, phases,
retry counts, or model names.
"""

import logging
import os
from datetime import datetime
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from src.config.loader import (
    build_agent_functions,
    load_agents_config,
    load_workflows_config,
    resolve_callable,
)
from src.core.state import (
    WorkflowState,
    update_workflow_failed,
    update_workflow_started,
)
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
    retry_count_key: str | None = None,
) -> Callable[[WorkflowState], WorkflowState]:
    """Create a wrapped agent node with logging and state updates.

    Args:
        agent_name: Name of the agent (for logging).
        agent_fn: The actual agent function to execute.
        retry_count_key: State key holding this agent's retry count (read for logging).

    Returns:
        Wrapped function that handles logging, timing, and state updates.
    """

    def wrapped_agent(state: WorkflowState) -> WorkflowState:
        workflow_id = state.get("workflow_id", "unknown")
        retry_count = state.get(retry_count_key, 0) if retry_count_key else 0

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
    """Generate a brief output summary for event emission."""
    output_key_counts = {
        "extracted_persons": lambda s: f"Extracted {len(s.get('extracted_persons', []))} person(s)",
        "reconciled_persons": lambda s: (
            f"Reconciled to {len(s.get('reconciled_persons', []))} person(s), "
            f"{len(s.get('duplicate_groups', []))} duplicate group(s)"
        ),
        "classified_persons": lambda s: (
            f"Classified {len(s.get('classified_persons', []))} person(s): "
            f"{sum(1 for p in s.get('classified_persons', []) if getattr(p, 'classification', '') == 'CSM')} CSM"
        ),
    }
    for key, summarizer in output_key_counts.items():
        if state.get(key) is not None:
            # Only return summary for the agent that writes this key
            persons = state.get(key, [])
            if persons:
                return summarizer(state)
    csm = state.get("csm_list", [])
    non_csm = state.get("non_csm_list", [])
    if csm or non_csm:
        return f"Output: {len(csm)} CSM, {len(non_csm)} NON_CSM"
    return None


def _generate_output_summary_dict(agent_name: str, state: WorkflowState) -> dict[str, Any]:
    """Generate an output summary dict for audit logging."""
    summary: dict[str, Any] = {}
    for key in ("extracted_persons", "reconciled_persons", "classified_persons"):
        items = state.get(key)
        if items is not None:
            summary[f"{key}_count"] = len(items)
    for key in ("duplicate_groups", "csm_list", "non_csm_list"):
        items = state.get(key)
        if items is not None:
            summary[f"{key}_count"] = len(items)
    return summary


# --- StateGraph Builder ---


def build_workflow_graph(
    functions: dict[str, AgentFunction],
    workflows_config: dict[str, Any] | None = None,
) -> StateGraph:
    """Build the LangGraph StateGraph driven by workflows.yaml (v1.2).

    All topology, agents, and runtime settings come from YAML — no hardcoding.

    Args:
        functions: Single map of node_name → agent callable (built by build_agent_functions).
        workflows_config: Pre-loaded workflows config (loaded from file if not provided).

    Returns:
        StateGraph ready for compilation.
    """
    if workflows_config is None:
        workflows_config = load_workflows_config()

    nodes_cfg = workflows_config.get("nodes", {})
    edges_cfg = workflows_config.get("edges", [])
    workflow_meta = workflows_config.get("workflow", {})

    graph = StateGraph(WorkflowState)

    # --- Add nodes from YAML ---
    for node_name, node_def in nodes_cfg.items():
        if node_def.get("type") == "end":
            continue  # end nodes handled via add_edge(..., END)

        if node_def.get("type") == "router":
            routing_fn = resolve_callable(node_def["fn"])
            graph.add_node(node_name, routing_fn)
            continue

        agent_fn = functions.get(node_name)
        if agent_fn is None:
            raise ValueError(
                f"Node '{node_name}' has no matching function in the provided functions dict"
            )
        retry_count_key = node_def.get("retry_count_key")
        wrapped = create_agent_node(node_name, agent_fn, retry_count_key=retry_count_key)
        graph.add_node(node_name, wrapped)

    # --- Add edges from YAML ---
    for edge in edges_cfg:
        from_node = edge.get("from")

        if from_node == "__start__":
            if "to" in edge:
                graph.add_edge(START, edge["to"])
            continue

        if "to" in edge:
            to_node = edge["to"]
            if to_node == "end" or to_node not in nodes_cfg:
                graph.add_edge(from_node, END)
            else:
                graph.add_edge(from_node, to_node)

        elif "condition" in edge:
            condition_cfg = edge["condition"]
            routing_fn = resolve_callable(condition_cfg["fn"])
            raw_routes = condition_cfg.get("routes", {})
            routes_map = {
                key: (END if (target == "end" or target not in nodes_cfg) else target)
                for key, target in raw_routes.items()
                if key != "default"
            }
            graph.add_conditional_edges(from_node, routing_fn, routes_map)

    return graph


def compile_workflow(
    workflows_config: dict[str, Any] | None = None,
    agents_config: dict[str, Any] | None = None,
) -> Any:
    """Build and compile the workflow graph from YAML config.

    Loads both config files if not provided, builds all agent functions via
    the factory, wires checkpointer and observability from runtime config.

    Args:
        workflows_config: Pre-loaded workflows config (loaded from file if not provided).
        agents_config: Pre-loaded agents config (loaded from file if not provided).

    Returns:
        Compiled workflow ready for invocation.
    """
    if workflows_config is None:
        workflows_config = load_workflows_config()
    if agents_config is None:
        agents_config = load_agents_config()

    # Wire observability from YAML before building
    observability_cfg = workflows_config.get("observability", {})
    if observability_cfg.get("provider") == "langsmith":
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_PROJECT"] = observability_cfg.get("project", "kyc")
        logger.info(
            f"LangSmith tracing enabled for project '{observability_cfg.get('project')}'"
        )

    # Build all agent functions from YAML
    functions = build_agent_functions(agents_config, workflows_config)

    graph = build_workflow_graph(functions, workflows_config)

    # Wire checkpointer from runtime config
    runtime_cfg = workflows_config.get("runtime", {})
    checkpointer = _build_checkpointer(runtime_cfg)

    interrupt_before = runtime_cfg.get("interrupt_before", []) or []
    interrupt_after = runtime_cfg.get("interrupt_after", []) or []

    compile_kwargs: dict[str, Any] = {}
    if checkpointer:
        compile_kwargs["checkpointer"] = checkpointer
    if interrupt_before:
        compile_kwargs["interrupt_before"] = interrupt_before
    if interrupt_after:
        compile_kwargs["interrupt_after"] = interrupt_after

    return graph.compile(**compile_kwargs)


def _build_checkpointer(runtime_cfg: dict[str, Any]) -> Any | None:
    """Build a LangGraph checkpointer from runtime config."""
    checkpointer_type = runtime_cfg.get("checkpointer", "memory")
    uri = runtime_cfg.get("checkpointer_uri", "")

    if checkpointer_type == "sqlite" and uri:
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
            return SqliteSaver.from_conn_string(uri)
        except ImportError:
            logger.warning("langgraph-checkpoint-sqlite not installed, using MemorySaver")
    elif checkpointer_type == "memory":
        try:
            from langgraph.checkpoint.memory import MemorySaver
            return MemorySaver()
        except ImportError:
            pass

    return None


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
    """Synchronous wrapper around run_workflow.

    Prefer ``await run_workflow(...)`` in async contexts.
    """
    import asyncio
    return asyncio.run(run_workflow(compiled_workflow, initial_state))


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
