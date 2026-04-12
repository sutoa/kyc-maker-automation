"""Person-related data models for KYC Document Processing.

This module defines Pydantic models for:
- SourceReference: Links extracted data to source documents
- ExtractedPerson: Raw person data from extraction phase
- ReconciledPerson: Deduplicated person with conflicts flagged
- ClassifiedPerson: Final classified person with CSM reasoning
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class SourceReference(BaseModel):
    """Links extracted data to its origin in source documents."""

    document_id: str = Field(..., description="UUID of the source document")
    filename: str = Field(..., description="Original filename of the document")
    page_number: int = Field(..., ge=1, description="Page where data was found")
    field_name: str | None = Field(
        None, description="Specific field this reference supports (null = whole record)"
    )
    extracted_text_snippet: str | None = Field(
        None, description="Relevant text from document"
    )
    confidence: float | None = Field(
        None, ge=0.0, le=1.0, description="LLM confidence score"
    )


class ExtractedPerson(BaseModel):
    """A person extracted from source documents.

    Fields match the extractor.md JSON example exactly so LLM output
    maps directly to Pydantic validation with no post-processing.
    """

    first_name: str = Field(..., min_length=1, description="Person's given name")
    last_name: str = Field(..., min_length=1, description="Person's family name")
    job_title: str | None = Field(None, description="Job title in English")
    job_title_original: str | None = Field(
        None, description="Original language job title (e.g. Geschäftsführer)"
    )
    doc_name: str = Field(..., description="Source document filename")
    page_number: int = Field(..., ge=1, description="Page where person was found")


class FieldConflict(BaseModel):
    """Represents conflicting values for a field from different sources."""

    field_name: str = Field(..., description="Name of the conflicting field")
    values: list["ConflictValue"] = Field(
        ..., min_length=2, description="Conflicting values"
    )


class ConflictValue(BaseModel):
    """A single conflicting value with its source."""

    value: str = Field(..., description="The conflicting value")
    source_document: str = Field(..., description="Document filename")
    source_page: int = Field(..., ge=1, description="Page number")


class DuplicateGroup(BaseModel):
    """Audit trail for merged duplicate records."""

    primary_person_id: str = Field(..., description="ID of the primary merged record")
    merged_extraction_ids: list[str] = Field(
        ..., description="IDs of extraction records that were merged"
    )
    match_score: float = Field(
        ..., ge=0.0, le=1.0, description="Fuzzy match confidence score"
    )


class ReconciledPerson(BaseModel):
    """A person after deduplication with conflicts flagged."""

    person_id: str = Field(..., description="Stable ID after deduplication")
    first_name: str = Field(..., min_length=1, description="First name")
    last_name: str = Field(..., min_length=1, description="Last name")
    first_name_normalized: str = Field(
        ..., description="Lowercase, ASCII-folded first name for matching"
    )
    last_name_normalized: str = Field(
        ..., description="Lowercase, ASCII-folded last name for matching"
    )
    job_title: str | None = Field(None, description="Job title in English")
    job_title_original: str | None = Field(
        None, description="Original language job title"
    )
    date_of_birth: date | None = Field(None, description="Date of birth")
    nationality: str | None = Field(None, description="Nationality")
    address: str | None = Field(None, description="Address")
    other_info: dict = Field(default_factory=dict, description="Additional fields")
    source_references: list[SourceReference] = Field(
        ..., description="Consolidated sources from all occurrences"
    )
    has_conflicts: bool = Field(
        False, description="True if conflicting data detected"
    )
    conflicts: list[FieldConflict] = Field(
        default_factory=list, description="Details of conflicting fields"
    )


class EvidenceReference(BaseModel):
    """Reference to evidence supporting a classification decision."""

    document: str = Field(..., description="Document filename")
    page: int = Field(..., ge=1, description="Page number")
    relevant_text: str = Field(..., description="Text supporting the classification")


class ClassifiedPerson(BaseModel):
    """A person with CSM/NON_CSM classification and reasoning."""

    person_id: str = Field(..., description="Stable person ID")
    first_name: str = Field(..., min_length=1, description="First name")
    last_name: str = Field(..., min_length=1, description="Last name")
    job_title: str | None = Field(None, description="Job title in English")
    job_title_original: str | None = Field(
        None, description="Original language job title"
    )
    date_of_birth: date | None = Field(None, description="Date of birth")
    nationality: str | None = Field(None, description="Nationality")
    address: str | None = Field(None, description="Address")
    other_info: dict = Field(default_factory=dict, description="Additional fields")
    source_references: list[SourceReference] = Field(
        ..., description="Source references"
    )
    has_conflicts: bool = Field(False, description="True if conflicts detected")
    conflicts: list[FieldConflict] = Field(
        default_factory=list, description="Conflict details"
    )

    # Classification result
    classification: Literal["CSM", "NON_CSM"] = Field(
        ..., description="CSM or NON_CSM classification"
    )
    reasoning: str = Field(
        ..., min_length=1, description="Explanation citing CSM criteria"
    )
    criteria_met: list[str] = Field(
        default_factory=list, description="CSM criteria that were satisfied"
    )
    criteria_not_met: list[str] = Field(
        default_factory=list, description="CSM criteria not satisfied"
    )
    confidence: float | None = Field(
        None, ge=0.0, le=1.0, description="Classification confidence"
    )
    supporting_evidence: list[EvidenceReference] = Field(
        default_factory=list, description="Evidence supporting the classification"
    )
