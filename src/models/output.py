"""Output-related data models for KYC Document Processing.

This module defines Pydantic models for:
- DocumentManifestEntry: Metadata for each processed document
- WorkflowOutput: Combined output with manifest and person lists
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .person import ClassifiedPerson


class DocumentManifestEntry(BaseModel):
    """Metadata for a document in the workflow output manifest."""

    filename: str = Field(..., description="Original filename")
    file_type: Literal["PDF", "TXT"] = Field(..., description="File type")
    page_count: int = Field(..., ge=0, description="Number of pages")
    processing_status: Literal["processed", "failed", "partial"] = Field(
        ..., description="Processing result"
    )


class WorkflowOutput(BaseModel):
    """Final output of a completed KYC workflow.

    Contains the document manifest and classified persons split
    into CSM and Non-CSM lists.
    """

    workflow_id: str = Field(..., description="Workflow identifier")
    completed_at: datetime = Field(..., description="Completion timestamp")
    document_manifest: list[DocumentManifestEntry] = Field(
        ..., description="List of all processed documents"
    )
    csm_list: list[ClassifiedPerson] = Field(
        ..., description="Persons classified as CSM"
    )
    non_csm_list: list[ClassifiedPerson] = Field(
        ..., description="Persons classified as NON_CSM"
    )


class WorkflowSummary(BaseModel):
    """Summary statistics for a workflow."""

    total_persons_extracted: int = Field(
        ..., ge=0, description="Total persons extracted"
    )
    csm_count: int = Field(..., ge=0, description="Number of CSM persons")
    non_csm_count: int = Field(..., ge=0, description="Number of NON_CSM persons")
    conflicts_detected: int = Field(
        ..., ge=0, description="Number of persons with conflicts"
    )


class WorkflowListItem(BaseModel):
    """Summary of a workflow for list endpoints."""

    workflow_id: str = Field(..., description="Workflow identifier")
    status: str = Field(..., description="Current status")
    created_at: datetime = Field(..., description="Creation timestamp")
    completed_at: datetime | None = Field(
        None, description="Completion timestamp"
    )
    duration_seconds: float | None = Field(
        None, description="Total execution time"
    )
    document_count: int = Field(..., ge=0, description="Number of documents")
    person_count: int = Field(
        ..., ge=0, description="Number of persons extracted"
    )
