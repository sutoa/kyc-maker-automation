"""Conditional edge routing functions for the KYC workflow.

Each function is referenced by fully-qualified name in workflows.yaml:

  edges:
    - from: critic_1
      condition:
        fn: src.core.conditions.route_on_critic_decision
        routes:
          pass:       reconciler
          fail_retry: extractor
          fail_max:   end

All critics write their decision to the same state key (last_critic_feedback).
The single generic routing function reads that key and returns the route string
that LangGraph maps to the next node via the condition.routes block.
"""

import logging
from typing import Literal

from langgraph.graph import END
from langgraph.types import Command

from src.core.state import WorkflowState
from src.models.enums import CriticDecision

logger = logging.getLogger(__name__)

_DECISION_TO_ROUTE = {
    CriticDecision.PASS: "pass",
    CriticDecision.FAIL_RETRY: "fail_retry",
    CriticDecision.FAIL_MAX: "fail_max",
}


def route_on_critic_decision(state: WorkflowState) -> str:
    """Generic routing function for all critic conditional edges.

    Reads last_critic_feedback.decision from state and maps it to
    the route key used in the edges condition.routes block.

    All three critics (critic_1, critic_2, critic_3) point to this
    single function — the specific routes (which node to go to) are
    declared per-edge in workflows.yaml, not here.

    Args:
        state: Current workflow state.

    Returns:
        "pass" | "fail_retry" | "fail_max"
    """
    feedback = state.get("last_critic_feedback")

    if feedback is None:
        logger.warning(
            f"[{state.get('workflow_id', 'unknown')}] "
            "route_on_critic_decision: no feedback found in state, defaulting to pass"
        )
        return "pass"

    decision = getattr(feedback, "decision", None)
    route = _DECISION_TO_ROUTE.get(decision)

    if route is None:
        logger.warning(
            f"[{state.get('workflow_id', 'unknown')}] "
            f"route_on_critic_decision: unexpected decision '{decision}', routing to fail_max"
        )
        return "fail_max"

    return route


def route_on_extractor_critic_decision(
    state: WorkflowState,
) -> "Command[Literal['formatter', 'extractor', END]]":
    """Router node function for the extractor critic loop.

    Reads extractor_critic_feedback from state. On pass, routes to formatter.
    On fail, increments extraction_retry_count and routes back to extractor.
    On fail with retry count >= 4, routes to END.

    Returns a Command so routing and state update happen atomically.
    """
    feedback = state.get("extractor_critic_feedback")
    retry_count = state.get("extraction_retry_count", 0) or 0

    if feedback is None or getattr(feedback, "status", "pass") == "pass":
        return Command(goto="formatter")

    if retry_count >= 4:
        logger.info(
            f"[{state.get('workflow_id', 'unknown')}] "
            "extractor_critic_router: max retries reached → END"
        )
        return Command(
            goto=END,
            update={
                "status": "failed",
                "failure_reason": "Extraction failed: maximum retries exceeded.",
            },
        )

    logger.info(
        f"[{state.get('workflow_id', 'unknown')}] "
        f"extractor_critic_router: fail_retry #{retry_count + 1} → extractor"
    )
    return Command(
        goto="extractor",
        update={"extraction_retry_count": retry_count + 1},
    )
