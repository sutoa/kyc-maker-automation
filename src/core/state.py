"""Workflow state management for LangGraph-based KYC processing.

This module defines:
- WorkflowState: TypedDict for LangGraph state management
- State initialization from uploaded documents
- State update helpers for each agent phase

The state flows through agents in this order:
extractor -> critic_1 -> reconciler -> critic_2 -> classifier -> critic_3 -> formatter
"""

from typing import Literal, TypedDict
from uuid import uuid4

from src.models.output import DocumentManifestEntry
from src.models.person import (
    ClassifiedPerson,
    DuplicateGroup,
    ExtractedPerson,
    ReconciledPerson,
)
from src.models.workflow import CriticFeedback
from src.services.document import DocumentInput


# Maximum retry attempts before critic fails the workflow
MAX_RETRY_COUNT = 4


class WorkflowState(TypedDict, total=False):
    """Shared state object passed through the LangGraph workflow.

    This TypedDict defines all fields that can be present in the workflow state.
    Using total=False allows partial updates during state transitions.
    """

    # Input - set at initialization
    workflow_id: str
    documents: list[DocumentInput]

    # Extraction phase
    extracted_persons: list[ExtractedPerson]
    extraction_retry_count: int
    extraction_feedback: str | None  # Feedback from critic_1 for retry

    # Reconciliation phase
    reconciled_persons: list[ReconciledPerson]
    duplicate_groups: list[DuplicateGroup]  # Audit trail for merges
    reconciliation_retry_count: int
    reconciliation_feedback: str | None  # Feedback from critic_2 for retry

    # Classification phase
    classified_persons: list[ClassifiedPerson]
    classification_retry_count: int
    classification_feedback: str | None  # Feedback from critic_3 for retry

    # Critic feedback (latest from any critic)
    last_critic_feedback: CriticFeedback | None

    # Final output (populated by formatter)
    document_manifest: list[DocumentManifestEntry]
    csm_list: list[ClassifiedPerson]
    non_csm_list: list[ClassifiedPerson]

    # Status tracking
    current_agent: str
    status: Literal["pending", "in_progress", "completed", "failed"]
    failure_reason: str | None


def create_initial_state(
    documents: list[DocumentInput],
    workflow_id: str | None = None,
) -> WorkflowState:
    """Create initial workflow state from uploaded documents.

    Args:
        documents: List of DocumentInput objects with extracted text.
        workflow_id: Optional workflow ID (generated if not provided).

    Returns:
        WorkflowState initialized with documents and default values.
    """
    return WorkflowState(
        workflow_id=workflow_id or str(uuid4()),
        documents=documents,
        extracted_persons=[],
        extraction_retry_count=0,
        extraction_feedback=None,
        reconciled_persons=[],
        duplicate_groups=[],
        reconciliation_retry_count=0,
        reconciliation_feedback=None,
        classified_persons=[],
        classification_retry_count=0,
        classification_feedback=None,
        last_critic_feedback=None,
        document_manifest=[],
        csm_list=[],
        non_csm_list=[],
        current_agent="extractor",
        status="pending",
        failure_reason=None,
    )


# --- Extraction Phase Update Helpers ---


def update_extraction_result(
    state: WorkflowState,
    extracted_persons: list[ExtractedPerson],
) -> WorkflowState:
    """Update state after extractor agent completes.

    Args:
        state: Current workflow state.
        extracted_persons: List of persons extracted from documents.

    Returns:
        Updated state with extraction results.
    """
    return WorkflowState(
        **{
            **state,
            "extracted_persons": extracted_persons,
            "current_agent": "critic_1",
        }
    )


def update_extraction_retry(
    state: WorkflowState,
    feedback: str,
    critic_feedback: CriticFeedback,
) -> WorkflowState:
    """Update state when critic_1 requests extraction retry.

    Args:
        state: Current workflow state.
        feedback: Text feedback for the extractor to improve.
        critic_feedback: Full critic feedback object.

    Returns:
        Updated state with incremented retry count and feedback.
    """
    return WorkflowState(
        **{
            **state,
            "extraction_retry_count": state.get("extraction_retry_count", 0) + 1,
            "extraction_feedback": feedback,
            "last_critic_feedback": critic_feedback,
            "current_agent": "extractor",
        }
    )


def update_extraction_passed(state: WorkflowState) -> WorkflowState:
    """Update state when critic_1 approves extraction.

    Args:
        state: Current workflow state.

    Returns:
        Updated state ready for reconciliation phase.
    """
    return WorkflowState(
        **{
            **state,
            "extraction_feedback": None,
            "current_agent": "reconciler",
        }
    )


# --- Reconciliation Phase Update Helpers ---


def update_reconciliation_result(
    state: WorkflowState,
    reconciled_persons: list[ReconciledPerson],
    duplicate_groups: list[DuplicateGroup],
) -> WorkflowState:
    """Update state after reconciler agent completes.

    Args:
        state: Current workflow state.
        reconciled_persons: Deduplicated persons list.
        duplicate_groups: Audit trail of merged records.

    Returns:
        Updated state with reconciliation results.
    """
    return WorkflowState(
        **{
            **state,
            "reconciled_persons": reconciled_persons,
            "duplicate_groups": duplicate_groups,
            "current_agent": "critic_2",
        }
    )


def update_reconciliation_retry(
    state: WorkflowState,
    feedback: str,
    critic_feedback: CriticFeedback,
) -> WorkflowState:
    """Update state when critic_2 requests reconciliation retry.

    Args:
        state: Current workflow state.
        feedback: Text feedback for the reconciler to improve.
        critic_feedback: Full critic feedback object.

    Returns:
        Updated state with incremented retry count and feedback.
    """
    return WorkflowState(
        **{
            **state,
            "reconciliation_retry_count": state.get("reconciliation_retry_count", 0) + 1,
            "reconciliation_feedback": feedback,
            "last_critic_feedback": critic_feedback,
            "current_agent": "reconciler",
        }
    )


def update_reconciliation_passed(state: WorkflowState) -> WorkflowState:
    """Update state when critic_2 approves reconciliation.

    Args:
        state: Current workflow state.

    Returns:
        Updated state ready for classification phase.
    """
    return WorkflowState(
        **{
            **state,
            "reconciliation_feedback": None,
            "current_agent": "classifier",
        }
    )


# --- Classification Phase Update Helpers ---


def update_classification_result(
    state: WorkflowState,
    classified_persons: list[ClassifiedPerson],
) -> WorkflowState:
    """Update state after classifier agent completes.

    Args:
        state: Current workflow state.
        classified_persons: Persons with CSM/NON_CSM classification.

    Returns:
        Updated state with classification results.
    """
    return WorkflowState(
        **{
            **state,
            "classified_persons": classified_persons,
            "current_agent": "critic_3",
        }
    )


def update_classification_retry(
    state: WorkflowState,
    feedback: str,
    critic_feedback: CriticFeedback,
) -> WorkflowState:
    """Update state when critic_3 requests classification retry.

    Args:
        state: Current workflow state.
        feedback: Text feedback for the classifier to improve.
        critic_feedback: Full critic feedback object.

    Returns:
        Updated state with incremented retry count and feedback.
    """
    return WorkflowState(
        **{
            **state,
            "classification_retry_count": state.get("classification_retry_count", 0) + 1,
            "classification_feedback": feedback,
            "last_critic_feedback": critic_feedback,
            "current_agent": "classifier",
        }
    )


def update_classification_passed(state: WorkflowState) -> WorkflowState:
    """Update state when critic_3 approves classification.

    Args:
        state: Current workflow state.

    Returns:
        Updated state ready for formatting phase.
    """
    return WorkflowState(
        **{
            **state,
            "classification_feedback": None,
            "current_agent": "formatter",
        }
    )


# --- Output Phase Update Helpers ---


def update_final_output(
    state: WorkflowState,
    document_manifest: list[DocumentManifestEntry],
    csm_list: list[ClassifiedPerson],
    non_csm_list: list[ClassifiedPerson],
) -> WorkflowState:
    """Update state with final formatted output.

    Args:
        state: Current workflow state.
        document_manifest: List of document metadata entries.
        csm_list: Persons classified as CSM.
        non_csm_list: Persons classified as NON_CSM.

    Returns:
        Updated state with final output and completed status.
    """
    return WorkflowState(
        **{
            **state,
            "document_manifest": document_manifest,
            "csm_list": csm_list,
            "non_csm_list": non_csm_list,
            "status": "completed",
            "current_agent": "",
        }
    )


# --- Failure Update Helpers ---


def update_workflow_failed(
    state: WorkflowState,
    reason: str,
    critic_feedback: CriticFeedback | None = None,
) -> WorkflowState:
    """Update state when workflow fails.

    Args:
        state: Current workflow state.
        reason: Human-readable failure reason.
        critic_feedback: Optional critic feedback if failure was due to max retries.

    Returns:
        Updated state with failed status.
    """
    return WorkflowState(
        **{
            **state,
            "status": "failed",
            "failure_reason": reason,
            "last_critic_feedback": critic_feedback or state.get("last_critic_feedback"),
        }
    )


def update_workflow_started(state: WorkflowState) -> WorkflowState:
    """Update state when workflow begins processing.

    Args:
        state: Current workflow state.

    Returns:
        Updated state with in_progress status.
    """
    return WorkflowState(
        **{
            **state,
            "status": "in_progress",
        }
    )


# --- State Query Helpers ---


def get_retry_count(state: WorkflowState, phase: str) -> int:
    """Get the current retry count for a phase.

    Args:
        state: Current workflow state.
        phase: One of 'extraction', 'reconciliation', or 'classification'.

    Returns:
        Current retry count for the phase.

    Raises:
        ValueError: If phase is invalid.
    """
    if phase == "extraction":
        return state.get("extraction_retry_count", 0)
    elif phase == "reconciliation":
        return state.get("reconciliation_retry_count", 0)
    elif phase == "classification":
        return state.get("classification_retry_count", 0)
    else:
        raise ValueError(f"Invalid phase: {phase}. Must be one of: extraction, reconciliation, classification")


def can_retry(state: WorkflowState, phase: str) -> bool:
    """Check if retry is allowed for a phase.

    Args:
        state: Current workflow state.
        phase: One of 'extraction', 'reconciliation', or 'classification'.

    Returns:
        True if retry count is below MAX_RETRY_COUNT.
    """
    return get_retry_count(state, phase) < MAX_RETRY_COUNT


def get_feedback(state: WorkflowState, phase: str) -> str | None:
    """Get the current feedback for a phase.

    Args:
        state: Current workflow state.
        phase: One of 'extraction', 'reconciliation', or 'classification'.

    Returns:
        Feedback string or None if no feedback.

    Raises:
        ValueError: If phase is invalid.
    """
    if phase == "extraction":
        return state.get("extraction_feedback")
    elif phase == "reconciliation":
        return state.get("reconciliation_feedback")
    elif phase == "classification":
        return state.get("classification_feedback")
    else:
        raise ValueError(f"Invalid phase: {phase}. Must be one of: extraction, reconciliation, classification")
