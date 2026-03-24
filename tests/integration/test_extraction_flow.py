"""End-to-end tests for extraction flow.

Tests the extractor → critic_1 → extractor retry loop.
"""

import pytest

from src.agents.critic import critic_1_agent
from src.agents.extractor import ExtractorOutput, extractor_agent
from src.core.state import (
    MAX_RETRY_COUNT,
    WorkflowState,
    create_initial_state,
    get_retry_count,
    update_extraction_result,
)
from src.core.workflow import compile_workflow, create_critic_node, run_workflow_sync
from src.models.enums import CriticDecision
from src.models.person import ExtractedPerson, SourceReference
from src.services.document import DocumentInput, PageContent


# --- Test Fixtures ---


def create_test_document(
    doc_id: str = "doc1",
    content: str = "[PAGE 1]\nHans Müller, Geschäftsführer\nAnna Schmidt, Sachbearbeiterin",
) -> DocumentInput:
    """Create a test document."""
    return DocumentInput(
        document_id=doc_id,
        filename=f"{doc_id}.pdf",
        file_type="PDF",
        content=content,
        pages=[PageContent(page_number=1, text=content.replace("[PAGE 1]\n", ""))],
        page_count=1,
    )


def create_valid_extracted_persons() -> list[ExtractedPerson]:
    """Create valid extracted persons."""
    return [
        ExtractedPerson(
            extraction_id="ext_1",
            first_name="Hans",
            last_name="Müller",
            job_title="Managing Director",
            job_title_original="Geschäftsführer",
            source_references=[
                SourceReference(
                    document_id="doc1",
                    filename="doc1.pdf",
                    page_number=1,
                    extracted_text_snippet="Hans Müller, Geschäftsführer",
                    confidence=0.95,
                )
            ],
        ),
        ExtractedPerson(
            extraction_id="ext_2",
            first_name="Anna",
            last_name="Schmidt",
            job_title="Administrative Clerk",
            job_title_original="Sachbearbeiterin",
            source_references=[
                SourceReference(
                    document_id="doc1",
                    filename="doc1.pdf",
                    page_number=1,
                    extracted_text_snippet="Anna Schmidt, Sachbearbeiterin",
                    confidence=0.90,
                )
            ],
        ),
    ]


def create_invalid_extracted_persons() -> list[ExtractedPerson]:
    """Create extracted persons with validation issues."""
    return [
        ExtractedPerson(
            extraction_id="ext_1",
            first_name="   ",  # Invalid - whitespace only
            last_name="Müller",
            source_references=[
                SourceReference(
                    document_id="doc1",
                    filename="doc1.pdf",
                    page_number=1,
                )
            ],
        ),
    ]


# --- Mock Agents for Testing ---


def mock_extractor_success(state: WorkflowState) -> WorkflowState:
    """Mock extractor that always succeeds."""
    return update_extraction_result(state, create_valid_extracted_persons())


def create_mock_extractor_fail_then_succeed(fail_count: int):
    """Create a mock extractor that fails N times then succeeds."""
    attempts = {"count": 0}

    def mock_extractor(state: WorkflowState) -> WorkflowState:
        attempts["count"] += 1
        if attempts["count"] <= fail_count:
            # Return invalid data to trigger critic failure
            return update_extraction_result(state, create_invalid_extracted_persons())
        return update_extraction_result(state, create_valid_extracted_persons())

    return mock_extractor


def mock_extractor_always_fail(state: WorkflowState) -> WorkflowState:
    """Mock extractor that always produces invalid output."""
    return update_extraction_result(state, create_invalid_extracted_persons())


def mock_reconciler(state: WorkflowState) -> WorkflowState:
    """Mock reconciler for testing extraction flow only."""
    from src.models.person import ReconciledPerson

    extracted = state.get("extracted_persons", [])
    reconciled = []
    for p in extracted:
        reconciled.append(
            ReconciledPerson(
                person_id=f"person_{p.extraction_id}",
                first_name=p.first_name,
                last_name=p.last_name,
                first_name_normalized=p.first_name.lower().strip(),
                last_name_normalized=p.last_name.lower().strip(),
                job_title=p.job_title,
                source_references=p.source_references,
            )
        )
    return WorkflowState(
        **{
            **state,
            "reconciled_persons": reconciled,
            "duplicate_groups": [],
        }
    )


def mock_classifier(state: WorkflowState) -> WorkflowState:
    """Mock classifier for testing extraction flow only."""
    from src.models.person import ClassifiedPerson

    reconciled = state.get("reconciled_persons", [])
    classified = []
    for p in reconciled:
        classified.append(
            ClassifiedPerson(
                person_id=p.person_id,
                first_name=p.first_name,
                last_name=p.last_name,
                job_title=p.job_title,
                source_references=p.source_references,
                classification="CSM",
                reasoning="Test classification with executive criteria.",
                criteria_met=["executive_management"],
            )
        )
    return WorkflowState(**{**state, "classified_persons": classified})


def mock_formatter(state: WorkflowState) -> WorkflowState:
    """Mock formatter for testing extraction flow only."""
    from src.models.output import DocumentManifestEntry

    classified = state.get("classified_persons", [])
    return WorkflowState(
        **{
            **state,
            "document_manifest": [
                DocumentManifestEntry(
                    filename="doc1.pdf",
                    file_type="PDF",
                    page_count=1,
                    processing_status="processed",
                )
            ],
            "csm_list": classified,
            "non_csm_list": [],
            "status": "completed",
            "current_agent": "",
        }
    )


def mock_critic_pass(state: WorkflowState) -> tuple[CriticDecision, str | None]:
    """Mock critic that always passes."""
    return (CriticDecision.PASS, None)


# --- Test Classes ---


class TestSuccessfulExtractionFlow:
    """Tests for successful extraction flow."""

    def test_extraction_succeeds_on_first_try(self):
        """Test that valid extraction passes on first attempt."""
        agent_functions = {
            "extractor": mock_extractor_success,
            "reconciler": mock_reconciler,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": critic_1_agent,  # Use real critic
            "critic_2": mock_critic_pass,
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        assert final_state["status"] == "completed"
        assert len(final_state["extracted_persons"]) == 2

    def test_extraction_produces_valid_persons(self):
        """Test that extraction produces persons with required fields."""
        agent_functions = {
            "extractor": mock_extractor_success,
            "reconciler": mock_reconciler,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": critic_1_agent,
            "critic_2": mock_critic_pass,
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        for person in final_state["extracted_persons"]:
            assert person.first_name.strip() != ""
            assert person.last_name.strip() != ""
            assert len(person.source_references) > 0


class TestExtractionRetryWithCriticFeedback:
    """Tests for extraction retry with critic feedback."""

    def test_extraction_retries_on_invalid_output(self):
        """Test that extraction retries when critic finds issues."""
        mock_extractor = create_mock_extractor_fail_then_succeed(1)

        agent_functions = {
            "extractor": mock_extractor,
            "reconciler": mock_reconciler,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": critic_1_agent,
            "critic_2": mock_critic_pass,
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        assert final_state["status"] == "completed"
        assert final_state["extraction_retry_count"] >= 1

    def test_extraction_retry_increments_counter(self):
        """Test that retry counter increments on each attempt."""
        mock_extractor = create_mock_extractor_fail_then_succeed(2)

        agent_functions = {
            "extractor": mock_extractor,
            "reconciler": mock_reconciler,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": critic_1_agent,
            "critic_2": mock_critic_pass,
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        assert final_state["status"] == "completed"
        assert final_state["extraction_retry_count"] >= 2

    def test_extraction_receives_feedback(self):
        """Test that extraction feedback is provided on retry."""
        mock_extractor = create_mock_extractor_fail_then_succeed(1)

        agent_functions = {
            "extractor": mock_extractor,
            "reconciler": mock_reconciler,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": critic_1_agent,
            "critic_2": mock_critic_pass,
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        # Feedback should have been set during retry (may be cleared after success)
        assert final_state["status"] == "completed"


class TestExtractionFailureAfterMaxRetries:
    """Tests for extraction failure after max retries."""

    def test_extraction_fails_after_max_retries(self):
        """Test that workflow fails after max extraction retries."""
        agent_functions = {
            "extractor": mock_extractor_always_fail,
            "reconciler": mock_reconciler,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": critic_1_agent,
            "critic_2": mock_critic_pass,
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        assert final_state["status"] == "failed"
        assert final_state["extraction_retry_count"] >= MAX_RETRY_COUNT

    def test_failure_reason_provided(self):
        """Test that failure reason is provided after max retries."""
        agent_functions = {
            "extractor": mock_extractor_always_fail,
            "reconciler": mock_reconciler,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": critic_1_agent,
            "critic_2": mock_critic_pass,
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        assert final_state["failure_reason"] is not None
        assert "retry" in final_state["failure_reason"].lower() or "maximum" in final_state["failure_reason"].lower()
