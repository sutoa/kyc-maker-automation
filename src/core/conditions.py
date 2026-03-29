"""Conditional edge routing functions for the KYC workflow.

Each function is referenced by fully-qualified name in workflows.yaml:

  edges:
    - from: critic_1
      condition:
        fn: src.core.conditions.route_critic_1
        routes:
          pass:       reconciler
          fail_retry: extractor
          fail_max:   end

All three critics write their decision to the same state key
(last_critic_feedback). The routing function reads that key and
returns a string that LangGraph maps to the next node via routes.
"""

import logging

from src.core.state import WorkflowState
from src.models.enums import CriticDecision

logger = logging.getLogger(__name__)


def _route_critic(state: WorkflowState, critic_name: str) -> str:
    """Shared routing logic for all critic edges.

    Reads last_critic_feedback.decision from state and maps it to
    the route key used in the edges condition.routes block.

    Args:
        state: Current workflow state.
        critic_name: Name of the critic (for logging only).

    Returns:
        "pass" | "fail_retry" | "fail_max"
    """
    feedback = state.get("last_critic_feedback")

    if feedback is None:
        logger.warning(
            f"[{state.get('workflow_id', 'unknown')}] "
            f"{critic_name}: no feedback found in state, defaulting to pass"
        )
        return "pass"

    # CriticFeedback is a Pydantic model — access .decision attribute
    decision = getattr(feedback, "decision", None)

    if decision == CriticDecision.PASS:
        return "pass"
    elif decision == CriticDecision.FAIL_RETRY:
        return "fail_retry"
    elif decision == CriticDecision.FAIL_MAX:
        return "fail_max"
    else:
        # Workflow failed mid-node (state.status == "failed")
        logger.warning(
            f"[{state.get('workflow_id', 'unknown')}] "
            f"{critic_name}: unexpected decision '{decision}', routing to fail_max"
        )
        return "fail_max"


def route_critic_1(state: WorkflowState) -> str:
    """Route after critic_1 (extraction validation).

    Returns:
        "pass"       → reconciler
        "fail_retry" → extractor (retry)
        "fail_max"   → end (workflow failed)
    """
    return _route_critic(state, "critic_1")


def route_critic_2(state: WorkflowState) -> str:
    """Route after critic_2 (reconciliation validation).

    Returns:
        "pass"       → classifier
        "fail_retry" → reconciler (retry)
        "fail_max"   → end (workflow failed)
    """
    return _route_critic(state, "critic_2")


def route_critic_3(state: WorkflowState) -> str:
    """Route after critic_3 (classification validation).

    Returns:
        "pass"       → formatter
        "fail_retry" → classifier (retry)
        "fail_max"   → end (workflow failed)
    """
    return _route_critic(state, "critic_3")
