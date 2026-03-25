"""Audit logging service for compliance and traceability.

This module provides:
- Immutable audit log creation with SHA-256 checksum
- Event types for all workflow actions
- Query functions for audit trail retrieval
- Integration with workflow callbacks

Data Retention Policy (FR-029):
- All audit logs are retained for 7 years from workflow completion
- Audit logs are immutable (no UPDATE or DELETE operations)
- Each log entry includes a SHA-256 checksum for integrity verification

Event Types:
- workflow_started: Workflow execution began
- workflow_completed: Workflow finished successfully
- workflow_failed: Workflow failed with error
- agent_started: Agent began processing
- agent_completed: Agent finished successfully
- agent_failed: Agent encountered an error
- critic_decision: Critic made a pass/fail decision
- retry_triggered: Agent retry was initiated
- document_uploaded: Document was uploaded
- document_processed: Document extraction completed
- person_extracted: Person record was extracted
- person_classified: Person was classified as CSM/NON_CSM
"""

import hashlib
import json
import logging
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from src.services.storage import AuditLogDB, compute_audit_checksum

logger = logging.getLogger(__name__)


# --- Audit Event Types ---


class AuditEventType(str, Enum):
    """Enumeration of audit event types."""

    # Workflow lifecycle
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"

    # Agent lifecycle
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"

    # Critic decisions
    CRITIC_DECISION = "critic_decision"

    # Retry events
    RETRY_TRIGGERED = "retry_triggered"

    # Document events
    DOCUMENT_UPLOADED = "document_uploaded"
    DOCUMENT_PROCESSED = "document_processed"

    # Person events
    PERSON_EXTRACTED = "person_extracted"
    PERSON_CLASSIFIED = "person_classified"


# --- Audit Service Class ---


class AuditService:
    """Service for creating and querying audit logs.

    This service provides methods for:
    - Creating immutable audit log entries
    - Logging agent actions with full context
    - Logging retry cycles with feedback
    - Querying audit trails for workflows

    All log entries include SHA-256 checksums for integrity verification.
    """

    def __init__(self, db: Session):
        """Initialize the audit service.

        Args:
            db: SQLAlchemy database session.
        """
        self.db = db

    def log(
        self,
        workflow_run_id: str,
        event_type: AuditEventType | str,
        actor: str,
        action: str,
        details: dict[str, Any] | None = None,
    ) -> AuditLogDB:
        """Create an immutable audit log entry.

        Args:
            workflow_run_id: ID of the associated workflow.
            event_type: Type of event being logged.
            actor: Name of agent or system component.
            action: Description of what happened.
            details: Additional context as JSON-serializable dict.

        Returns:
            The created AuditLogDB instance.
        """
        event_type_str = (
            event_type.value if isinstance(event_type, AuditEventType) else event_type
        )
        details = details or {}

        event_timestamp = datetime.utcnow()
        checksum = compute_audit_checksum(
            event_type_str, event_timestamp, actor, action, details
        )

        audit_log = AuditLogDB(
            workflow_run_id=workflow_run_id,
            event_type=event_type_str,
            event_timestamp=event_timestamp,
            actor=actor,
            action=action,
            details=details,
            checksum=checksum,
        )

        self.db.add(audit_log)
        self.db.commit()
        self.db.refresh(audit_log)

        logger.debug(
            f"[{workflow_run_id}] Audit log created: {event_type_str} - {action}"
        )

        return audit_log

    # --- Workflow Events ---

    def log_workflow_started(
        self,
        workflow_run_id: str,
        document_count: int,
    ) -> AuditLogDB:
        """Log workflow started event.

        Args:
            workflow_run_id: ID of the workflow.
            document_count: Number of documents to process.

        Returns:
            The created audit log entry.
        """
        return self.log(
            workflow_run_id=workflow_run_id,
            event_type=AuditEventType.WORKFLOW_STARTED,
            actor="system",
            action=f"Workflow started with {document_count} document(s)",
            details={"document_count": document_count},
        )

    def log_workflow_completed(
        self,
        workflow_run_id: str,
        duration_seconds: float,
        csm_count: int,
        non_csm_count: int,
    ) -> AuditLogDB:
        """Log workflow completed event.

        Args:
            workflow_run_id: ID of the workflow.
            duration_seconds: Total workflow duration.
            csm_count: Number of CSM classifications.
            non_csm_count: Number of NON_CSM classifications.

        Returns:
            The created audit log entry.
        """
        return self.log(
            workflow_run_id=workflow_run_id,
            event_type=AuditEventType.WORKFLOW_COMPLETED,
            actor="system",
            action=f"Workflow completed successfully in {duration_seconds:.1f}s",
            details={
                "duration_seconds": duration_seconds,
                "csm_count": csm_count,
                "non_csm_count": non_csm_count,
                "total_persons": csm_count + non_csm_count,
            },
        )

    def log_workflow_failed(
        self,
        workflow_run_id: str,
        error: str,
        failed_agent: str | None = None,
    ) -> AuditLogDB:
        """Log workflow failed event.

        Args:
            workflow_run_id: ID of the workflow.
            error: Error message.
            failed_agent: Name of the agent that failed (if applicable).

        Returns:
            The created audit log entry.
        """
        return self.log(
            workflow_run_id=workflow_run_id,
            event_type=AuditEventType.WORKFLOW_FAILED,
            actor=failed_agent or "system",
            action=f"Workflow failed: {error[:200]}",
            details={"error": error, "failed_agent": failed_agent},
        )

    # --- Agent Events ---

    def log_agent_started(
        self,
        workflow_run_id: str,
        agent_name: str,
        retry_count: int,
        input_summary: dict[str, Any] | None = None,
    ) -> AuditLogDB:
        """Log agent started event.

        Args:
            workflow_run_id: ID of the workflow.
            agent_name: Name of the agent.
            retry_count: Current retry count.
            input_summary: Summary of agent input (for audit trail).

        Returns:
            The created audit log entry.
        """
        return self.log(
            workflow_run_id=workflow_run_id,
            event_type=AuditEventType.AGENT_STARTED,
            actor=agent_name,
            action=f"Agent started (retry: {retry_count})",
            details={
                "agent_name": agent_name,
                "retry_count": retry_count,
                "input_summary": input_summary or {},
            },
        )

    def log_agent_completed(
        self,
        workflow_run_id: str,
        agent_name: str,
        duration_ms: float,
        output_summary: dict[str, Any] | None = None,
    ) -> AuditLogDB:
        """Log agent completed event.

        Args:
            workflow_run_id: ID of the workflow.
            agent_name: Name of the agent.
            duration_ms: Execution duration in milliseconds.
            output_summary: Summary of agent output (for audit trail).

        Returns:
            The created audit log entry.
        """
        return self.log(
            workflow_run_id=workflow_run_id,
            event_type=AuditEventType.AGENT_COMPLETED,
            actor=agent_name,
            action=f"Agent completed in {duration_ms:.0f}ms",
            details={
                "agent_name": agent_name,
                "duration_ms": duration_ms,
                "output_summary": output_summary or {},
            },
        )

    def log_agent_failed(
        self,
        workflow_run_id: str,
        agent_name: str,
        error: str,
    ) -> AuditLogDB:
        """Log agent failed event.

        Args:
            workflow_run_id: ID of the workflow.
            agent_name: Name of the agent.
            error: Error message.

        Returns:
            The created audit log entry.
        """
        return self.log(
            workflow_run_id=workflow_run_id,
            event_type=AuditEventType.AGENT_FAILED,
            actor=agent_name,
            action=f"Agent failed: {error[:200]}",
            details={"agent_name": agent_name, "error": error},
        )

    # --- Critic Events ---

    def log_critic_decision(
        self,
        workflow_run_id: str,
        critic_name: str,
        decision: str,
        feedback: str | None = None,
        issues_found: list[str] | None = None,
    ) -> AuditLogDB:
        """Log critic decision event.

        Args:
            workflow_run_id: ID of the workflow.
            critic_name: Name of the critic agent.
            decision: Decision made (pass, fail_retry, fail_max).
            feedback: Feedback message if applicable.
            issues_found: List of issues identified.

        Returns:
            The created audit log entry.
        """
        return self.log(
            workflow_run_id=workflow_run_id,
            event_type=AuditEventType.CRITIC_DECISION,
            actor=critic_name,
            action=f"Critic decision: {decision}",
            details={
                "critic_name": critic_name,
                "decision": decision,
                "feedback": feedback,
                "issues_found": issues_found or [],
            },
        )

    # --- Retry Events ---

    def log_retry_triggered(
        self,
        workflow_run_id: str,
        agent_name: str,
        retry_count: int,
        reason: str,
        critic_feedback: str | None = None,
    ) -> AuditLogDB:
        """Log retry triggered event.

        Args:
            workflow_run_id: ID of the workflow.
            agent_name: Name of the agent being retried.
            retry_count: New retry count after increment.
            reason: Reason for retry.
            critic_feedback: Full feedback from critic.

        Returns:
            The created audit log entry.
        """
        return self.log(
            workflow_run_id=workflow_run_id,
            event_type=AuditEventType.RETRY_TRIGGERED,
            actor=agent_name,
            action=f"Retry triggered (count: {retry_count}): {reason[:100]}",
            details={
                "agent_name": agent_name,
                "retry_count": retry_count,
                "reason": reason,
                "critic_feedback": critic_feedback,
            },
        )

    # --- Document Events ---

    def log_document_uploaded(
        self,
        workflow_run_id: str,
        document_id: str,
        filename: str,
        file_type: str,
        page_count: int | None,
    ) -> AuditLogDB:
        """Log document uploaded event.

        Args:
            workflow_run_id: ID of the workflow.
            document_id: ID of the document.
            filename: Original filename.
            file_type: Type of file (PDF, TXT).
            page_count: Number of pages.

        Returns:
            The created audit log entry.
        """
        return self.log(
            workflow_run_id=workflow_run_id,
            event_type=AuditEventType.DOCUMENT_UPLOADED,
            actor="system",
            action=f"Document uploaded: {filename}",
            details={
                "document_id": document_id,
                "filename": filename,
                "file_type": file_type,
                "page_count": page_count,
            },
        )

    def log_document_processed(
        self,
        workflow_run_id: str,
        document_id: str,
        filename: str,
        persons_extracted: int,
    ) -> AuditLogDB:
        """Log document processed event.

        Args:
            workflow_run_id: ID of the workflow.
            document_id: ID of the document.
            filename: Original filename.
            persons_extracted: Number of persons extracted.

        Returns:
            The created audit log entry.
        """
        return self.log(
            workflow_run_id=workflow_run_id,
            event_type=AuditEventType.DOCUMENT_PROCESSED,
            actor="extractor",
            action=f"Document processed: {filename} ({persons_extracted} persons)",
            details={
                "document_id": document_id,
                "filename": filename,
                "persons_extracted": persons_extracted,
            },
        )

    # --- Person Events ---

    def log_person_extracted(
        self,
        workflow_run_id: str,
        person_id: str,
        first_name: str,
        last_name: str,
        source_document: str,
    ) -> AuditLogDB:
        """Log person extracted event.

        Args:
            workflow_run_id: ID of the workflow.
            person_id: ID of the person record.
            first_name: Person's first name.
            last_name: Person's last name.
            source_document: Source document filename.

        Returns:
            The created audit log entry.
        """
        return self.log(
            workflow_run_id=workflow_run_id,
            event_type=AuditEventType.PERSON_EXTRACTED,
            actor="extractor",
            action=f"Person extracted: {first_name} {last_name}",
            details={
                "person_id": person_id,
                "first_name": first_name,
                "last_name": last_name,
                "source_document": source_document,
            },
        )

    def log_person_classified(
        self,
        workflow_run_id: str,
        person_id: str,
        first_name: str,
        last_name: str,
        classification: str,
        reasoning: str,
    ) -> AuditLogDB:
        """Log person classified event.

        Args:
            workflow_run_id: ID of the workflow.
            person_id: ID of the person record.
            first_name: Person's first name.
            last_name: Person's last name.
            classification: CSM or NON_CSM.
            reasoning: Classification reasoning.

        Returns:
            The created audit log entry.
        """
        return self.log(
            workflow_run_id=workflow_run_id,
            event_type=AuditEventType.PERSON_CLASSIFIED,
            actor="classifier",
            action=f"Person classified as {classification}: {first_name} {last_name}",
            details={
                "person_id": person_id,
                "first_name": first_name,
                "last_name": last_name,
                "classification": classification,
                "reasoning": reasoning[:500] if reasoning else None,
            },
        )

    # --- Query Functions ---

    def get_audit_trail(
        self,
        workflow_run_id: str,
        event_type: AuditEventType | str | None = None,
    ) -> list[AuditLogDB]:
        """Get audit trail for a workflow.

        Args:
            workflow_run_id: ID of the workflow.
            event_type: Optional filter by event type.

        Returns:
            List of audit log entries, ordered by timestamp.
        """
        query = self.db.query(AuditLogDB).filter(
            AuditLogDB.workflow_run_id == workflow_run_id
        )

        if event_type:
            event_type_str = (
                event_type.value if isinstance(event_type, AuditEventType) else event_type
            )
            query = query.filter(AuditLogDB.event_type == event_type_str)

        return query.order_by(AuditLogDB.event_timestamp).all()

    def verify_checksum(self, audit_log: AuditLogDB) -> bool:
        """Verify the integrity of an audit log entry.

        Args:
            audit_log: The audit log entry to verify.

        Returns:
            True if checksum is valid, False otherwise.
        """
        expected_checksum = compute_audit_checksum(
            audit_log.event_type,
            audit_log.event_timestamp,
            audit_log.actor,
            audit_log.action,
            audit_log.details,
        )
        return audit_log.checksum == expected_checksum

    def verify_audit_trail(self, workflow_run_id: str) -> dict[str, Any]:
        """Verify the integrity of an entire audit trail.

        Args:
            workflow_run_id: ID of the workflow.

        Returns:
            Dictionary with verification results.
        """
        logs = self.get_audit_trail(workflow_run_id)
        valid_count = 0
        invalid_entries = []

        for log in logs:
            if self.verify_checksum(log):
                valid_count += 1
            else:
                invalid_entries.append(log.id)

        return {
            "workflow_run_id": workflow_run_id,
            "total_entries": len(logs),
            "valid_entries": valid_count,
            "invalid_entries": invalid_entries,
            "integrity_verified": len(invalid_entries) == 0,
        }


# --- Factory Function ---


def create_audit_service(db: Session) -> AuditService:
    """Create an audit service instance.

    Args:
        db: SQLAlchemy database session.

    Returns:
        AuditService instance.
    """
    return AuditService(db)
