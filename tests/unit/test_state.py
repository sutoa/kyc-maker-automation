"""Unit tests for workflow state management."""

from datetime import datetime
from uuid import uuid4

import pytest

from src.core.state import (
    MAX_RETRY_COUNT,
    WorkflowState,
    can_retry,
    create_initial_state,
    get_feedback,
    get_retry_count,
    update_classification_passed,
    update_classification_result,
    update_classification_retry,
    update_extraction_passed,
    update_extraction_result,
    update_extraction_retry,
    update_final_output,
    update_reconciliation_passed,
    update_reconciliation_result,
    update_reconciliation_retry,
    update_workflow_failed,
    update_workflow_started,
)
from src.models.enums import CriticDecision
from src.models.output import DocumentManifestEntry
from src.models.person import (
    ClassifiedPerson,
    DuplicateGroup,
    ExtractedPerson,
    ReconciledPerson,
    SourceReference,
)
from src.models.workflow import CriticFeedback
from src.services.document import DocumentInput, PageContent


# --- Test Fixtures ---


def create_test_document_input(doc_id: str = "doc1") -> DocumentInput:
    """Create a test DocumentInput."""
    return DocumentInput(
        document_id=doc_id,
        filename=f"{doc_id}.pdf",
        file_type="PDF",
        content="[PAGE 1]\nTest content",
        pages=[PageContent(page_number=1, text="Test content")],
        page_count=1,
    )


def create_test_extracted_person(extraction_id: str = "ext1") -> ExtractedPerson:
    """Create a test ExtractedPerson."""
    return ExtractedPerson(
        extraction_id=extraction_id,
        first_name="Hans",
        last_name="Müller",
        job_title="Managing Director",
        source_references=[
            SourceReference(
                document_id="doc1",
                filename="doc1.pdf",
                page_number=1,
            )
        ],
    )


def create_test_reconciled_person(person_id: str = "person1") -> ReconciledPerson:
    """Create a test ReconciledPerson."""
    return ReconciledPerson(
        person_id=person_id,
        first_name="Hans",
        last_name="Müller",
        first_name_normalized="hans",
        last_name_normalized="muller",
        job_title="Managing Director",
        source_references=[
            SourceReference(
                document_id="doc1",
                filename="doc1.pdf",
                page_number=1,
            )
        ],
    )


def create_test_classified_person(
    person_id: str = "person1",
    classification: str = "CSM",
) -> ClassifiedPerson:
    """Create a test ClassifiedPerson."""
    return ClassifiedPerson(
        person_id=person_id,
        first_name="Hans",
        last_name="Müller",
        job_title="Managing Director",
        source_references=[
            SourceReference(
                document_id="doc1",
                filename="doc1.pdf",
                page_number=1,
            )
        ],
        classification=classification,
        reasoning="Managing Director is a CSM role per criteria 1.",
        criteria_met=["Criterion 1: Executive role"],
    )


def create_test_critic_feedback(critic_name: str = "critic_1") -> CriticFeedback:
    """Create a test CriticFeedback."""
    return CriticFeedback(
        id=str(uuid4()),
        agent_execution_id=str(uuid4()),
        critic_agent_name=critic_name,
        decision=CriticDecision.FAIL_RETRY,
        issues_found=[{"issue_type": "missing_field", "description": "Missing date of birth"}],
        suggested_corrections="Please extract date of birth from page 2.",
        created_at=datetime.now(),
    )


# --- Test Classes ---


class TestCreateInitialState:
    """Tests for create_initial_state function."""

    def test_create_with_single_document(self):
        """Test creating state with a single document."""
        doc = create_test_document_input()
        state = create_initial_state([doc])

        assert state["workflow_id"] is not None
        assert len(state["documents"]) == 1
        assert state["documents"][0].document_id == "doc1"
        assert state["status"] == "pending"
        assert state["current_agent"] == "extractor"

    def test_create_with_multiple_documents(self):
        """Test creating state with multiple documents."""
        docs = [
            create_test_document_input("doc1"),
            create_test_document_input("doc2"),
            create_test_document_input("doc3"),
        ]
        state = create_initial_state(docs)

        assert len(state["documents"]) == 3
        assert state["documents"][0].document_id == "doc1"
        assert state["documents"][1].document_id == "doc2"
        assert state["documents"][2].document_id == "doc3"

    def test_create_with_custom_workflow_id(self):
        """Test creating state with a custom workflow ID."""
        doc = create_test_document_input()
        workflow_id = "custom-workflow-123"
        state = create_initial_state([doc], workflow_id=workflow_id)

        assert state["workflow_id"] == workflow_id

    def test_initial_state_has_empty_lists(self):
        """Test that initial state has empty person lists."""
        doc = create_test_document_input()
        state = create_initial_state([doc])

        assert state["extracted_persons"] == []
        assert state["reconciled_persons"] == []
        assert state["classified_persons"] == []
        assert state["duplicate_groups"] == []
        assert state["document_manifest"] == []
        assert state["csm_list"] == []
        assert state["non_csm_list"] == []

    def test_initial_state_has_zero_retry_counts(self):
        """Test that initial state has zero retry counts."""
        doc = create_test_document_input()
        state = create_initial_state([doc])

        assert state["extraction_retry_count"] == 0
        assert state["reconciliation_retry_count"] == 0
        assert state["classification_retry_count"] == 0

    def test_initial_state_has_no_feedback(self):
        """Test that initial state has no feedback."""
        doc = create_test_document_input()
        state = create_initial_state([doc])

        assert state["extraction_feedback"] is None
        assert state["reconciliation_feedback"] is None
        assert state["classification_feedback"] is None
        assert state["last_critic_feedback"] is None
        assert state["failure_reason"] is None


class TestExtractionPhaseUpdates:
    """Tests for extraction phase state updates."""

    def test_update_extraction_result(self):
        """Test updating state with extraction results."""
        doc = create_test_document_input()
        state = create_initial_state([doc])
        persons = [create_test_extracted_person("ext1"), create_test_extracted_person("ext2")]

        new_state = update_extraction_result(state, persons)

        assert len(new_state["extracted_persons"]) == 2
        assert new_state["current_agent"] == "critic_1"

    def test_update_extraction_retry(self):
        """Test updating state for extraction retry."""
        doc = create_test_document_input()
        state = create_initial_state([doc])
        feedback = create_test_critic_feedback("critic_1")

        new_state = update_extraction_retry(state, "Please extract date of birth", feedback)

        assert new_state["extraction_retry_count"] == 1
        assert new_state["extraction_feedback"] == "Please extract date of birth"
        assert new_state["last_critic_feedback"] == feedback
        assert new_state["current_agent"] == "extractor"

    def test_update_extraction_retry_increments_count(self):
        """Test that retry count increments correctly."""
        doc = create_test_document_input()
        state = create_initial_state([doc])
        feedback = create_test_critic_feedback("critic_1")

        state = update_extraction_retry(state, "Feedback 1", feedback)
        assert state["extraction_retry_count"] == 1

        state = update_extraction_retry(state, "Feedback 2", feedback)
        assert state["extraction_retry_count"] == 2

        state = update_extraction_retry(state, "Feedback 3", feedback)
        assert state["extraction_retry_count"] == 3

    def test_update_extraction_passed(self):
        """Test updating state when extraction passes."""
        doc = create_test_document_input()
        state = create_initial_state([doc])
        state = update_extraction_retry(state, "Some feedback", create_test_critic_feedback())

        new_state = update_extraction_passed(state)

        assert new_state["extraction_feedback"] is None
        assert new_state["current_agent"] == "reconciler"


class TestReconciliationPhaseUpdates:
    """Tests for reconciliation phase state updates."""

    def test_update_reconciliation_result(self):
        """Test updating state with reconciliation results."""
        doc = create_test_document_input()
        state = create_initial_state([doc])
        persons = [create_test_reconciled_person("p1")]
        groups = [DuplicateGroup(primary_person_id="p1", merged_extraction_ids=["e1", "e2"], match_score=0.95)]

        new_state = update_reconciliation_result(state, persons, groups)

        assert len(new_state["reconciled_persons"]) == 1
        assert len(new_state["duplicate_groups"]) == 1
        assert new_state["current_agent"] == "critic_2"

    def test_update_reconciliation_retry(self):
        """Test updating state for reconciliation retry."""
        doc = create_test_document_input()
        state = create_initial_state([doc])
        feedback = create_test_critic_feedback("critic_2")

        new_state = update_reconciliation_retry(state, "Missed duplicate", feedback)

        assert new_state["reconciliation_retry_count"] == 1
        assert new_state["reconciliation_feedback"] == "Missed duplicate"
        assert new_state["current_agent"] == "reconciler"

    def test_update_reconciliation_passed(self):
        """Test updating state when reconciliation passes."""
        doc = create_test_document_input()
        state = create_initial_state([doc])

        new_state = update_reconciliation_passed(state)

        assert new_state["reconciliation_feedback"] is None
        assert new_state["current_agent"] == "classifier"


class TestClassificationPhaseUpdates:
    """Tests for classification phase state updates."""

    def test_update_classification_result(self):
        """Test updating state with classification results."""
        doc = create_test_document_input()
        state = create_initial_state([doc])
        persons = [create_test_classified_person("p1", "CSM")]

        new_state = update_classification_result(state, persons)

        assert len(new_state["classified_persons"]) == 1
        assert new_state["current_agent"] == "critic_3"

    def test_update_classification_retry(self):
        """Test updating state for classification retry."""
        doc = create_test_document_input()
        state = create_initial_state([doc])
        feedback = create_test_critic_feedback("critic_3")

        new_state = update_classification_retry(state, "Weak reasoning", feedback)

        assert new_state["classification_retry_count"] == 1
        assert new_state["classification_feedback"] == "Weak reasoning"
        assert new_state["current_agent"] == "classifier"

    def test_update_classification_passed(self):
        """Test updating state when classification passes."""
        doc = create_test_document_input()
        state = create_initial_state([doc])

        new_state = update_classification_passed(state)

        assert new_state["classification_feedback"] is None
        assert new_state["current_agent"] == "formatter"


class TestFinalOutputUpdate:
    """Tests for final output state update."""

    def test_update_final_output(self):
        """Test updating state with final output."""
        doc = create_test_document_input()
        state = create_initial_state([doc])

        manifest = [DocumentManifestEntry(filename="doc1.pdf", file_type="PDF", page_count=1, processing_status="processed")]
        csm = [create_test_classified_person("p1", "CSM")]
        non_csm = [create_test_classified_person("p2", "NON_CSM")]

        new_state = update_final_output(state, manifest, csm, non_csm)

        assert len(new_state["document_manifest"]) == 1
        assert len(new_state["csm_list"]) == 1
        assert len(new_state["non_csm_list"]) == 1
        assert new_state["status"] == "completed"
        assert new_state["current_agent"] == ""

    def test_update_final_output_empty_lists(self):
        """Test final output with empty person lists."""
        doc = create_test_document_input()
        state = create_initial_state([doc])

        manifest = [DocumentManifestEntry(filename="doc1.pdf", file_type="PDF", page_count=1, processing_status="processed")]

        new_state = update_final_output(state, manifest, [], [])

        assert new_state["csm_list"] == []
        assert new_state["non_csm_list"] == []
        assert new_state["status"] == "completed"


class TestWorkflowStatusUpdates:
    """Tests for workflow status updates."""

    def test_update_workflow_started(self):
        """Test updating state when workflow starts."""
        doc = create_test_document_input()
        state = create_initial_state([doc])

        new_state = update_workflow_started(state)

        assert new_state["status"] == "in_progress"

    def test_update_workflow_failed(self):
        """Test updating state when workflow fails."""
        doc = create_test_document_input()
        state = create_initial_state([doc])

        new_state = update_workflow_failed(state, "Maximum retries exceeded for extraction")

        assert new_state["status"] == "failed"
        assert new_state["failure_reason"] == "Maximum retries exceeded for extraction"

    def test_update_workflow_failed_with_critic_feedback(self):
        """Test workflow failure with critic feedback."""
        doc = create_test_document_input()
        state = create_initial_state([doc])
        feedback = create_test_critic_feedback()

        new_state = update_workflow_failed(state, "Max retries", feedback)

        assert new_state["status"] == "failed"
        assert new_state["last_critic_feedback"] == feedback


class TestRetryCountHelpers:
    """Tests for retry count helper functions."""

    def test_get_retry_count_extraction(self):
        """Test getting extraction retry count."""
        doc = create_test_document_input()
        state = create_initial_state([doc])

        assert get_retry_count(state, "extraction") == 0

        state["extraction_retry_count"] = 3
        assert get_retry_count(state, "extraction") == 3

    def test_get_retry_count_reconciliation(self):
        """Test getting reconciliation retry count."""
        doc = create_test_document_input()
        state = create_initial_state([doc])
        state["reconciliation_retry_count"] = 2

        assert get_retry_count(state, "reconciliation") == 2

    def test_get_retry_count_classification(self):
        """Test getting classification retry count."""
        doc = create_test_document_input()
        state = create_initial_state([doc])
        state["classification_retry_count"] = 4

        assert get_retry_count(state, "classification") == 4

    def test_get_retry_count_invalid_phase(self):
        """Test that invalid phase raises error."""
        doc = create_test_document_input()
        state = create_initial_state([doc])

        with pytest.raises(ValueError, match="Invalid phase"):
            get_retry_count(state, "invalid")

    def test_can_retry_below_max(self):
        """Test that retry is allowed below max count."""
        doc = create_test_document_input()
        state = create_initial_state([doc])

        assert can_retry(state, "extraction")
        assert can_retry(state, "reconciliation")
        assert can_retry(state, "classification")

    def test_can_retry_at_max(self):
        """Test that retry is not allowed at max count."""
        doc = create_test_document_input()
        state = create_initial_state([doc])
        state["extraction_retry_count"] = MAX_RETRY_COUNT

        assert not can_retry(state, "extraction")

    def test_can_retry_above_max(self):
        """Test that retry is not allowed above max count."""
        doc = create_test_document_input()
        state = create_initial_state([doc])
        state["reconciliation_retry_count"] = MAX_RETRY_COUNT + 1

        assert not can_retry(state, "reconciliation")


class TestFeedbackHelpers:
    """Tests for feedback helper functions."""

    def test_get_feedback_extraction(self):
        """Test getting extraction feedback."""
        doc = create_test_document_input()
        state = create_initial_state([doc])

        assert get_feedback(state, "extraction") is None

        state["extraction_feedback"] = "Extract DOB"
        assert get_feedback(state, "extraction") == "Extract DOB"

    def test_get_feedback_reconciliation(self):
        """Test getting reconciliation feedback."""
        doc = create_test_document_input()
        state = create_initial_state([doc])
        state["reconciliation_feedback"] = "Check duplicates"

        assert get_feedback(state, "reconciliation") == "Check duplicates"

    def test_get_feedback_classification(self):
        """Test getting classification feedback."""
        doc = create_test_document_input()
        state = create_initial_state([doc])
        state["classification_feedback"] = "Strengthen reasoning"

        assert get_feedback(state, "classification") == "Strengthen reasoning"

    def test_get_feedback_invalid_phase(self):
        """Test that invalid phase raises error."""
        doc = create_test_document_input()
        state = create_initial_state([doc])

        with pytest.raises(ValueError, match="Invalid phase"):
            get_feedback(state, "invalid_phase")


class TestMaxRetryCount:
    """Tests for MAX_RETRY_COUNT constant."""

    def test_max_retry_count_is_four(self):
        """Test that max retry count is 4 as per spec."""
        assert MAX_RETRY_COUNT == 4


class TestStateImmutability:
    """Tests to verify state update functions return new state objects."""

    def test_extraction_update_preserves_original(self):
        """Test that extraction update doesn't modify original state."""
        doc = create_test_document_input()
        original_state = create_initial_state([doc])
        original_agent = original_state["current_agent"]

        persons = [create_test_extracted_person()]
        new_state = update_extraction_result(original_state, persons)

        # Original should be unchanged
        assert original_state["current_agent"] == original_agent
        assert new_state["current_agent"] == "critic_1"

    def test_workflow_start_preserves_original(self):
        """Test that workflow start doesn't modify original state."""
        doc = create_test_document_input()
        original_state = create_initial_state([doc])
        original_status = original_state["status"]

        new_state = update_workflow_started(original_state)

        assert original_state["status"] == original_status
        assert new_state["status"] == "in_progress"
