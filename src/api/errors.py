"""Error codes and response models for API.

Error codes per contracts/api.md specification.
"""

from typing import Any

from pydantic import BaseModel


class ErrorCode:
    """Error codes per contracts/api.md."""

    INVALID_FILE_TYPE = "INVALID_FILE_TYPE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    WORKFLOW_NOT_FOUND = "WORKFLOW_NOT_FOUND"
    WORKFLOW_ALREADY_STARTED = "WORKFLOW_ALREADY_STARTED"
    WORKFLOW_NOT_COMPLETED = "WORKFLOW_NOT_COMPLETED"
    LLM_SERVICE_UNAVAILABLE = "LLM_SERVICE_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"


class ErrorDetail(BaseModel):
    """Error detail structure per contracts/api.md."""

    code: str
    message: str
    details: Any = None


class ErrorResponse(BaseModel):
    """Standard error response format."""

    error: ErrorDetail
