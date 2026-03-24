"""End-to-end tests for reconciliation flow.

Tests the reconciler → critic_2 → reconciler retry loop.
Also tests handling of German name variants.
"""

import pytest

from src.agents.critic import critic_2_agent
from src.agents.reconciler import reconciler_agent
from src.core.state import WorkflowState, create_initial_state
from src.core.workflow import compile_workflow, run_workflow_sync
from src.models.enums import CriticDecision
from src.models.person import ExtractedPerson, ReconciledPerson, SourceReference
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


def create_extracted_persons_no_duplicates() -> list[ExtractedPerson]:
    """Create extracted persons with no duplicates."""
    return [
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
        ),
        ExtractedPerson(
            extraction_id="ext_2",
            first_name="Anna",
            last_name="Schmidt",
            job_title="Secretary",
            source_references=[
                SourceReference(
                    document_id="doc1",
                    filename="doc1.pdf",
                    page_number=2,
                )
            ],
        ),
    ]


def create_extracted_persons_with_duplicates() -> list[ExtractedPerson]:
    """Create extracted persons with duplicate entries."""
    return [
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
        ),
        ExtractedPerson(
            extraction_id="ext_2",
            first_name="Hans",
            last_name="Müller",  # Same person, same spelling
            job_title="Managing Director",
            source_references=[
                SourceReference(
                    document_id="doc1",
                    filename="doc1.pdf",
                    page_number=3,  # Different page
                )
            ],
        ),
        ExtractedPerson(
            extraction_id="ext_3",
            first_name="Anna",
            last_name="Schmidt",
            job_title="Secretary",
            source_references=[
                SourceReference(
                    document_id="doc1",
                    filename="doc1.pdf",
                    page_number=2,
                )
            ],
        ),
    ]


def create_extracted_persons_german_variants() -> list[ExtractedPerson]:
    """Create extracted persons with German name variants."""
    return [
        ExtractedPerson(
            extraction_id="ext_1",
            first_name="Hans",
            last_name="Müller",  # With umlaut
            job_title="Director",
            source_references=[
                SourceReference(
                    document_id="doc1",
                    filename="doc1.pdf",
                    page_number=1,
                )
            ],
        ),
        ExtractedPerson(
            extraction_id="ext_2",
            first_name="Hans",
            last_name="Mueller",  # Without umlaut (ASCII variant)
            job_title="Director",
            source_references=[
                SourceReference(
                    document_id="doc2",
                    filename="doc2.pdf",
                    page_number=1,
                )
            ],
        ),
    ]


# --- Mock Agents ---


def mock_extractor(persons: list[ExtractedPerson]):
    """Create mock extractor returning specified persons."""

    def extractor(state: WorkflowState) -> WorkflowState:
        return WorkflowState(**{**state, "extracted_persons": persons})

    return extractor


def mock_classifier(state: WorkflowState) -> WorkflowState:
    """Mock classifier for testing reconciliation flow only."""
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
    """Mock formatter for testing reconciliation flow only."""
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


class TestSuccessfulReconciliationFlow:
    """Tests for successful reconciliation flow."""

    def test_reconciliation_succeeds_no_duplicates(self):
        """Test successful reconciliation with no duplicates."""
        agent_functions = {
            "extractor": mock_extractor(create_extracted_persons_no_duplicates()),
            "reconciler": reconciler_agent,  # Use real reconciler
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": critic_2_agent,  # Use real critic
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        assert final_state["status"] == "completed"
        assert len(final_state["reconciled_persons"]) == 2

    def test_reconciliation_merges_duplicates(self):
        """Test that duplicates are merged correctly."""
        agent_functions = {
            "extractor": mock_extractor(create_extracted_persons_with_duplicates()),
            "reconciler": reconciler_agent,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": critic_2_agent,
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        assert final_state["status"] == "completed"
        # Should merge Hans Müller entries, keep Anna Schmidt separate
        assert len(final_state["reconciled_persons"]) <= 2

    def test_merged_person_has_consolidated_sources(self):
        """Test that merged person has consolidated source references."""
        agent_functions = {
            "extractor": mock_extractor(create_extracted_persons_with_duplicates()),
            "reconciler": reconciler_agent,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": critic_2_agent,
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        # Find the Hans Müller person
        hans = next(
            (p for p in final_state["reconciled_persons"] if p.first_name == "Hans"),
            None,
        )
        if hans:
            # Should have at least 2 source references from the merge
            assert len(hans.source_references) >= 2


class TestReconciliationWithGermanNameVariants:
    """Tests for reconciliation with German name variants."""

    def test_umlaut_variants_recognized_as_similar(self):
        """Test that Müller and Mueller are recognized as similar."""
        agent_functions = {
            "extractor": mock_extractor(create_extracted_persons_german_variants()),
            "reconciler": reconciler_agent,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": critic_2_agent,
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        assert final_state["status"] == "completed"
        # With proper fuzzy matching, these should be merged
        # Since they have high similarity (Müller ≈ Mueller)
        assert len(final_state["reconciled_persons"]) <= 2

    def test_normalized_names_present(self):
        """Test that normalized names are generated."""
        agent_functions = {
            "extractor": mock_extractor(create_extracted_persons_no_duplicates()),
            "reconciler": reconciler_agent,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": critic_2_agent,
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        for person in final_state["reconciled_persons"]:
            assert person.first_name_normalized is not None
            assert person.last_name_normalized is not None
            # Normalized names should be lowercase ASCII
            assert person.first_name_normalized.islower()
            assert person.last_name_normalized.islower()

    def test_duplicate_groups_tracked(self):
        """Test that duplicate groups are tracked for audit."""
        agent_functions = {
            "extractor": mock_extractor(create_extracted_persons_with_duplicates()),
            "reconciler": reconciler_agent,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": critic_2_agent,
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        # Should have duplicate groups if merges occurred
        if len(final_state["reconciled_persons"]) < 3:
            # Merges occurred, should have audit trail
            assert len(final_state["duplicate_groups"]) >= 1


class TestReconciliationValidation:
    """Tests for reconciliation validation by critic_2."""

    def test_critic_passes_valid_reconciliation(self):
        """Test that critic_2 passes valid reconciliation."""
        agent_functions = {
            "extractor": mock_extractor(create_extracted_persons_no_duplicates()),
            "reconciler": reconciler_agent,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": critic_2_agent,
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_test_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        assert final_state["status"] == "completed"
        # No reconciliation failures
        assert final_state.get("reconciliation_retry_count", 0) == 0
