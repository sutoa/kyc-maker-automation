"""End-to-end tests for classification flow.

Tests the classifier → critic_3 → classifier retry loop.
Also tests handling of insufficient information scenarios.
"""

import pytest

from src.agents.classifier import classifier_agent
from src.agents.critic import critic_3_agent
from src.core.state import WorkflowState, create_initial_state
from src.core.workflow import compile_workflow, run_workflow_sync
from src.models.enums import CriticDecision
from src.models.person import (
    ClassifiedPerson,
    ExtractedPerson,
    ReconciledPerson,
    SourceReference,
)
from src.services.document import DocumentInput, PageContent


# --- Test Fixtures ---


def create_test_document(doc_id: str = "doc1") -> DocumentInput:
    """Create a test document."""
    return DocumentInput(
        document_id=doc_id,
        filename=f"{doc_id}.pdf",
        file_type="PDF",
        content="[PAGE 1]\nTest content",
        pages=[PageContent(page_number=1, text="Test content")],
        page_count=1,
    )


def create_reconciled_persons_with_clear_roles() -> list[ReconciledPerson]:
    """Create reconciled persons with clear CSM/NON_CSM roles."""
    return [
        ReconciledPerson(
            person_id="person_1",
            first_name="Hans",
            last_name="Müller",
            first_name_normalized="hans",
            last_name_normalized="muller",
            job_title="Managing Director",
            job_title_original="Geschäftsführer",
            source_references=[
                SourceReference(
                    document_id="doc1",
                    filename="doc1.pdf",
                    page_number=1,
                )
            ],
        ),
        ReconciledPerson(
            person_id="person_2",
            first_name="Anna",
            last_name="Schmidt",
            first_name_normalized="anna",
            last_name_normalized="schmidt",
            job_title="Administrative Clerk",
            job_title_original="Sachbearbeiterin",
            source_references=[
                SourceReference(
                    document_id="doc1",
                    filename="doc1.pdf",
                    page_number=2,
                )
            ],
        ),
    ]


def create_reconciled_persons_insufficient_info() -> list[ReconciledPerson]:
    """Create reconciled persons with insufficient role information."""
    return [
        ReconciledPerson(
            person_id="person_1",
            first_name="Hans",
            last_name="Müller",
            first_name_normalized="hans",
            last_name_normalized="muller",
            job_title=None,  # No job title
            source_references=[
                SourceReference(
                    document_id="doc1",
                    filename="doc1.pdf",
                    page_number=1,
                )
            ],
        ),
    ]


# --- Mock Agents ---


def mock_extractor(state: WorkflowState) -> WorkflowState:
    """Mock extractor for classification flow tests."""
    return WorkflowState(
        **{
            **state,
            "extracted_persons": [
                ExtractedPerson(
                    extraction_id="ext_1",
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
            ],
        }
    )


def mock_reconciler(persons: list[ReconciledPerson]):
    """Create mock reconciler returning specified persons."""

    def reconciler(state: WorkflowState) -> WorkflowState:
        return WorkflowState(
            **{
                **state,
                "reconciled_persons": persons,
                "duplicate_groups": [],
            }
        )

    return reconciler


def mock_formatter(state: WorkflowState) -> WorkflowState:
    """Mock formatter for testing classification flow only."""
    from src.models.output import DocumentManifestEntry

    classified = state.get("classified_persons", [])
    csm_list = [p for p in classified if p.classification == "CSM"]
    non_csm_list = [p for p in classified if p.classification == "NON_CSM"]

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
            "csm_list": csm_list,
            "non_csm_list": non_csm_list,
            "status": "completed",
            "current_agent": "",
        }
    )


def mock_critic_pass(state: WorkflowState) -> tuple[CriticDecision, str | None]:
    """Mock critic that always passes."""
    return (CriticDecision.PASS, None)


# --- Test Classes ---


class TestSuccessfulClassificationFlow:
    """Tests for successful classification flow."""

    def test_classification_succeeds_with_clear_roles(self):
        """Test successful classification with clear CSM/NON_CSM roles."""
        agent_functions = {
            "extractor": mock_extractor,
            "reconciler": mock_reconciler(create_reconciled_persons_with_clear_roles()),
            "classifier": classifier_agent,  # Use real classifier
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": mock_critic_pass,
            "critic_3": critic_3_agent,  # Use real critic
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        assert final_state["status"] == "completed"
        assert len(final_state["classified_persons"]) == 2

    def test_managing_director_classified_as_csm(self):
        """Test that Managing Director is classified as CSM."""
        agent_functions = {
            "extractor": mock_extractor,
            "reconciler": mock_reconciler(create_reconciled_persons_with_clear_roles()),
            "classifier": classifier_agent,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": mock_critic_pass,
            "critic_3": critic_3_agent,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        hans = next(
            (p for p in final_state["classified_persons"] if p.first_name == "Hans"),
            None,
        )
        assert hans is not None
        assert hans.classification == "CSM"

    def test_clerk_classified_as_non_csm(self):
        """Test that Administrative Clerk is classified as NON_CSM."""
        agent_functions = {
            "extractor": mock_extractor,
            "reconciler": mock_reconciler(create_reconciled_persons_with_clear_roles()),
            "classifier": classifier_agent,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": mock_critic_pass,
            "critic_3": critic_3_agent,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        anna = next(
            (p for p in final_state["classified_persons"] if p.first_name == "Anna"),
            None,
        )
        assert anna is not None
        assert anna.classification == "NON_CSM"

    def test_classification_has_reasoning(self):
        """Test that all classifications have reasoning."""
        agent_functions = {
            "extractor": mock_extractor,
            "reconciler": mock_reconciler(create_reconciled_persons_with_clear_roles()),
            "classifier": classifier_agent,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": mock_critic_pass,
            "critic_3": critic_3_agent,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        for person in final_state["classified_persons"]:
            assert person.reasoning is not None
            assert len(person.reasoning.strip()) > 0


class TestClassificationWithInsufficientInfo:
    """Tests for classification with insufficient information."""

    def test_no_job_title_classified_as_non_csm(self):
        """Test that person with no job title is classified as NON_CSM."""
        agent_functions = {
            "extractor": mock_extractor,
            "reconciler": mock_reconciler(create_reconciled_persons_insufficient_info()),
            "classifier": classifier_agent,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": mock_critic_pass,
            "critic_3": critic_3_agent,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        # Should still complete (classify as NON_CSM when uncertain)
        assert final_state["status"] == "completed"
        assert len(final_state["classified_persons"]) == 1
        assert final_state["classified_persons"][0].classification == "NON_CSM"

    def test_insufficient_info_has_reasoning(self):
        """Test that classification with insufficient info has reasoning."""
        agent_functions = {
            "extractor": mock_extractor,
            "reconciler": mock_reconciler(create_reconciled_persons_insufficient_info()),
            "classifier": classifier_agent,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": mock_critic_pass,
            "critic_3": critic_3_agent,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        person = final_state["classified_persons"][0]
        assert person.reasoning is not None
        assert len(person.reasoning.strip()) > 0


class TestClassificationValidation:
    """Tests for classification validation by critic_3."""

    def test_critic_passes_valid_classification(self):
        """Test that critic_3 passes valid classification."""
        agent_functions = {
            "extractor": mock_extractor,
            "reconciler": mock_reconciler(create_reconciled_persons_with_clear_roles()),
            "classifier": classifier_agent,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": mock_critic_pass,
            "critic_3": critic_3_agent,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        assert final_state["status"] == "completed"
        # No classification failures
        assert final_state.get("classification_retry_count", 0) == 0

    def test_csm_list_and_non_csm_list_populated(self):
        """Test that CSM and NON_CSM lists are properly populated."""
        agent_functions = {
            "extractor": mock_extractor,
            "reconciler": mock_reconciler(create_reconciled_persons_with_clear_roles()),
            "classifier": classifier_agent,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": mock_critic_pass,
            "critic_3": critic_3_agent,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        assert len(final_state["csm_list"]) == 1
        assert len(final_state["non_csm_list"]) == 1
        assert final_state["csm_list"][0].first_name == "Hans"
        assert final_state["non_csm_list"][0].first_name == "Anna"
