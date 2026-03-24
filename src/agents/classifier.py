"""Classifier agent for KYC document processing.

This agent classifies persons as CSM (Controlling Senior Manager) or NON_CSM
based on their roles, job titles, and other attributes.
"""

import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from src.core.llm import get_llm_provider
from src.core.llm.base import Message
from src.core.state import (
    WorkflowState,
    get_feedback,
    update_classification_result,
)
from src.models.person import (
    ClassifiedPerson,
    EvidenceReference,
    ReconciledPerson,
)

logger = logging.getLogger(__name__)

# Prompt paths
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
CLASSIFIER_PROMPT_PATH = PROMPTS_DIR / "classifier.md"
CSM_DEFINITION_PATH = PROMPTS_DIR / "csm_definition.md"

# German job titles that typically indicate CSM status
CSM_JOB_TITLES = {
    # German titles
    "geschäftsführer",
    "geschäftsführerin",
    "vorstand",
    "vorstandsvorsitzender",
    "vorstandsvorsitzende",
    "aufsichtsrat",
    "aufsichtsratsvorsitzender",
    "aufsichtsratsvorsitzende",
    "prokurist",  # Only with Einzelprokura
    "inhaber",
    "inhaberin",
    "komplementär",
    "liquidator",
    # English equivalents
    "managing director",
    "ceo",
    "chief executive officer",
    "cfo",
    "chief financial officer",
    "coo",
    "chief operating officer",
    "chairman",
    "chairwoman",
    "board member",
    "director",
    "general manager",
    "partner",
    "owner",
    "proprietor",
}

# Job titles that typically indicate NON_CSM status
NON_CSM_JOB_TITLES = {
    "sachbearbeiter",
    "sachbearbeiterin",
    "clerk",
    "assistant",
    "secretary",
    "administrative",
    "employee",
    "staff",
    "analyst",
    "specialist",
}


class ClassifierInput(BaseModel):
    """Input contract for the classifier agent."""

    reconciled_persons: list[ReconciledPerson] = Field(
        ..., description="Reconciled persons to classify"
    )
    csm_definition: str = Field(..., description="CSM definition text")
    retry_feedback: str | None = Field(
        None, description="Feedback from critic if retrying"
    )


class ClassifierOutput(BaseModel):
    """Output contract for the classifier agent."""

    classified_persons: list[ClassifiedPerson] = Field(
        ..., description="Classified persons"
    )


def load_csm_definition() -> str:
    """Load the CSM definition from file.

    Returns:
        CSM definition text.
    """
    if CSM_DEFINITION_PATH.exists():
        return CSM_DEFINITION_PATH.read_text(encoding="utf-8")
    return "CSM criteria not available"


def classify_by_job_title(job_title: str | None) -> tuple[Literal["CSM", "NON_CSM"], str, list[str]]:
    """Classify a person based on their job title using rule-based logic.

    Args:
        job_title: The job title to classify.

    Returns:
        Tuple of (classification, reasoning, criteria_met).
    """
    if not job_title:
        return (
            "NON_CSM",
            "No job title available. Cannot determine CSM status without role information.",
            [],
        )

    title_lower = job_title.lower().strip()

    # Check for CSM indicators
    for csm_title in CSM_JOB_TITLES:
        if csm_title in title_lower:
            # Determine which criterion
            if any(t in title_lower for t in ["geschäftsführer", "managing director", "ceo", "cfo", "coo", "general manager"]):
                criteria = ["Criterion 1: Executive Management Role"]
                reasoning = f"'{job_title}' is an executive management position per Criterion 1."
            elif any(t in title_lower for t in ["vorstand", "board", "chairman", "aufsichtsrat"]):
                criteria = ["Criterion 4: Supervisory Control"]
                reasoning = f"'{job_title}' is a supervisory/board position per Criterion 4."
            elif any(t in title_lower for t in ["inhaber", "owner", "proprietor"]):
                criteria = ["Criterion 2: Significant Ownership"]
                reasoning = f"'{job_title}' indicates ownership per Criterion 2."
            elif "prokurist" in title_lower:
                criteria = ["Criterion 3: Signing Authority"]
                reasoning = f"'{job_title}' has signing authority per Criterion 3."
            elif "partner" in title_lower or "komplementär" in title_lower:
                criteria = ["Criterion 2: Significant Ownership", "Criterion 1: Executive Management Role"]
                reasoning = f"'{job_title}' indicates partnership with management authority."
            else:
                criteria = ["Criterion 1: Executive Management Role"]
                reasoning = f"'{job_title}' indicates a senior management position per Criterion 1."

            return ("CSM", reasoning, criteria)

    # Check for NON_CSM indicators
    for non_csm_title in NON_CSM_JOB_TITLES:
        if non_csm_title in title_lower:
            return (
                "NON_CSM",
                f"'{job_title}' is an administrative/non-executive position that does not meet CSM criteria.",
                [],
            )

    # Default to NON_CSM for unclear titles
    return (
        "NON_CSM",
        f"'{job_title}' does not clearly indicate executive authority, ownership, or signing authority. Defaulting to NON_CSM.",
        [],
    )


def classify_person(person: ReconciledPerson) -> ClassifiedPerson:
    """Classify a single reconciled person.

    Args:
        person: Reconciled person to classify.

    Returns:
        ClassifiedPerson with classification and reasoning.
    """
    # Use rule-based classification
    classification, reasoning, criteria_met = classify_by_job_title(person.job_title)

    # Also check original job title
    if person.job_title_original and classification == "NON_CSM":
        orig_class, orig_reason, orig_criteria = classify_by_job_title(
            person.job_title_original
        )
        if orig_class == "CSM":
            classification = orig_class
            reasoning = orig_reason
            criteria_met = orig_criteria

    # Build criteria not met
    all_criteria = [
        "Criterion 1: Executive Management Role",
        "Criterion 2: Significant Ownership",
        "Criterion 3: Signing Authority",
        "Criterion 4: Supervisory Control",
        "Criterion 5: Day-to-Day Control",
    ]
    criteria_not_met = [c for c in all_criteria if c not in criteria_met]

    # Build supporting evidence from source references
    supporting_evidence = []
    for ref in person.source_references[:3]:  # Limit to 3
        supporting_evidence.append(
            EvidenceReference(
                document=ref.filename,
                page=ref.page_number,
                relevant_text=ref.extracted_text_snippet or f"Found on page {ref.page_number}",
            )
        )

    return ClassifiedPerson(
        person_id=person.person_id,
        first_name=person.first_name,
        last_name=person.last_name,
        job_title=person.job_title,
        job_title_original=person.job_title_original,
        date_of_birth=person.date_of_birth,
        nationality=person.nationality,
        address=person.address,
        other_info=person.other_info,
        source_references=person.source_references,
        has_conflicts=person.has_conflicts,
        conflicts=person.conflicts,
        classification=classification,
        reasoning=reasoning,
        criteria_met=criteria_met,
        criteria_not_met=criteria_not_met,
        confidence=0.9 if criteria_met else 0.7,
        supporting_evidence=supporting_evidence,
    )


def classify_persons(
    reconciled_persons: list[ReconciledPerson],
) -> ClassifierOutput:
    """Classify all reconciled persons.

    Args:
        reconciled_persons: Persons to classify.

    Returns:
        ClassifierOutput with classified persons.
    """
    classified = [classify_person(p) for p in reconciled_persons]

    csm_count = sum(1 for p in classified if p.classification == "CSM")
    non_csm_count = len(classified) - csm_count

    logger.info(
        f"Classified {len(classified)} persons: {csm_count} CSM, {non_csm_count} NON_CSM"
    )

    return ClassifierOutput(classified_persons=classified)


def classifier_agent(state: WorkflowState) -> WorkflowState:
    """Classifier agent function for LangGraph workflow.

    This function:
    1. Gets reconciled persons from state
    2. Classifies each person as CSM or NON_CSM
    3. Updates state with classified persons

    Args:
        state: Current workflow state.

    Returns:
        Updated workflow state with classified persons.
    """
    workflow_id = state.get("workflow_id", "unknown")
    logger.info(f"[{workflow_id}] Classifier agent starting")

    reconciled_persons = state.get("reconciled_persons", [])
    if not reconciled_persons:
        logger.warning(f"[{workflow_id}] No reconciled persons to classify")
        return update_classification_result(state, [])

    # Get retry feedback
    retry_feedback = get_feedback(state, "classification")
    if retry_feedback:
        logger.info(f"[{workflow_id}] Retry feedback: {retry_feedback}")

    # Classify persons
    try:
        output = classify_persons(reconciled_persons)
        logger.info(
            f"[{workflow_id}] Classified {len(output.classified_persons)} persons"
        )
        return update_classification_result(state, output.classified_persons)

    except Exception as e:
        logger.error(f"[{workflow_id}] Classification failed: {e}", exc_info=True)
        return update_classification_result(state, [])
