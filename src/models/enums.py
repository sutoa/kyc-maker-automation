"""Enumerations for KYC Document Processing workflow.

This module defines all enum types used across the application for
workflow status, file types, critic decisions, and classifications.
"""

from enum import Enum


class WorkflowStatus(str, Enum):
    """Status of a workflow run."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class DocumentProcessingStatus(str, Enum):
    """Processing status for uploaded documents."""

    PENDING = "pending"
    PROCESSED = "processed"
    FAILED = "failed"
    PARTIAL = "partial"


class FileType(str, Enum):
    """Supported file types for document upload."""

    PDF = "PDF"
    TXT = "TXT"


class CriticDecision(str, Enum):
    """Decision outcome from critic agents.

    - PASS: Output meets quality standards, proceed to next agent
    - FAIL_RETRY: Output has issues, retry with feedback (if retries remaining)
    - FAIL_MAX: Maximum retries reached, workflow fails
    """

    PASS = "pass"
    FAIL_RETRY = "fail_retry"
    FAIL_MAX = "fail_max"


class Classification(str, Enum):
    """CSM classification result for a person."""

    CSM = "CSM"
    NON_CSM = "NON_CSM"
