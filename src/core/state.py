"""Workflow state management for LangGraph-based KYC processing."""

from typing import Literal, TypedDict
from uuid import uuid4

from src.models.output import DocumentManifestEntry
from src.models.person import ClassifiedPerson, DuplicateGroup, ExtractedPerson, ReconciledPerson
from src.models.workflow import CriticFeedback, ExtractorCriticFeedback
from src.services.document import DocumentInput


class WorkflowState(TypedDict, total=False):
    """Shared state object passed through the LangGraph workflow."""

    # Input
    workflow_id: str
    documents: list[DocumentInput]

    # Extraction phase
    extracted_persons: list[ExtractedPerson]
    extraction_retry_count: int
    extractor_critic_feedback: ExtractorCriticFeedback | None

    # Reconciliation phase (inactive — re-enabled when reconciler is added back)
    reconciled_persons: list[ReconciledPerson]
    duplicate_groups: list[DuplicateGroup]
    reconciliation_retry_count: int
    reconciliation_feedback: str | None

    # Classification phase (inactive — re-enabled when classifier is added back)
    classified_persons: list[ClassifiedPerson]
    classification_retry_count: int
    classification_feedback: str | None

    # Generic critic feedback (used by rule-based critics)
    last_critic_feedback: CriticFeedback | None

    # Output
    document_manifest: list[DocumentManifestEntry]
    csm_list: list[ClassifiedPerson]
    non_csm_list: list[ClassifiedPerson]
    csm_report: str | None

    # Status tracking
    current_agent: str
    status: Literal["pending", "in_progress", "completed", "failed"]
    failure_reason: str | None


def create_initial_state(
    documents: list[DocumentInput],
    workflow_id: str | None = None,
) -> WorkflowState:
    """Create initial workflow state from uploaded documents."""
    return WorkflowState(
        workflow_id=workflow_id or str(uuid4()),
        documents=documents,
        extracted_persons=[],
        extraction_retry_count=0,
        extractor_critic_feedback=None,
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
        csm_report=None,
        current_agent="extractor",
        status="pending",
        failure_reason=None,
    )


def update_workflow_started(state: WorkflowState) -> WorkflowState:
    """Return new state with status set to in_progress."""
    return WorkflowState(**{**state, "status": "in_progress"})


def update_workflow_failed(
    state: WorkflowState,
    reason: str,
    critic_feedback: CriticFeedback | None = None,
) -> WorkflowState:
    """Return new state with failed status and failure reason."""
    return WorkflowState(**{
        **state,
        "status": "failed",
        "failure_reason": reason,
        "last_critic_feedback": critic_feedback or state.get("last_critic_feedback"),
    })
