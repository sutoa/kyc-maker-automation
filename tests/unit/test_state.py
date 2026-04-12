"""Unit tests for workflow state management."""

import pytest

from src.core.state import WorkflowState, create_initial_state, update_workflow_failed, update_workflow_started
from src.services.document import DocumentInput, PageContent


def _doc(doc_id: str = "doc1") -> DocumentInput:
    return DocumentInput(
        document_id=doc_id,
        filename=f"{doc_id}.pdf",
        file_type="PDF",
        content="[PAGE 1]\nTest content",
        pages=[PageContent(page_number=1, text="Test content")],
        page_count=1,
    )


class TestCreateInitialState:
    def test_workflow_id_auto_generated(self):
        state = create_initial_state([_doc()])
        assert state["workflow_id"] is not None
        assert len(state["workflow_id"]) > 0

    def test_custom_workflow_id(self):
        state = create_initial_state([_doc()], workflow_id="my-id")
        assert state["workflow_id"] == "my-id"

    def test_documents_set(self):
        state = create_initial_state([_doc("a"), _doc("b")])
        assert len(state["documents"]) == 2

    def test_status_is_pending(self):
        state = create_initial_state([_doc()])
        assert state["status"] == "pending"

    def test_retry_counts_zero(self):
        state = create_initial_state([_doc()])
        assert state["extraction_retry_count"] == 0

    def test_new_state_keys_present(self):
        state = create_initial_state([_doc()])
        assert "extractor_critic_feedback" in state
        assert state["extractor_critic_feedback"] is None
        assert "csm_report" in state
        assert state["csm_report"] is None

    def test_no_dead_helper_imports(self):
        """Verify deleted helpers are truly gone."""
        import src.core.state as m
        assert not hasattr(m, "update_extraction_result")
        assert not hasattr(m, "update_extraction_retry")
        assert not hasattr(m, "update_extraction_passed")
        assert not hasattr(m, "update_reconciliation_result")
        assert not hasattr(m, "update_reconciliation_retry")
        assert not hasattr(m, "update_reconciliation_passed")
        assert not hasattr(m, "update_classification_result")
        assert not hasattr(m, "update_classification_retry")
        assert not hasattr(m, "update_classification_passed")
        assert not hasattr(m, "update_final_output")
        assert not hasattr(m, "MAX_RETRY_COUNT")
        assert not hasattr(m, "can_retry")
        assert not hasattr(m, "get_retry_count")
        assert not hasattr(m, "get_feedback")


class TestWorkflowStatusUpdates:
    def test_update_started(self):
        state = create_initial_state([_doc()])
        new = update_workflow_started(state)
        assert new["status"] == "in_progress"
        assert state["status"] == "pending"  # original unchanged

    def test_update_failed(self):
        state = create_initial_state([_doc()])
        new = update_workflow_failed(state, "extraction failed")
        assert new["status"] == "failed"
        assert new["failure_reason"] == "extraction failed"

    def test_update_failed_preserves_other_keys(self):
        state = create_initial_state([_doc("x")])
        new = update_workflow_failed(state, "boom")
        assert new["workflow_id"] == state["workflow_id"]
        assert new["documents"] == state["documents"]
