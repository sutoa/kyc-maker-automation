"""Workflow-related data models for KYC Document Processing.

This module defines Pydantic models for:
- WorkflowRun: A single execution of the processing pipeline
- AgentExecution: Records of individual agent invocations
- CriticFeedback: Feedback from critic agents
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .enums import CriticDecision, WorkflowStatus


class WorkflowRun(BaseModel):
    """Represents a single execution of the KYC document processing pipeline."""

    id: str = Field(..., description="Unique workflow identifier (UUID)")
    status: WorkflowStatus = Field(
        default=WorkflowStatus.PENDING, description="Current workflow status"
    )
    created_at: datetime = Field(..., description="Workflow trigger timestamp")
    started_at: datetime | None = Field(
        None, description="When processing began"
    )
    completed_at: datetime | None = Field(
        None, description="Workflow completion timestamp"
    )
    duration_seconds: float | None = Field(
        None, description="Total execution time"
    )
    failure_reason: str | None = Field(
        None, description="Error message if status=failed"
    )
    output_json_path: str | None = Field(
        None, description="Path to downloadable JSON output"
    )


class AgentExecution(BaseModel):
    """Records a single invocation of an agent within a workflow."""

    id: str = Field(..., description="Unique execution identifier (UUID)")
    workflow_run_id: str = Field(..., description="Parent workflow ID")
    agent_name: str = Field(
        ..., description="Agent identifier (e.g., 'extractor', 'critic_1')"
    )
    started_at: datetime = Field(..., description="Execution start time")
    ended_at: datetime | None = Field(None, description="Execution end time")
    duration_ms: int | None = Field(
        None, description="Execution duration in milliseconds"
    )
    input_payload: dict[str, Any] = Field(
        ..., description="Input data to agent"
    )
    output_payload: dict[str, Any] | None = Field(
        None, description="Output data from agent"
    )
    retry_count: int = Field(
        default=0, ge=0, le=4, description="Current retry attempt (0-4)"
    )
    status: Literal["running", "completed", "failed"] = Field(
        default="running", description="Execution status"
    )


class ExtractionIssue(BaseModel):
    """Issue identified during extraction validation."""

    extraction_id: str = Field(..., description="Which person record has the issue")
    issue_type: Literal[
        "missing_first_name",
        "missing_last_name",
        "missing_source",
        "invalid_page_number",
        "low_confidence",
        "other",
    ] = Field(..., description="Type of issue")
    description: str = Field(..., description="Issue description")
    severity: Literal["error", "warning"] = Field(..., description="Issue severity")


class ReconciliationIssue(BaseModel):
    """Issue identified during reconciliation validation."""

    person_id: str | None = Field(
        None, description="Person ID (null for global issues)"
    )
    issue_type: Literal[
        "missed_duplicate",
        "incorrect_merge",
        "undetected_conflict",
        "lost_source_reference",
        "other",
    ] = Field(..., description="Type of issue")
    description: str = Field(..., description="Issue description")
    evidence: str | None = Field(None, description="Supporting evidence")


class ClassificationIssue(BaseModel):
    """Issue identified during classification validation."""

    person_id: str = Field(..., description="Person ID with the issue")
    issue_type: Literal[
        "missing_reasoning",
        "weak_reasoning",
        "incorrect_criteria_citation",
        "missing_evidence",
        "inconsistent_classification",
        "other",
    ] = Field(..., description="Type of issue")
    description: str = Field(..., description="Issue description")
    suggested_correction: str | None = Field(
        None, description="Suggested correction"
    )


class CriticFeedback(BaseModel):
    """Feedback from a critic agent when an output fails review."""

    id: str = Field(..., description="Unique feedback identifier (UUID)")
    agent_execution_id: str = Field(
        ..., description="The execution that produced failing output"
    )
    critic_agent_name: str = Field(
        ..., description="Name of critic agent (critic_1/2/3)"
    )
    decision: CriticDecision = Field(..., description="Critic decision")
    issues_found: list[dict[str, Any]] = Field(
        default_factory=list, description="List of specific issues identified"
    )
    suggested_corrections: str | None = Field(
        None, description="Guidance for retry"
    )
    created_at: datetime = Field(..., description="Feedback timestamp")
