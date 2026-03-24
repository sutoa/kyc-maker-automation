"""Critic agents for KYC document processing workflow.

This module contains all critic agents:
- Critic 1: Validates extraction output
- Critic 2: Validates reconciliation output
- Critic 3: Validates classification output

Each critic returns a 3-outcome decision:
- PASS: Output meets quality standards
- FAIL_RETRY: Output has issues, retry with feedback
- FAIL_MAX: Maximum retries exceeded, workflow fails
"""

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src.core.llm import get_llm_provider
from src.core.llm.base import Message
from src.core.state import MAX_RETRY_COUNT, WorkflowState, get_retry_count
from src.models.enums import CriticDecision
from src.models.person import ClassifiedPerson, ExtractedPerson, ReconciledPerson
from src.models.workflow import (
    ClassificationIssue,
    ExtractionIssue,
    ReconciliationIssue,
)

logger = logging.getLogger(__name__)

# Prompt paths
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


# --- Critic 1: Extraction Validation ---


class Critic1Input(BaseModel):
    """Input contract for Critic 1."""

    extracted_persons: list[ExtractedPerson] = Field(
        ..., description="Extracted persons to validate"
    )
    retry_count: int = Field(..., ge=0, description="Current retry count")


class Critic1Output(BaseModel):
    """Output contract for Critic 1."""

    decision: CriticDecision = Field(..., description="Validation decision")
    issues: list[ExtractionIssue] = Field(
        default_factory=list, description="Issues found"
    )
    feedback: str | None = Field(None, description="Feedback for retry")


def validate_extraction(
    extracted_persons: list[ExtractedPerson],
    retry_count: int,
) -> Critic1Output:
    """Validate extraction output using rule-based checks.

    This performs deterministic validation without LLM:
    - Mandatory fields present
    - Source references provided
    - Page numbers valid

    Args:
        extracted_persons: Persons to validate.
        retry_count: Current retry attempt.

    Returns:
        Critic1Output with decision and any issues.
    """
    issues: list[ExtractionIssue] = []

    for person in extracted_persons:
        # Check mandatory first_name
        if not person.first_name or not person.first_name.strip():
            issues.append(
                ExtractionIssue(
                    extraction_id=person.extraction_id,
                    issue_type="missing_first_name",
                    description=f"Person {person.extraction_id} has empty first_name",
                    severity="error",
                )
            )

        # Check mandatory last_name
        if not person.last_name or not person.last_name.strip():
            issues.append(
                ExtractionIssue(
                    extraction_id=person.extraction_id,
                    issue_type="missing_last_name",
                    description=f"Person {person.extraction_id} has empty last_name",
                    severity="error",
                )
            )

        # Check source references
        if not person.source_references:
            issues.append(
                ExtractionIssue(
                    extraction_id=person.extraction_id,
                    issue_type="missing_source",
                    description=f"Person {person.extraction_id} has no source references",
                    severity="error",
                )
            )
        else:
            # Check page numbers
            for ref in person.source_references:
                if ref.page_number < 1:
                    issues.append(
                        ExtractionIssue(
                            extraction_id=person.extraction_id,
                            issue_type="invalid_page_number",
                            description=f"Person {person.extraction_id} has invalid page_number: {ref.page_number}",
                            severity="error",
                        )
                    )

                # Check confidence (warning only)
                if ref.confidence is not None and ref.confidence < 0.7:
                    issues.append(
                        ExtractionIssue(
                            extraction_id=person.extraction_id,
                            issue_type="low_confidence",
                            description=f"Person {person.extraction_id} has low confidence: {ref.confidence}",
                            severity="warning",
                        )
                    )

    # Determine decision
    error_issues = [i for i in issues if i.severity == "error"]

    if not error_issues:
        return Critic1Output(decision=CriticDecision.PASS, issues=issues)

    if retry_count >= MAX_RETRY_COUNT:
        return Critic1Output(
            decision=CriticDecision.FAIL_MAX,
            issues=issues,
            feedback=f"Maximum retries ({MAX_RETRY_COUNT}) exceeded. Errors: {len(error_issues)}",
        )

    # Build feedback for retry
    feedback_lines = ["Please fix the following extraction issues:"]
    for issue in error_issues:
        feedback_lines.append(f"- {issue.description}")

    return Critic1Output(
        decision=CriticDecision.FAIL_RETRY,
        issues=issues,
        feedback="\n".join(feedback_lines),
    )


def critic_1_agent(state: WorkflowState) -> tuple[CriticDecision, str | None]:
    """Critic 1 agent function for LangGraph workflow.

    Validates extraction output and returns decision with optional feedback.

    Args:
        state: Current workflow state.

    Returns:
        Tuple of (decision, feedback).
    """
    workflow_id = state.get("workflow_id", "unknown")
    logger.info(f"[{workflow_id}] Critic 1 starting validation")

    extracted_persons = state.get("extracted_persons", [])
    retry_count = get_retry_count(state, "extraction")

    # Check if no persons extracted
    if not extracted_persons:
        if retry_count >= MAX_RETRY_COUNT:
            return (
                CriticDecision.FAIL_MAX,
                "No persons extracted after maximum retries",
            )
        return (
            CriticDecision.FAIL_RETRY,
            "No persons were extracted from the documents. Please re-examine the documents and extract all persons mentioned.",
        )

    # Validate extraction
    output = validate_extraction(extracted_persons, retry_count)

    logger.info(
        f"[{workflow_id}] Critic 1 decision: {output.decision.value}, "
        f"issues: {len(output.issues)}"
    )

    return (output.decision, output.feedback)


# --- Critic 2: Reconciliation Validation ---


class Critic2Input(BaseModel):
    """Input contract for Critic 2."""

    reconciled_persons: list[ReconciledPerson] = Field(
        ..., description="Reconciled persons to validate"
    )
    duplicate_groups: list[dict[str, Any]] = Field(
        default_factory=list, description="Duplicate group audit trail"
    )
    retry_count: int = Field(..., ge=0, description="Current retry count")


class Critic2Output(BaseModel):
    """Output contract for Critic 2."""

    decision: CriticDecision = Field(..., description="Validation decision")
    issues: list[ReconciliationIssue] = Field(
        default_factory=list, description="Issues found"
    )
    feedback: str | None = Field(None, description="Feedback for retry")


def validate_reconciliation(
    reconciled_persons: list[ReconciledPerson],
    extracted_count: int,
    retry_count: int,
) -> Critic2Output:
    """Validate reconciliation output.

    Checks:
    - All source references preserved
    - Normalized names present
    - Conflicts properly flagged

    Args:
        reconciled_persons: Reconciled persons to validate.
        extracted_count: Number of originally extracted persons.
        retry_count: Current retry attempt.

    Returns:
        Critic2Output with decision and any issues.
    """
    issues: list[ReconciliationIssue] = []

    # Count total source references
    total_sources = sum(len(p.source_references) for p in reconciled_persons)

    # Check each reconciled person
    for person in reconciled_persons:
        # Check normalized names
        if not person.first_name_normalized:
            issues.append(
                ReconciliationIssue(
                    person_id=person.person_id,
                    issue_type="other",
                    description=f"Person {person.person_id} missing first_name_normalized",
                )
            )

        if not person.last_name_normalized:
            issues.append(
                ReconciliationIssue(
                    person_id=person.person_id,
                    issue_type="other",
                    description=f"Person {person.person_id} missing last_name_normalized",
                )
            )

        # Check source references
        if not person.source_references:
            issues.append(
                ReconciliationIssue(
                    person_id=person.person_id,
                    issue_type="lost_source_reference",
                    description=f"Person {person.person_id} has no source references",
                )
            )

        # Check conflict flagging consistency
        if person.conflicts and not person.has_conflicts:
            issues.append(
                ReconciliationIssue(
                    person_id=person.person_id,
                    issue_type="undetected_conflict",
                    description=f"Person {person.person_id} has conflicts but has_conflicts=False",
                )
            )

    # Determine decision
    error_types = {"lost_source_reference", "missed_duplicate", "incorrect_merge"}
    error_issues = [i for i in issues if i.issue_type in error_types]

    if not error_issues:
        return Critic2Output(decision=CriticDecision.PASS, issues=issues)

    if retry_count >= MAX_RETRY_COUNT:
        return Critic2Output(
            decision=CriticDecision.FAIL_MAX,
            issues=issues,
            feedback=f"Maximum retries exceeded. Errors: {len(error_issues)}",
        )

    feedback_lines = ["Please fix the following reconciliation issues:"]
    for issue in error_issues:
        feedback_lines.append(f"- {issue.description}")

    return Critic2Output(
        decision=CriticDecision.FAIL_RETRY,
        issues=issues,
        feedback="\n".join(feedback_lines),
    )


def critic_2_agent(state: WorkflowState) -> tuple[CriticDecision, str | None]:
    """Critic 2 agent function for LangGraph workflow.

    Validates reconciliation output.

    Args:
        state: Current workflow state.

    Returns:
        Tuple of (decision, feedback).
    """
    workflow_id = state.get("workflow_id", "unknown")
    logger.info(f"[{workflow_id}] Critic 2 starting validation")

    reconciled_persons = state.get("reconciled_persons", [])
    extracted_count = len(state.get("extracted_persons", []))
    retry_count = get_retry_count(state, "reconciliation")

    # Check if no persons reconciled
    if not reconciled_persons:
        if retry_count >= MAX_RETRY_COUNT:
            return (CriticDecision.FAIL_MAX, "No reconciled persons after max retries")
        return (
            CriticDecision.FAIL_RETRY,
            "No persons were reconciled. Please process the extracted persons.",
        )

    output = validate_reconciliation(reconciled_persons, extracted_count, retry_count)

    logger.info(
        f"[{workflow_id}] Critic 2 decision: {output.decision.value}, "
        f"issues: {len(output.issues)}"
    )

    return (output.decision, output.feedback)


# --- Critic 3: Classification Validation ---


class Critic3Input(BaseModel):
    """Input contract for Critic 3."""

    classified_persons: list[ClassifiedPerson] = Field(
        ..., description="Classified persons to validate"
    )
    retry_count: int = Field(..., ge=0, description="Current retry count")


class Critic3Output(BaseModel):
    """Output contract for Critic 3."""

    decision: CriticDecision = Field(..., description="Validation decision")
    issues: list[ClassificationIssue] = Field(
        default_factory=list, description="Issues found"
    )
    feedback: str | None = Field(None, description="Feedback for retry")


def validate_classification(
    classified_persons: list[ClassifiedPerson],
    retry_count: int,
) -> Critic3Output:
    """Validate classification output.

    Checks:
    - Every person has classification
    - Reasoning is non-empty
    - Reasoning references criteria
    - Classification consistent with criteria

    Args:
        classified_persons: Classified persons to validate.
        retry_count: Current retry attempt.

    Returns:
        Critic3Output with decision and any issues.
    """
    issues: list[ClassificationIssue] = []

    # Keywords that indicate criteria citation
    criteria_keywords = [
        "criterion",
        "criteria",
        "executive",
        "management",
        "ownership",
        "signing",
        "authority",
        "control",
        "director",
        "board",
        "shareholder",
    ]

    for person in classified_persons:
        # Check classification present (should always be due to Pydantic)
        if not person.classification:
            issues.append(
                ClassificationIssue(
                    person_id=person.person_id,
                    issue_type="other",
                    description=f"Person {person.person_id} missing classification",
                )
            )
            continue

        # Check reasoning present
        if not person.reasoning or not person.reasoning.strip():
            issues.append(
                ClassificationIssue(
                    person_id=person.person_id,
                    issue_type="missing_reasoning",
                    description=f"Person {person.person_id} has empty reasoning",
                    suggested_correction="Provide detailed reasoning citing specific CSM criteria",
                )
            )
            continue

        # Check reasoning quality - should cite criteria
        reasoning_lower = person.reasoning.lower()
        has_criteria_citation = any(kw in reasoning_lower for kw in criteria_keywords)

        if not has_criteria_citation:
            issues.append(
                ClassificationIssue(
                    person_id=person.person_id,
                    issue_type="weak_reasoning",
                    description=f"Person {person.person_id} reasoning does not cite CSM criteria",
                    suggested_correction="Reasoning should explicitly reference CSM criteria (e.g., 'Criterion 1: Executive Management Role')",
                )
            )

        # Check classification consistency with criteria_met
        if person.classification == "CSM" and not person.criteria_met:
            issues.append(
                ClassificationIssue(
                    person_id=person.person_id,
                    issue_type="inconsistent_classification",
                    description=f"Person {person.person_id} classified as CSM but no criteria_met listed",
                    suggested_correction="List the specific criteria that qualify this person as CSM",
                )
            )

        # Check for supporting evidence (warning)
        if not person.supporting_evidence:
            issues.append(
                ClassificationIssue(
                    person_id=person.person_id,
                    issue_type="missing_evidence",
                    description=f"Person {person.person_id} has no supporting_evidence",
                    suggested_correction="Provide document references supporting the classification",
                )
            )

    # Determine decision
    critical_types = {"missing_reasoning", "incorrect_criteria_citation", "inconsistent_classification"}
    critical_issues = [i for i in issues if i.issue_type in critical_types]

    if not critical_issues:
        return Critic3Output(decision=CriticDecision.PASS, issues=issues)

    if retry_count >= MAX_RETRY_COUNT:
        return Critic3Output(
            decision=CriticDecision.FAIL_MAX,
            issues=issues,
            feedback=f"Maximum retries exceeded. Critical issues: {len(critical_issues)}",
        )

    feedback_lines = ["Please fix the following classification issues:"]
    for issue in critical_issues:
        feedback_lines.append(f"- {issue.description}")
        if issue.suggested_correction:
            feedback_lines.append(f"  Suggestion: {issue.suggested_correction}")

    return Critic3Output(
        decision=CriticDecision.FAIL_RETRY,
        issues=issues,
        feedback="\n".join(feedback_lines),
    )


def critic_3_agent(state: WorkflowState) -> tuple[CriticDecision, str | None]:
    """Critic 3 agent function for LangGraph workflow.

    Validates classification output.

    Args:
        state: Current workflow state.

    Returns:
        Tuple of (decision, feedback).
    """
    workflow_id = state.get("workflow_id", "unknown")
    logger.info(f"[{workflow_id}] Critic 3 starting validation")

    classified_persons = state.get("classified_persons", [])
    retry_count = get_retry_count(state, "classification")

    # Check if no persons classified
    if not classified_persons:
        if retry_count >= MAX_RETRY_COUNT:
            return (CriticDecision.FAIL_MAX, "No classified persons after max retries")
        return (
            CriticDecision.FAIL_RETRY,
            "No persons were classified. Please classify all reconciled persons.",
        )

    output = validate_classification(classified_persons, retry_count)

    logger.info(
        f"[{workflow_id}] Critic 3 decision: {output.decision.value}, "
        f"issues: {len(output.issues)}"
    )

    return (output.decision, output.feedback)
