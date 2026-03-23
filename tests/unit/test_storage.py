"""Unit tests for storage CRUD operations."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.enums import CriticDecision, FileType, WorkflowStatus
from src.services.database import Base
from src.services.storage import (
    AuditLogDB,
    WorkflowRunDB,
    complete_agent_execution,
    compute_audit_checksum,
    create_agent_execution,
    create_audit_log,
    create_critic_feedback,
    create_uploaded_document,
    create_workflow_run,
    get_workflow_run,
    save_workflow_output,
    update_workflow_status,
)


@pytest.fixture
def db_session():
    """Create a test database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


class TestWorkflowRunCRUD:
    """Tests for WorkflowRun CRUD operations."""

    def test_create_workflow_run(self, db_session):
        """Test creating a new workflow run."""
        workflow = create_workflow_run(db_session)

        assert workflow.id is not None
        assert len(workflow.id) == 36  # UUID format
        assert workflow.status == WorkflowStatus.PENDING
        assert workflow.created_at is not None
        assert workflow.started_at is None
        assert workflow.completed_at is None

    def test_get_workflow_run(self, db_session):
        """Test retrieving a workflow run by ID."""
        workflow = create_workflow_run(db_session)
        retrieved = get_workflow_run(db_session, workflow.id)

        assert retrieved is not None
        assert retrieved.id == workflow.id

    def test_get_workflow_run_not_found(self, db_session):
        """Test retrieving a non-existent workflow run."""
        retrieved = get_workflow_run(db_session, "nonexistent-id")

        assert retrieved is None

    def test_update_workflow_status_to_in_progress(self, db_session):
        """Test updating workflow status to in_progress."""
        workflow = create_workflow_run(db_session)
        updated = update_workflow_status(
            db_session, workflow.id, WorkflowStatus.IN_PROGRESS
        )

        assert updated.status == WorkflowStatus.IN_PROGRESS
        assert updated.started_at is not None

    def test_update_workflow_status_to_completed(self, db_session):
        """Test updating workflow status to completed."""
        workflow = create_workflow_run(db_session)
        update_workflow_status(db_session, workflow.id, WorkflowStatus.IN_PROGRESS)
        updated = update_workflow_status(
            db_session, workflow.id, WorkflowStatus.COMPLETED
        )

        assert updated.status == WorkflowStatus.COMPLETED
        assert updated.completed_at is not None
        assert updated.duration_seconds is not None
        assert updated.retention_until is not None

    def test_update_workflow_status_to_failed(self, db_session):
        """Test updating workflow status to failed with reason."""
        workflow = create_workflow_run(db_session)
        update_workflow_status(db_session, workflow.id, WorkflowStatus.IN_PROGRESS)
        updated = update_workflow_status(
            db_session,
            workflow.id,
            WorkflowStatus.FAILED,
            failure_reason="Max retries exceeded",
        )

        assert updated.status == WorkflowStatus.FAILED
        assert updated.failure_reason == "Max retries exceeded"
        assert updated.retention_until is not None

    def test_save_workflow_output(self, db_session):
        """Test saving workflow output path."""
        workflow = create_workflow_run(db_session)
        updated = save_workflow_output(
            db_session, workflow.id, "/output/workflow_123.json"
        )

        assert updated.output_json_path == "/output/workflow_123.json"


class TestUploadedDocumentCRUD:
    """Tests for UploadedDocument CRUD operations."""

    def test_create_uploaded_document(self, db_session):
        """Test creating an uploaded document record."""
        workflow = create_workflow_run(db_session)
        document = create_uploaded_document(
            db_session,
            workflow_run_id=workflow.id,
            filename="handelsregister.pdf",
            file_type=FileType.PDF,
            file_path="/uploads/handelsregister.pdf",
            file_size_bytes=1024000,
            page_count=5,
        )

        assert document.id is not None
        assert document.filename == "handelsregister.pdf"
        assert document.file_type == FileType.PDF
        assert document.page_count == 5
        assert document.workflow_run_id == workflow.id


class TestAgentExecutionCRUD:
    """Tests for AgentExecution CRUD operations."""

    def test_create_agent_execution(self, db_session):
        """Test creating an agent execution record."""
        workflow = create_workflow_run(db_session)
        execution = create_agent_execution(
            db_session,
            workflow_run_id=workflow.id,
            agent_name="extractor",
            input_payload={"documents": []},
            retry_count=0,
        )

        assert execution.id is not None
        assert execution.agent_name == "extractor"
        assert execution.status == "running"
        assert execution.retry_count == 0

    def test_complete_agent_execution(self, db_session):
        """Test completing an agent execution."""
        workflow = create_workflow_run(db_session)
        execution = create_agent_execution(
            db_session,
            workflow_run_id=workflow.id,
            agent_name="extractor",
            input_payload={"documents": []},
        )

        completed = complete_agent_execution(
            db_session,
            execution_id=execution.id,
            output_payload={"extracted_persons": []},
            status="completed",
        )

        assert completed.status == "completed"
        assert completed.ended_at is not None
        assert completed.duration_ms is not None
        assert completed.output_payload == {"extracted_persons": []}


class TestCriticFeedbackCRUD:
    """Tests for CriticFeedback CRUD operations."""

    def test_create_critic_feedback_pass(self, db_session):
        """Test creating critic feedback with pass decision."""
        workflow = create_workflow_run(db_session)
        execution = create_agent_execution(
            db_session,
            workflow_run_id=workflow.id,
            agent_name="extractor",
            input_payload={},
        )

        feedback = create_critic_feedback(
            db_session,
            agent_execution_id=execution.id,
            critic_agent_name="critic_1",
            decision=CriticDecision.PASS,
            issues_found=[],
        )

        assert feedback.id is not None
        assert feedback.decision == CriticDecision.PASS
        assert feedback.issues_found == []

    def test_create_critic_feedback_fail_retry(self, db_session):
        """Test creating critic feedback with fail_retry decision."""
        workflow = create_workflow_run(db_session)
        execution = create_agent_execution(
            db_session,
            workflow_run_id=workflow.id,
            agent_name="extractor",
            input_payload={},
        )

        issues = [
            {
                "extraction_id": "123",
                "issue_type": "missing_source",
                "description": "No source reference provided",
                "severity": "error",
            }
        ]

        feedback = create_critic_feedback(
            db_session,
            agent_execution_id=execution.id,
            critic_agent_name="critic_1",
            decision=CriticDecision.FAIL_RETRY,
            issues_found=issues,
            suggested_corrections="Add source references for all extracted persons",
        )

        assert feedback.decision == CriticDecision.FAIL_RETRY
        assert len(feedback.issues_found) == 1
        assert feedback.suggested_corrections is not None


class TestAuditLogCRUD:
    """Tests for AuditLog CRUD operations."""

    def test_create_audit_log(self, db_session):
        """Test creating an audit log entry."""
        workflow = create_workflow_run(db_session)
        audit_log = create_audit_log(
            db_session,
            workflow_run_id=workflow.id,
            event_type="agent_started",
            actor="extractor",
            action="Started extraction of documents",
            details={"document_count": 3},
        )

        assert audit_log.id is not None
        assert audit_log.event_type == "agent_started"
        assert audit_log.checksum is not None
        assert len(audit_log.checksum) == 64  # SHA-256 hex

    def test_audit_log_checksum_integrity(self, db_session):
        """Test that audit log checksum matches computed checksum."""
        workflow = create_workflow_run(db_session)
        audit_log = create_audit_log(
            db_session,
            workflow_run_id=workflow.id,
            event_type="workflow_completed",
            actor="system",
            action="Workflow completed successfully",
            details={"csm_count": 5, "non_csm_count": 10},
        )

        expected_checksum = compute_audit_checksum(
            audit_log.event_type,
            audit_log.event_timestamp,
            audit_log.actor,
            audit_log.action,
            audit_log.details,
        )

        assert audit_log.checksum == expected_checksum

    def test_audit_log_immutability_update(self, db_session):
        """Test that audit logs cannot be updated."""
        workflow = create_workflow_run(db_session)
        audit_log = create_audit_log(
            db_session,
            workflow_run_id=workflow.id,
            event_type="test_event",
            actor="test",
            action="test action",
            details={},
        )

        # Try to update the audit log
        audit_log.action = "modified action"
        with pytest.raises(ValueError, match="Audit logs are immutable"):
            db_session.commit()

    def test_audit_log_immutability_delete(self, db_session):
        """Test that audit logs cannot be deleted."""
        workflow = create_workflow_run(db_session)
        audit_log = create_audit_log(
            db_session,
            workflow_run_id=workflow.id,
            event_type="test_event",
            actor="test",
            action="test action",
            details={},
        )

        # Try to delete the audit log
        db_session.delete(audit_log)
        with pytest.raises(ValueError, match="Audit logs are immutable"):
            db_session.commit()


class TestComputeAuditChecksum:
    """Tests for audit checksum computation."""

    def test_compute_checksum_deterministic(self):
        """Test that checksum computation is deterministic."""
        from datetime import datetime

        timestamp = datetime(2025, 3, 22, 10, 30, 0)
        details = {"key": "value", "count": 5}

        checksum1 = compute_audit_checksum(
            "event_type", timestamp, "actor", "action", details
        )
        checksum2 = compute_audit_checksum(
            "event_type", timestamp, "actor", "action", details
        )

        assert checksum1 == checksum2

    def test_compute_checksum_different_inputs(self):
        """Test that different inputs produce different checksums."""
        from datetime import datetime

        timestamp = datetime(2025, 3, 22, 10, 30, 0)

        checksum1 = compute_audit_checksum(
            "event_type", timestamp, "actor1", "action", {}
        )
        checksum2 = compute_audit_checksum(
            "event_type", timestamp, "actor2", "action", {}
        )

        assert checksum1 != checksum2
