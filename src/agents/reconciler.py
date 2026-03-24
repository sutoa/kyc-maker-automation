"""Reconciler agent for KYC document processing.

This agent identifies and merges duplicate person records using
fuzzy name matching and consolidates source references.
"""

import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from src.core.state import (
    WorkflowState,
    get_feedback,
    update_reconciliation_result,
)
from src.models.person import (
    DuplicateGroup,
    ExtractedPerson,
    FieldConflict,
    ConflictValue,
    ReconciledPerson,
    SourceReference,
)
from src.services.matching import (
    find_duplicates,
    normalize_name,
)

logger = logging.getLogger(__name__)


class ReconcilerInput(BaseModel):
    """Input contract for the reconciler agent."""

    extracted_persons: list[ExtractedPerson] = Field(
        ..., description="Extracted persons to reconcile"
    )
    retry_feedback: str | None = Field(
        None, description="Feedback from critic if retrying"
    )


class ReconcilerOutput(BaseModel):
    """Output contract for the reconciler agent."""

    reconciled_persons: list[ReconciledPerson] = Field(
        ..., description="Deduplicated persons"
    )
    duplicate_groups: list[DuplicateGroup] = Field(
        default_factory=list, description="Audit trail of merged records"
    )


def merge_persons(
    persons: list[ExtractedPerson],
    match_score: float = 1.0,
) -> ReconciledPerson:
    """Merge multiple extracted persons into one reconciled person.

    Args:
        persons: List of persons to merge (at least 1).
        match_score: Fuzzy match score for the group.

    Returns:
        Single ReconciledPerson with consolidated data.
    """
    if not persons:
        raise ValueError("Cannot merge empty person list")

    # Use first person as primary
    primary = persons[0]

    # Generate stable person_id
    person_id = f"person_{uuid4().hex[:8]}"

    # Consolidate source references
    all_sources: list[SourceReference] = []
    for person in persons:
        all_sources.extend(person.source_references)

    # Detect conflicts
    conflicts: list[FieldConflict] = []

    # Check for job_title conflicts
    job_titles = set()
    job_title_sources: list[ConflictValue] = []
    for person in persons:
        if person.job_title:
            if person.job_title not in job_titles:
                job_titles.add(person.job_title)
                if person.source_references:
                    ref = person.source_references[0]
                    job_title_sources.append(
                        ConflictValue(
                            value=person.job_title,
                            source_document=ref.filename,
                            source_page=ref.page_number,
                        )
                    )

    if len(job_titles) > 1:
        conflicts.append(
            FieldConflict(field_name="job_title", values=job_title_sources)
        )

    # Check for date_of_birth conflicts
    dobs = set()
    dob_sources: list[ConflictValue] = []
    for person in persons:
        if person.date_of_birth:
            dob_str = str(person.date_of_birth)
            if dob_str not in dobs:
                dobs.add(dob_str)
                if person.source_references:
                    ref = person.source_references[0]
                    dob_sources.append(
                        ConflictValue(
                            value=dob_str,
                            source_document=ref.filename,
                            source_page=ref.page_number,
                        )
                    )

    if len(dobs) > 1:
        conflicts.append(
            FieldConflict(field_name="date_of_birth", values=dob_sources)
        )

    # Merge other_info
    merged_other_info: dict[str, Any] = {}
    for person in persons:
        merged_other_info.update(person.other_info)

    # Create reconciled person
    return ReconciledPerson(
        person_id=person_id,
        first_name=primary.first_name,
        last_name=primary.last_name,
        first_name_normalized=normalize_name(primary.first_name),
        last_name_normalized=normalize_name(primary.last_name),
        job_title=primary.job_title,
        job_title_original=primary.job_title_original,
        date_of_birth=primary.date_of_birth,
        nationality=primary.nationality,
        address=primary.address,
        other_info=merged_other_info,
        source_references=all_sources,
        has_conflicts=len(conflicts) > 0,
        conflicts=conflicts,
    )


def reconcile_persons(
    extracted_persons: list[ExtractedPerson],
    threshold: float = 0.85,
) -> ReconcilerOutput:
    """Reconcile extracted persons by identifying and merging duplicates.

    Args:
        extracted_persons: Persons to reconcile.
        threshold: Fuzzy matching threshold (default 0.85).

    Returns:
        ReconcilerOutput with reconciled persons and duplicate groups.
    """
    if not extracted_persons:
        return ReconcilerOutput(reconciled_persons=[], duplicate_groups=[])

    # Build person tuples for duplicate detection
    person_tuples = [
        (p.extraction_id, p.first_name, p.last_name) for p in extracted_persons
    ]

    # Find duplicate groups (indices)
    duplicate_indices = find_duplicates(person_tuples, threshold=threshold)

    # Track which persons have been processed
    processed_indices: set[int] = set()
    reconciled_persons: list[ReconciledPerson] = []
    duplicate_groups: list[DuplicateGroup] = []

    # Process duplicate groups first
    for group_indices in duplicate_indices:
        if not group_indices:
            continue

        # Get persons in this group
        group_persons = [extracted_persons[i] for i in group_indices]
        extraction_ids = [p.extraction_id for p in group_persons]

        # Merge the group
        merged = merge_persons(group_persons, match_score=0.95)
        reconciled_persons.append(merged)

        # Record the duplicate group
        duplicate_groups.append(
            DuplicateGroup(
                primary_person_id=merged.person_id,
                merged_extraction_ids=extraction_ids,
                match_score=0.95,
            )
        )

        # Mark as processed
        processed_indices.update(group_indices)

    # Process non-duplicate persons
    for i, person in enumerate(extracted_persons):
        if i in processed_indices:
            continue

        # Single person - no merge needed
        reconciled = merge_persons([person])
        reconciled_persons.append(reconciled)

    logger.info(
        f"Reconciled {len(extracted_persons)} extracted persons into "
        f"{len(reconciled_persons)} unique persons, "
        f"{len(duplicate_groups)} duplicate group(s) found"
    )

    return ReconcilerOutput(
        reconciled_persons=reconciled_persons,
        duplicate_groups=duplicate_groups,
    )


def reconciler_agent(state: WorkflowState) -> WorkflowState:
    """Reconciler agent function for LangGraph workflow.

    This function:
    1. Gets extracted persons from state
    2. Identifies and merges duplicates
    3. Updates state with reconciled persons

    Args:
        state: Current workflow state.

    Returns:
        Updated workflow state with reconciled persons.
    """
    workflow_id = state.get("workflow_id", "unknown")
    logger.info(f"[{workflow_id}] Reconciler agent starting")

    extracted_persons = state.get("extracted_persons", [])
    if not extracted_persons:
        logger.warning(f"[{workflow_id}] No extracted persons to reconcile")
        return update_reconciliation_result(state, [], [])

    # Get retry feedback (not currently used but available for LLM-based reconciliation)
    retry_feedback = get_feedback(state, "reconciliation")
    if retry_feedback:
        logger.info(f"[{workflow_id}] Retry feedback: {retry_feedback}")

    # Reconcile persons
    try:
        output = reconcile_persons(extracted_persons)
        logger.info(
            f"[{workflow_id}] Reconciled {len(extracted_persons)} -> "
            f"{len(output.reconciled_persons)} persons"
        )
        return update_reconciliation_result(
            state,
            output.reconciled_persons,
            output.duplicate_groups,
        )

    except Exception as e:
        logger.error(f"[{workflow_id}] Reconciliation failed: {e}", exc_info=True)
        return update_reconciliation_result(state, [], [])
