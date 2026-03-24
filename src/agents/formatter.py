"""Formatter agent for KYC document processing.

This agent formats the final workflow output including:
- Document manifest with processing status
- CSM list (persons classified as CSM)
- Non-CSM list (persons classified as NON_CSM)
"""

import logging
from typing import Literal

from pydantic import BaseModel, Field

from src.core.state import WorkflowState, update_final_output
from src.models.output import DocumentManifestEntry
from src.models.person import ClassifiedPerson
from src.services.document import DocumentInput

logger = logging.getLogger(__name__)


class FormatterInput(BaseModel):
    """Input contract for the formatter agent."""

    workflow_id: str = Field(..., description="Workflow identifier")
    documents: list[DocumentInput] = Field(
        ..., description="Processed documents"
    )
    classified_persons: list[ClassifiedPerson] = Field(
        ..., description="Classified persons"
    )


class FormatterOutput(BaseModel):
    """Output contract for the formatter agent."""

    document_manifest: list[DocumentManifestEntry] = Field(
        ..., description="Document metadata"
    )
    csm_list: list[ClassifiedPerson] = Field(
        ..., description="Persons classified as CSM"
    )
    non_csm_list: list[ClassifiedPerson] = Field(
        ..., description="Persons classified as NON_CSM"
    )


def determine_processing_status(
    document: DocumentInput,
    classified_persons: list[ClassifiedPerson],
) -> Literal["processed", "failed", "partial"]:
    """Determine the processing status for a document.

    Args:
        document: The document to check.
        classified_persons: All classified persons.

    Returns:
        Processing status.
    """
    # Check if any persons reference this document
    doc_referenced = False
    for person in classified_persons:
        for ref in person.source_references:
            if ref.document_id == document.document_id:
                doc_referenced = True
                break
        if doc_referenced:
            break

    if doc_referenced:
        return "processed"

    # If document has content but no persons, it's still processed
    if document.content and document.content.strip():
        return "processed"

    # If document is empty, it failed
    if not document.content or not document.content.strip():
        return "failed"

    return "partial"


def create_document_manifest(
    documents: list[DocumentInput],
    classified_persons: list[ClassifiedPerson],
) -> list[DocumentManifestEntry]:
    """Create the document manifest.

    Args:
        documents: Processed documents.
        classified_persons: All classified persons.

    Returns:
        List of document manifest entries.
    """
    manifest = []
    for doc in documents:
        status = determine_processing_status(doc, classified_persons)
        entry = DocumentManifestEntry(
            filename=doc.filename,
            file_type=doc.file_type,
            page_count=doc.page_count,
            processing_status=status,
        )
        manifest.append(entry)

    return manifest


def split_by_classification(
    classified_persons: list[ClassifiedPerson],
) -> tuple[list[ClassifiedPerson], list[ClassifiedPerson]]:
    """Split classified persons into CSM and NON_CSM lists.

    Args:
        classified_persons: All classified persons.

    Returns:
        Tuple of (csm_list, non_csm_list).
    """
    csm_list = []
    non_csm_list = []

    for person in classified_persons:
        if person.classification == "CSM":
            csm_list.append(person)
        else:
            non_csm_list.append(person)

    return csm_list, non_csm_list


def format_output(
    documents: list[DocumentInput],
    classified_persons: list[ClassifiedPerson],
) -> FormatterOutput:
    """Format the final workflow output.

    Args:
        documents: Processed documents.
        classified_persons: Classified persons.

    Returns:
        FormatterOutput with manifest and person lists.
    """
    # Create document manifest
    manifest = create_document_manifest(documents, classified_persons)

    # Split persons by classification
    csm_list, non_csm_list = split_by_classification(classified_persons)

    # Validate mutual exclusivity
    csm_ids = {p.person_id for p in csm_list}
    non_csm_ids = {p.person_id for p in non_csm_list}
    overlap = csm_ids & non_csm_ids

    if overlap:
        logger.warning(f"Persons in both CSM and NON_CSM lists: {overlap}")

    logger.info(
        f"Formatted output: {len(manifest)} documents, "
        f"{len(csm_list)} CSM, {len(non_csm_list)} NON_CSM"
    )

    return FormatterOutput(
        document_manifest=manifest,
        csm_list=csm_list,
        non_csm_list=non_csm_list,
    )


def formatter_agent(state: WorkflowState) -> WorkflowState:
    """Formatter agent function for LangGraph workflow.

    This function:
    1. Gets documents and classified persons from state
    2. Creates document manifest
    3. Splits persons into CSM and NON_CSM lists
    4. Updates state with final output

    Args:
        state: Current workflow state.

    Returns:
        Updated workflow state with formatted output and completed status.
    """
    workflow_id = state.get("workflow_id", "unknown")
    logger.info(f"[{workflow_id}] Formatter agent starting")

    documents = state.get("documents", [])
    classified_persons = state.get("classified_persons", [])

    try:
        output = format_output(documents, classified_persons)

        logger.info(
            f"[{workflow_id}] Formatted output: "
            f"{len(output.document_manifest)} docs, "
            f"{len(output.csm_list)} CSM, "
            f"{len(output.non_csm_list)} NON_CSM"
        )

        return update_final_output(
            state,
            output.document_manifest,
            output.csm_list,
            output.non_csm_list,
        )

    except Exception as e:
        logger.error(f"[{workflow_id}] Formatting failed: {e}", exc_info=True)
        # Return state with empty output
        return update_final_output(state, [], [], [])
