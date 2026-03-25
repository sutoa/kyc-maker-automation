"""Unit tests for AuditService."""

import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.services.audit import AuditEventType, AuditService, create_audit_service
from src.services.database import Base
from src.services.storage import (
    AuditLogDB,
    WorkflowRunDB,
    compute_audit_checksum,
    create_workflow_run,
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


@pytest.fixture
def audit_service(db_session):
    """Create an AuditService instance for testing."""
    return create_audit_service(db_session)


@pytest.fixture
def workflow_id(db_session):
    """Create a workflow and return its ID."""
    workflow = create_workflow_run(db_session)
    return workflow.id


class TestAuditServiceBasics:
    """Tests for basic AuditService operations."""

    def test_create_audit_service(self, db_session):
        """Test creating an audit service instance."""
        service = create_audit_service(db_session)
        assert service is not None
        assert isinstance(service, AuditService)

    def test_log_creates_entry(self, audit_service, workflow_id):
        """Test that log() creates an audit log entry."""
        audit_log = audit_service.log(
            workflow_run_id=workflow_id,
            event_type=AuditEventType.WORKFLOW_STARTED,
            actor="system",
            action="Test action",
            details={"test": "value"},
        )

        assert audit_log.id is not None
        assert audit_log.workflow_run_id == workflow_id
        assert audit_log.event_type == "workflow_started"
        assert audit_log.actor == "system"
        assert audit_log.action == "Test action"
        assert audit_log.details == {"test": "value"}
        assert audit_log.checksum is not None
        assert len(audit_log.checksum) == 64  # SHA-256 hex

    def test_log_with_string_event_type(self, audit_service, workflow_id):
        """Test that log() works with string event type."""
        audit_log = audit_service.log(
            workflow_run_id=workflow_id,
            event_type="custom_event",
            actor="test",
            action="Custom action",
        )

        assert audit_log.event_type == "custom_event"


class TestWorkflowEvents:
    """Tests for workflow lifecycle event logging."""

    def test_log_workflow_started(self, audit_service, workflow_id):
        """Test logging workflow started event."""
        audit_log = audit_service.log_workflow_started(
            workflow_run_id=workflow_id,
            document_count=3,
        )

        assert audit_log.event_type == "workflow_started"
        assert audit_log.actor == "system"
        assert "3 document(s)" in audit_log.action
        assert audit_log.details["document_count"] == 3

    def test_log_workflow_completed(self, audit_service, workflow_id):
        """Test logging workflow completed event."""
        audit_log = audit_service.log_workflow_completed(
            workflow_run_id=workflow_id,
            duration_seconds=45.5,
            csm_count=5,
            non_csm_count=10,
        )

        assert audit_log.event_type == "workflow_completed"
        assert audit_log.actor == "system"
        assert "45.5s" in audit_log.action
        assert audit_log.details["csm_count"] == 5
        assert audit_log.details["non_csm_count"] == 10
        assert audit_log.details["total_persons"] == 15

    def test_log_workflow_failed(self, audit_service, workflow_id):
        """Test logging workflow failed event."""
        audit_log = audit_service.log_workflow_failed(
            workflow_run_id=workflow_id,
            error="Maximum retries exceeded for extraction",
            failed_agent="extractor",
        )

        assert audit_log.event_type == "workflow_failed"
        assert audit_log.actor == "extractor"
        assert "Maximum retries" in audit_log.action
        assert audit_log.details["error"] == "Maximum retries exceeded for extraction"
        assert audit_log.details["failed_agent"] == "extractor"


class TestAgentEvents:
    """Tests for agent lifecycle event logging."""

    def test_log_agent_started(self, audit_service, workflow_id):
        """Test logging agent started event."""
        audit_log = audit_service.log_agent_started(
            workflow_run_id=workflow_id,
            agent_name="extractor",
            retry_count=1,
            input_summary={"documents": 3},
        )

        assert audit_log.event_type == "agent_started"
        assert audit_log.actor == "extractor"
        assert "retry: 1" in audit_log.action
        assert audit_log.details["retry_count"] == 1
        assert audit_log.details["input_summary"]["documents"] == 3

    def test_log_agent_completed(self, audit_service, workflow_id):
        """Test logging agent completed event."""
        audit_log = audit_service.log_agent_completed(
            workflow_run_id=workflow_id,
            agent_name="classifier",
            duration_ms=1500.5,
            output_summary={"classified": 10},
        )

        assert audit_log.event_type == "agent_completed"
        assert audit_log.actor == "classifier"
        assert "1501ms" in audit_log.action  # Rounded
        assert audit_log.details["duration_ms"] == 1500.5

    def test_log_agent_failed(self, audit_service, workflow_id):
        """Test logging agent failed event."""
        audit_log = audit_service.log_agent_failed(
            workflow_run_id=workflow_id,
            agent_name="reconciler",
            error="Connection timeout",
        )

        assert audit_log.event_type == "agent_failed"
        assert audit_log.actor == "reconciler"
        assert "Connection timeout" in audit_log.action
        assert audit_log.details["error"] == "Connection timeout"


class TestCriticEvents:
    """Tests for critic event logging."""

    def test_log_critic_decision_pass(self, audit_service, workflow_id):
        """Test logging critic pass decision."""
        audit_log = audit_service.log_critic_decision(
            workflow_run_id=workflow_id,
            critic_name="critic_1",
            decision="pass",
        )

        assert audit_log.event_type == "critic_decision"
        assert audit_log.actor == "critic_1"
        assert "pass" in audit_log.action
        assert audit_log.details["decision"] == "pass"

    def test_log_critic_decision_fail_retry(self, audit_service, workflow_id):
        """Test logging critic fail_retry decision with feedback."""
        audit_log = audit_service.log_critic_decision(
            workflow_run_id=workflow_id,
            critic_name="critic_2",
            decision="fail_retry",
            feedback="Missing source references",
            issues_found=["no_source", "incomplete_data"],
        )

        assert audit_log.event_type == "critic_decision"
        assert "fail_retry" in audit_log.action
        assert audit_log.details["feedback"] == "Missing source references"
        assert len(audit_log.details["issues_found"]) == 2


class TestRetryEvents:
    """Tests for retry event logging."""

    def test_log_retry_triggered(self, audit_service, workflow_id):
        """Test logging retry triggered event."""
        audit_log = audit_service.log_retry_triggered(
            workflow_run_id=workflow_id,
            agent_name="extractor",
            retry_count=2,
            reason="Quality check failed",
            critic_feedback="Extraction incomplete - missing 3 persons",
        )

        assert audit_log.event_type == "retry_triggered"
        assert audit_log.actor == "extractor"
        assert "count: 2" in audit_log.action
        assert audit_log.details["retry_count"] == 2
        assert audit_log.details["reason"] == "Quality check failed"
        assert "missing 3 persons" in audit_log.details["critic_feedback"]


class TestDocumentEvents:
    """Tests for document event logging."""

    def test_log_document_uploaded(self, audit_service, workflow_id):
        """Test logging document uploaded event."""
        audit_log = audit_service.log_document_uploaded(
            workflow_run_id=workflow_id,
            document_id="doc-123",
            filename="handelsregister.pdf",
            file_type="PDF",
            page_count=5,
        )

        assert audit_log.event_type == "document_uploaded"
        assert audit_log.actor == "system"
        assert "handelsregister.pdf" in audit_log.action
        assert audit_log.details["document_id"] == "doc-123"
        assert audit_log.details["page_count"] == 5

    def test_log_document_processed(self, audit_service, workflow_id):
        """Test logging document processed event."""
        audit_log = audit_service.log_document_processed(
            workflow_run_id=workflow_id,
            document_id="doc-123",
            filename="handelsregister.pdf",
            persons_extracted=7,
        )

        assert audit_log.event_type == "document_processed"
        assert audit_log.actor == "extractor"
        assert "7 persons" in audit_log.action
        assert audit_log.details["persons_extracted"] == 7


class TestPersonEvents:
    """Tests for person event logging."""

    def test_log_person_extracted(self, audit_service, workflow_id):
        """Test logging person extracted event."""
        audit_log = audit_service.log_person_extracted(
            workflow_run_id=workflow_id,
            person_id="person-456",
            first_name="Hans",
            last_name="Mueller",
            source_document="handelsregister.pdf",
        )

        assert audit_log.event_type == "person_extracted"
        assert "Hans Mueller" in audit_log.action
        assert audit_log.details["person_id"] == "person-456"
        assert audit_log.details["source_document"] == "handelsregister.pdf"

    def test_log_person_classified(self, audit_service, workflow_id):
        """Test logging person classified event."""
        audit_log = audit_service.log_person_classified(
            workflow_run_id=workflow_id,
            person_id="person-456",
            first_name="Hans",
            last_name="Mueller",
            classification="CSM",
            reasoning="Person has management role as Geschaeftsfuehrer",
        )

        assert audit_log.event_type == "person_classified"
        assert audit_log.actor == "classifier"
        assert "CSM" in audit_log.action
        assert audit_log.details["classification"] == "CSM"
        assert "management role" in audit_log.details["reasoning"]


class TestAuditTrailQueries:
    """Tests for audit trail query functions."""

    def test_get_audit_trail(self, audit_service, workflow_id):
        """Test retrieving full audit trail for a workflow."""
        # Create multiple audit logs
        audit_service.log_workflow_started(workflow_id, 2)
        audit_service.log_agent_started(workflow_id, "extractor", 0)
        audit_service.log_agent_completed(workflow_id, "extractor", 100.0)
        audit_service.log_workflow_completed(workflow_id, 5.0, 3, 2)

        # Get all logs
        logs = audit_service.get_audit_trail(workflow_id)

        assert len(logs) == 4
        # Should be ordered by timestamp
        assert logs[0].event_type == "workflow_started"
        assert logs[-1].event_type == "workflow_completed"

    def test_get_audit_trail_filtered_by_type(self, audit_service, workflow_id):
        """Test retrieving audit trail filtered by event type."""
        audit_service.log_workflow_started(workflow_id, 2)
        audit_service.log_agent_started(workflow_id, "extractor", 0)
        audit_service.log_agent_completed(workflow_id, "extractor", 100.0)

        # Filter by event type
        logs = audit_service.get_audit_trail(
            workflow_id, event_type=AuditEventType.AGENT_STARTED
        )

        assert len(logs) == 1
        assert logs[0].event_type == "agent_started"

    def test_get_audit_trail_empty(self, audit_service, db_session):
        """Test retrieving audit trail for non-existent workflow."""
        logs = audit_service.get_audit_trail("nonexistent-workflow-id")
        assert logs == []


class TestChecksumVerification:
    """Tests for checksum verification functions."""

    def test_verify_checksum_valid(self, audit_service, workflow_id):
        """Test verifying a valid checksum."""
        audit_log = audit_service.log_workflow_started(workflow_id, 3)

        is_valid = audit_service.verify_checksum(audit_log)
        assert is_valid is True

    def test_verify_audit_trail_all_valid(self, audit_service, workflow_id):
        """Test verifying entire audit trail with valid checksums."""
        audit_service.log_workflow_started(workflow_id, 2)
        audit_service.log_agent_started(workflow_id, "extractor", 0)
        audit_service.log_workflow_completed(workflow_id, 10.0, 5, 3)

        result = audit_service.verify_audit_trail(workflow_id)

        assert result["workflow_run_id"] == workflow_id
        assert result["total_entries"] == 3
        assert result["valid_entries"] == 3
        assert result["invalid_entries"] == []
        assert result["integrity_verified"] is True


class TestAuditLogImmutability:
    """Tests for audit log immutability enforcement.

    These tests verify that the AuditService creates logs that cannot
    be modified or deleted, as required by FR-029.
    """

    def test_audit_log_has_checksum(self, audit_service, workflow_id):
        """Test that every audit log entry has a SHA-256 checksum."""
        audit_log = audit_service.log_workflow_started(workflow_id, 3)

        assert audit_log.checksum is not None
        assert len(audit_log.checksum) == 64  # SHA-256 produces 64 hex chars

    def test_audit_log_checksum_matches_content(self, audit_service, workflow_id):
        """Test that checksum matches the log content."""
        audit_log = audit_service.log_agent_completed(
            workflow_id, "classifier", 500.0, {"count": 10}
        )

        # Recompute checksum from stored values
        expected_checksum = compute_audit_checksum(
            audit_log.event_type,
            audit_log.event_timestamp,
            audit_log.actor,
            audit_log.action,
            audit_log.details,
        )

        assert audit_log.checksum == expected_checksum

    def test_audit_log_cannot_be_updated(self, audit_service, workflow_id, db_session):
        """Test that audit logs cannot be updated (immutability)."""
        audit_log = audit_service.log_workflow_started(workflow_id, 3)

        # Attempt to modify the log
        audit_log.action = "Modified action"

        # The database should prevent this
        with pytest.raises(ValueError, match="Audit logs are immutable"):
            db_session.commit()

    def test_audit_log_cannot_be_deleted(self, audit_service, workflow_id, db_session):
        """Test that audit logs cannot be deleted (immutability)."""
        audit_log = audit_service.log_workflow_started(workflow_id, 3)

        # Attempt to delete the log
        db_session.delete(audit_log)

        # The database should prevent this
        with pytest.raises(ValueError, match="Audit logs are immutable"):
            db_session.commit()

    def test_multiple_logs_maintain_integrity(self, audit_service, workflow_id):
        """Test that multiple audit logs all maintain integrity."""
        # Create several different types of logs
        log1 = audit_service.log_workflow_started(workflow_id, 2)
        log2 = audit_service.log_agent_started(workflow_id, "extractor", 0)
        log3 = audit_service.log_critic_decision(workflow_id, "critic_1", "pass")
        log4 = audit_service.log_workflow_completed(workflow_id, 30.0, 5, 3)

        # All should have valid checksums
        for log in [log1, log2, log3, log4]:
            assert audit_service.verify_checksum(log) is True


class TestAuditEventTypes:
    """Tests for AuditEventType enum."""

    def test_all_workflow_event_types(self):
        """Test that all workflow event types are defined."""
        assert AuditEventType.WORKFLOW_STARTED.value == "workflow_started"
        assert AuditEventType.WORKFLOW_COMPLETED.value == "workflow_completed"
        assert AuditEventType.WORKFLOW_FAILED.value == "workflow_failed"

    def test_all_agent_event_types(self):
        """Test that all agent event types are defined."""
        assert AuditEventType.AGENT_STARTED.value == "agent_started"
        assert AuditEventType.AGENT_COMPLETED.value == "agent_completed"
        assert AuditEventType.AGENT_FAILED.value == "agent_failed"

    def test_all_critic_event_types(self):
        """Test that critic event types are defined."""
        assert AuditEventType.CRITIC_DECISION.value == "critic_decision"
        assert AuditEventType.RETRY_TRIGGERED.value == "retry_triggered"

    def test_all_document_event_types(self):
        """Test that all document event types are defined."""
        assert AuditEventType.DOCUMENT_UPLOADED.value == "document_uploaded"
        assert AuditEventType.DOCUMENT_PROCESSED.value == "document_processed"

    def test_all_person_event_types(self):
        """Test that all person event types are defined."""
        assert AuditEventType.PERSON_EXTRACTED.value == "person_extracted"
        assert AuditEventType.PERSON_CLASSIFIED.value == "person_classified"
