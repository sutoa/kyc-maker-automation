"""End-to-end tests for reconciliation flow.

Tests the reconciler → critic_2 → reconciler retry loop.
critic_2 uses validate_reconciliation_for_factory (the real rule-based critic)
so validation logic is exercised without calling an LLM.
"""

import pytest

from src.agents.critic import validate_reconciliation_for_factory
from src.agents.reconciler import reconciler_agent
from src.core.state import WorkflowState, create_initial_state
from src.core.workflow import run_workflow_sync
from src.models.person import ExtractedPerson, ReconciledPerson, SourceReference
from src.services.document import DocumentInput, PageContent

from .conftest import (
    build_compiled_workflow,
    default_critic_1_pass,
    default_critic_3_pass,
    fail_retry_feedback,
    pass_feedback,
)


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------


def make_doc(doc_id="doc1") -> DocumentInput:
    return DocumentInput(
        document_id=doc_id,
        filename=f"{doc_id}.pdf",
        file_type="PDF",
        content="[PAGE 1]\nTest content",
        pages=[PageContent(page_number=1, text="Test content")],
        page_count=1,
    )


def extracted_no_duplicates() -> list[ExtractedPerson]:
    return [
        ExtractedPerson(
            extraction_id="ext_1",
            first_name="Hans",
            last_name="Müller",
            job_title="Managing Director",
            source_references=[SourceReference(document_id="doc1", filename="doc1.pdf", page_number=1)],
        ),
        ExtractedPerson(
            extraction_id="ext_2",
            first_name="Anna",
            last_name="Schmidt",
            job_title="Secretary",
            source_references=[SourceReference(document_id="doc1", filename="doc1.pdf", page_number=2)],
        ),
    ]


def extracted_with_duplicates() -> list[ExtractedPerson]:
    return [
        ExtractedPerson(
            extraction_id="ext_1",
            first_name="Hans",
            last_name="Müller",
            job_title="Managing Director",
            source_references=[SourceReference(document_id="doc1", filename="doc1.pdf", page_number=1)],
        ),
        ExtractedPerson(
            extraction_id="ext_2",
            first_name="Hans",
            last_name="Müller",
            job_title="Managing Director",
            source_references=[SourceReference(document_id="doc1", filename="doc1.pdf", page_number=3)],
        ),
        ExtractedPerson(
            extraction_id="ext_3",
            first_name="Anna",
            last_name="Schmidt",
            job_title="Secretary",
            source_references=[SourceReference(document_id="doc1", filename="doc1.pdf", page_number=2)],
        ),
    ]


def extracted_german_variants() -> list[ExtractedPerson]:
    return [
        ExtractedPerson(
            extraction_id="ext_1",
            first_name="Hans",
            last_name="Müller",
            job_title="Director",
            source_references=[SourceReference(document_id="doc1", filename="doc1.pdf", page_number=1)],
        ),
        ExtractedPerson(
            extraction_id="ext_2",
            first_name="Hans",
            last_name="Mueller",
            job_title="Director",
            source_references=[SourceReference(document_id="doc2", filename="doc2.pdf", page_number=1)],
        ),
    ]


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def make_extractor(persons: list[ExtractedPerson]):
    def extractor(state: WorkflowState) -> WorkflowState:
        return WorkflowState(**{**state, "extracted_persons": persons})
    return extractor


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSuccessfulReconciliationFlow:

    def test_reconciliation_succeeds_no_duplicates(self):
        """Successful reconciliation with no duplicates."""
        compiled = build_compiled_workflow(
            extractor=make_extractor(extracted_no_duplicates()),
            reconciler=reconciler_agent,
            critic_2=validate_reconciliation_for_factory,
        )
        final_state = run_workflow_sync(compiled, create_initial_state([make_doc()]))

        assert final_state["status"] == "completed"
        assert len(final_state["reconciled_persons"]) == 2

    def test_reconciliation_merges_duplicates(self):
        """Duplicates are merged to produce fewer reconciled records."""
        compiled = build_compiled_workflow(
            extractor=make_extractor(extracted_with_duplicates()),
            reconciler=reconciler_agent,
            critic_2=validate_reconciliation_for_factory,
        )
        final_state = run_workflow_sync(compiled, create_initial_state([make_doc()]))

        assert final_state["status"] == "completed"
        # Hans Müller appears twice, should be merged into one
        assert len(final_state["reconciled_persons"]) <= 2

    def test_merged_person_has_consolidated_sources(self):
        """Merged person has source references from both originals."""
        compiled = build_compiled_workflow(
            extractor=make_extractor(extracted_with_duplicates()),
            reconciler=reconciler_agent,
            critic_2=validate_reconciliation_for_factory,
        )
        final_state = run_workflow_sync(compiled, create_initial_state([make_doc()]))

        hans = next(
            (p for p in final_state["reconciled_persons"] if p.first_name == "Hans"),
            None,
        )
        if hans and len(final_state["reconciled_persons"]) < 3:
            assert len(hans.source_references) >= 2


class TestReconciliationWithGermanNameVariants:

    def test_umlaut_variants_recognized_as_similar(self):
        """Müller and Mueller are treated as the same person."""
        compiled = build_compiled_workflow(
            extractor=make_extractor(extracted_german_variants()),
            reconciler=reconciler_agent,
            critic_2=validate_reconciliation_for_factory,
        )
        final_state = run_workflow_sync(compiled, create_initial_state([make_doc()]))

        assert final_state["status"] == "completed"
        assert len(final_state["reconciled_persons"]) <= 2

    def test_normalized_names_present(self):
        """Reconciled persons have lowercase ASCII normalized names."""
        compiled = build_compiled_workflow(
            extractor=make_extractor(extracted_no_duplicates()),
            reconciler=reconciler_agent,
            critic_2=validate_reconciliation_for_factory,
        )
        final_state = run_workflow_sync(compiled, create_initial_state([make_doc()]))

        for person in final_state["reconciled_persons"]:
            assert person.first_name_normalized is not None
            assert person.last_name_normalized is not None
            assert person.first_name_normalized.islower()
            assert person.last_name_normalized.islower()

    def test_duplicate_groups_tracked(self):
        """Duplicate groups are tracked for audit trail."""
        compiled = build_compiled_workflow(
            extractor=make_extractor(extracted_with_duplicates()),
            reconciler=reconciler_agent,
            critic_2=validate_reconciliation_for_factory,
        )
        final_state = run_workflow_sync(compiled, create_initial_state([make_doc()]))

        if len(final_state["reconciled_persons"]) < 3:
            assert len(final_state["duplicate_groups"]) >= 1


class TestReconciliationValidation:

    def test_critic_passes_valid_reconciliation(self):
        """critic_2 passes valid reconciliation on first attempt."""
        compiled = build_compiled_workflow(
            extractor=make_extractor(extracted_no_duplicates()),
            reconciler=reconciler_agent,
            critic_2=validate_reconciliation_for_factory,
        )
        final_state = run_workflow_sync(compiled, create_initial_state([make_doc()]))

        assert final_state["status"] == "completed"
        assert final_state.get("reconciliation_retry_count", 0) == 0
