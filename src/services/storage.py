"""SQLAlchemy table schemas and storage service for KYC workflow.

This module defines:
- SQLAlchemy table schemas for all entities
- CRUD operations for workflow data
- Audit log immutability enforcement

Data Retention Policy (FR-029):
- All workflow data retained for 7 years from completion
- Audit logs are immutable (no UPDATE or DELETE)
"""

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    event,
)
from sqlalchemy.orm import Session, relationship

from src.models.enums import (
    Classification,
    CriticDecision,
    DocumentProcessingStatus,
    FileType,
    WorkflowStatus,
)

from .database import Base

# Retention period: 7 years
RETENTION_YEARS = 7


class WorkflowRunDB(Base):
    """SQLAlchemy model for workflow runs."""

    __tablename__ = "workflow_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    status = Column(
        Enum(WorkflowStatus),
        nullable=False,
        default=WorkflowStatus.PENDING,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    failure_reason = Column(Text, nullable=True)
    output_json_path = Column(String(500), nullable=True)
    retention_until = Column(DateTime, nullable=True)

    # Relationships
    documents = relationship(
        "UploadedDocumentDB", back_populates="workflow_run", cascade="all, delete-orphan"
    )
    agent_executions = relationship(
        "AgentExecutionDB", back_populates="workflow_run", cascade="all, delete-orphan"
    )
    persons = relationship(
        "PersonDB", back_populates="workflow_run", cascade="all, delete-orphan"
    )
    audit_logs = relationship(
        "AuditLogDB", back_populates="workflow_run", cascade="all, delete-orphan"
    )


class UploadedDocumentDB(Base):
    """SQLAlchemy model for uploaded documents."""

    __tablename__ = "uploaded_documents"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_run_id = Column(
        String(36), ForeignKey("workflow_runs.id"), nullable=False
    )
    filename = Column(String(255), nullable=False)
    file_type = Column(Enum(FileType), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size_bytes = Column(Integer, nullable=False)
    page_count = Column(Integer, nullable=True)
    processing_status = Column(
        Enum(DocumentProcessingStatus),
        nullable=False,
        default=DocumentProcessingStatus.PENDING,
    )
    error_message = Column(Text, nullable=True)

    # Relationships
    workflow_run = relationship("WorkflowRunDB", back_populates="documents")
    source_references = relationship(
        "SourceReferenceDB", back_populates="document", cascade="all, delete-orphan"
    )


class AgentExecutionDB(Base):
    """SQLAlchemy model for agent executions."""

    __tablename__ = "agent_executions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_run_id = Column(
        String(36), ForeignKey("workflow_runs.id"), nullable=False
    )
    agent_name = Column(String(50), nullable=False)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    input_payload = Column(JSON, nullable=False)
    output_payload = Column(JSON, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="running")

    # Relationships
    workflow_run = relationship("WorkflowRunDB", back_populates="agent_executions")
    critic_feedback = relationship(
        "CriticFeedbackDB", back_populates="agent_execution", uselist=False
    )


class CriticFeedbackDB(Base):
    """SQLAlchemy model for critic feedback."""

    __tablename__ = "critic_feedbacks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_execution_id = Column(
        String(36), ForeignKey("agent_executions.id"), nullable=False
    )
    critic_agent_name = Column(String(50), nullable=False)
    decision = Column(Enum(CriticDecision), nullable=False)
    issues_found = Column(JSON, nullable=False, default=list)
    suggested_corrections = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    agent_execution = relationship("AgentExecutionDB", back_populates="critic_feedback")


class PersonDB(Base):
    """SQLAlchemy model for extracted persons."""

    __tablename__ = "persons"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_run_id = Column(
        String(36), ForeignKey("workflow_runs.id"), nullable=False
    )
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    first_name_normalized = Column(String(100), nullable=False)
    last_name_normalized = Column(String(100), nullable=False)
    job_title = Column(String(200), nullable=True)
    job_title_original = Column(String(200), nullable=True)
    date_of_birth = Column(DateTime, nullable=True)
    nationality = Column(String(100), nullable=True)
    address = Column(Text, nullable=True)
    other_info = Column(JSON, nullable=True, default=dict)
    is_duplicate = Column(Boolean, nullable=False, default=False)
    merged_into_id = Column(String(36), ForeignKey("persons.id"), nullable=True)
    has_conflicts = Column(Boolean, nullable=False, default=False)
    conflicts = Column(JSON, nullable=True)

    # Relationships
    workflow_run = relationship("WorkflowRunDB", back_populates="persons")
    source_references = relationship(
        "SourceReferenceDB", back_populates="person", cascade="all, delete-orphan"
    )
    classification_result = relationship(
        "ClassificationResultDB", back_populates="person", uselist=False
    )


class SourceReferenceDB(Base):
    """SQLAlchemy model for source references."""

    __tablename__ = "source_references"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    person_id = Column(String(36), ForeignKey("persons.id"), nullable=False)
    document_id = Column(
        String(36), ForeignKey("uploaded_documents.id"), nullable=False
    )
    page_number = Column(Integer, nullable=False)
    field_name = Column(String(50), nullable=True)
    extraction_confidence = Column(Float, nullable=True)
    extracted_text_snippet = Column(Text, nullable=True)

    # Relationships
    person = relationship("PersonDB", back_populates="source_references")
    document = relationship("UploadedDocumentDB", back_populates="source_references")


class ClassificationResultDB(Base):
    """SQLAlchemy model for classification results."""

    __tablename__ = "classification_results"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    person_id = Column(String(36), ForeignKey("persons.id"), nullable=False, unique=True)
    classification = Column(Enum(Classification), nullable=False)
    reasoning = Column(Text, nullable=False)
    criteria_met = Column(JSON, nullable=True)
    criteria_not_met = Column(JSON, nullable=True)
    confidence_score = Column(Float, nullable=True)
    classified_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    supporting_evidence = Column(JSON, nullable=False, default=list)

    # Relationships
    person = relationship("PersonDB", back_populates="classification_result")


class AuditLogDB(Base):
    """SQLAlchemy model for immutable audit logs.

    This table enforces immutability - no UPDATE or DELETE operations permitted.
    """

    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_run_id = Column(
        String(36), ForeignKey("workflow_runs.id"), nullable=False
    )
    event_type = Column(String(50), nullable=False)
    event_timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    actor = Column(String(100), nullable=False)
    action = Column(String(200), nullable=False)
    details = Column(JSON, nullable=False)
    checksum = Column(String(64), nullable=False)

    # Relationships
    workflow_run = relationship("WorkflowRunDB", back_populates="audit_logs")


def compute_audit_checksum(
    event_type: str,
    event_timestamp: datetime,
    actor: str,
    action: str,
    details: dict[str, Any],
) -> str:
    """Compute SHA-256 checksum for audit log integrity verification."""
    details_json = json.dumps(details, sort_keys=True)
    payload = (
        f"{event_type}{event_timestamp.isoformat()}{actor}{action}{details_json}"
    )
    return hashlib.sha256(payload.encode()).hexdigest()


# Event listeners to enforce audit log immutability
@event.listens_for(AuditLogDB, "before_update")
def prevent_audit_update(mapper, connection, target):
    """Prevent updates to audit logs."""
    raise ValueError("Audit logs are immutable and cannot be updated")


@event.listens_for(AuditLogDB, "before_delete")
def prevent_audit_delete(mapper, connection, target):
    """Prevent deletion of audit logs."""
    raise ValueError("Audit logs are immutable and cannot be deleted")


# Storage service functions
def create_workflow_run(db: Session) -> WorkflowRunDB:
    """Create a new workflow run."""
    workflow = WorkflowRunDB()
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow


def get_workflow_run(db: Session, workflow_id: str) -> WorkflowRunDB | None:
    """Get a workflow run by ID."""
    return db.query(WorkflowRunDB).filter(WorkflowRunDB.id == workflow_id).first()


def update_workflow_status(
    db: Session,
    workflow_id: str,
    status: WorkflowStatus,
    failure_reason: str | None = None,
) -> WorkflowRunDB | None:
    """Update workflow status."""
    workflow = get_workflow_run(db, workflow_id)
    if workflow:
        workflow.status = status
        if status == WorkflowStatus.IN_PROGRESS and workflow.started_at is None:
            workflow.started_at = datetime.utcnow()
        if status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED):
            workflow.completed_at = datetime.utcnow()
            if workflow.started_at:
                workflow.duration_seconds = (
                    workflow.completed_at - workflow.started_at
                ).total_seconds()
            # Set retention date
            workflow.retention_until = datetime.utcnow() + timedelta(
                days=RETENTION_YEARS * 365
            )
        if failure_reason:
            workflow.failure_reason = failure_reason
        db.commit()
        db.refresh(workflow)
    return workflow


def create_uploaded_document(
    db: Session,
    workflow_run_id: str,
    filename: str,
    file_type: FileType,
    file_path: str,
    file_size_bytes: int,
    page_count: int | None = None,
) -> UploadedDocumentDB:
    """Create an uploaded document record."""
    document = UploadedDocumentDB(
        workflow_run_id=workflow_run_id,
        filename=filename,
        file_type=file_type,
        file_path=file_path,
        file_size_bytes=file_size_bytes,
        page_count=page_count,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def create_agent_execution(
    db: Session,
    workflow_run_id: str,
    agent_name: str,
    input_payload: dict[str, Any],
    retry_count: int = 0,
) -> AgentExecutionDB:
    """Create an agent execution record."""
    execution = AgentExecutionDB(
        workflow_run_id=workflow_run_id,
        agent_name=agent_name,
        input_payload=input_payload,
        retry_count=retry_count,
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)
    return execution


def complete_agent_execution(
    db: Session,
    execution_id: str,
    output_payload: dict[str, Any],
    status: str = "completed",
) -> AgentExecutionDB | None:
    """Mark an agent execution as completed."""
    execution = db.query(AgentExecutionDB).filter(AgentExecutionDB.id == execution_id).first()
    if execution:
        execution.ended_at = datetime.utcnow()
        execution.duration_ms = int(
            (execution.ended_at - execution.started_at).total_seconds() * 1000
        )
        execution.output_payload = output_payload
        execution.status = status
        db.commit()
        db.refresh(execution)
    return execution


def create_critic_feedback(
    db: Session,
    agent_execution_id: str,
    critic_agent_name: str,
    decision: CriticDecision,
    issues_found: list[dict[str, Any]],
    suggested_corrections: str | None = None,
) -> CriticFeedbackDB:
    """Create a critic feedback record."""
    feedback = CriticFeedbackDB(
        agent_execution_id=agent_execution_id,
        critic_agent_name=critic_agent_name,
        decision=decision,
        issues_found=issues_found,
        suggested_corrections=suggested_corrections,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback


def create_audit_log(
    db: Session,
    workflow_run_id: str,
    event_type: str,
    actor: str,
    action: str,
    details: dict[str, Any],
) -> AuditLogDB:
    """Create an immutable audit log entry."""
    event_timestamp = datetime.utcnow()
    checksum = compute_audit_checksum(
        event_type, event_timestamp, actor, action, details
    )
    audit_log = AuditLogDB(
        workflow_run_id=workflow_run_id,
        event_type=event_type,
        event_timestamp=event_timestamp,
        actor=actor,
        action=action,
        details=details,
        checksum=checksum,
    )
    db.add(audit_log)
    db.commit()
    db.refresh(audit_log)
    return audit_log


def save_workflow_output(
    db: Session,
    workflow_id: str,
    output_json_path: str,
) -> WorkflowRunDB | None:
    """Save the path to the workflow output JSON."""
    workflow = get_workflow_run(db, workflow_id)
    if workflow:
        workflow.output_json_path = output_json_path
        db.commit()
        db.refresh(workflow)
    return workflow


# --- Output Persistence Functions ---

from pathlib import Path


def save_output_json(
    workflow_id: str,
    output_data: dict[str, Any],
    output_dir: str | Path = "outputs",
) -> Path:
    """Save workflow output JSON to filesystem.

    Args:
        workflow_id: Unique workflow identifier.
        output_data: Workflow output data to save.
        output_dir: Directory to save output files.

    Returns:
        Path to the saved JSON file.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    filename = f"workflow_{workflow_id}_output.json"
    file_path = output_path / filename

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False, default=str)

    return file_path


def persist_workflow_output(
    workflow_id: str,
    document_manifest: list[dict[str, Any]],
    csm_list: list[dict[str, Any]],
    non_csm_list: list[dict[str, Any]],
    output_dir: str | Path = "outputs",
    db: Session | None = None,
) -> Path:
    """Persist complete workflow output to filesystem and optionally update DB.

    This function:
    1. Creates the output JSON structure
    2. Saves it to the filesystem
    3. Optionally updates the WorkflowRun with the output path

    Args:
        workflow_id: Unique workflow identifier.
        document_manifest: List of document manifest entries.
        csm_list: List of CSM classified persons.
        non_csm_list: List of NON_CSM classified persons.
        output_dir: Directory to save output files.
        db: Optional database session for updating WorkflowRun.

    Returns:
        Path to the saved JSON file.
    """
    output_data = {
        "workflow_id": workflow_id,
        "generated_at": datetime.utcnow().isoformat(),
        "document_manifest": document_manifest,
        "csm_list": csm_list,
        "non_csm_list": non_csm_list,
        "summary": {
            "total_documents": len(document_manifest),
            "total_csm": len(csm_list),
            "total_non_csm": len(non_csm_list),
        },
    }

    file_path = save_output_json(workflow_id, output_data, output_dir)

    if db is not None:
        save_workflow_output(db, workflow_id, str(file_path))

    return file_path


def load_workflow_output(file_path: str | Path) -> dict[str, Any]:
    """Load workflow output JSON from filesystem.

    Args:
        file_path: Path to the output JSON file.

    Returns:
        Loaded output data.

    Raises:
        FileNotFoundError: If file doesn't exist.
        json.JSONDecodeError: If file is not valid JSON.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)
