"""End-to-end tests for classification flow.

Tests the classifier → critic_3 → classifier retry loop.
critic_3 uses validate_classification_for_factory (the real rule-based critic)
so validation logic is exercised without calling an LLM.

classifier_agent requires an LLM — these tests use a mock classifier that
produces controlled outputs so the flow can be verified without LLM calls.
"""

import pytest

from src.agents.critic import validate_classification_for_factory
from src.core.state import WorkflowState, create_initial_state
from src.core.workflow import run_workflow_sync
from src.models.person import ClassifiedPerson, ExtractedPerson, ReconciledPerson, SourceReference
from src.services.document import DocumentInput, PageContent

from .conftest import (
    build_compiled_workflow,
    default_critic_1_pass,
    default_critic_2_pass,
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


def reconciled_clear_roles() -> list[ReconciledPerson]:
    return [
        ReconciledPerson(
            person_id="person_1",
            first_name="Hans",
            last_name="Müller",
            first_name_normalized="hans",
            last_name_normalized="muller",
            job_title="Managing Director",
            job_title_original="Geschäftsführer",
            source_references=[SourceReference(document_id="doc1", filename="doc1.pdf", page_number=1)],
        ),
        ReconciledPerson(
            person_id="person_2",
            first_name="Anna",
            last_name="Schmidt",
            first_name_normalized="anna",
            last_name_normalized="schmidt",
            job_title="Administrative Clerk",
            job_title_original="Sachbearbeiterin",
            source_references=[SourceReference(document_id="doc1", filename="doc1.pdf", page_number=2)],
        ),
    ]


def reconciled_no_job_title() -> list[ReconciledPerson]:
    return [
        ReconciledPerson(
            person_id="person_1",
            first_name="Hans",
            last_name="Müller",
            first_name_normalized="hans",
            last_name_normalized="muller",
            job_title=None,
            source_references=[SourceReference(document_id="doc1", filename="doc1.pdf", page_number=1)],
        ),
    ]


# ---------------------------------------------------------------------------
# Mock agents
# ---------------------------------------------------------------------------


def make_reconciler(persons: list[ReconciledPerson]):
    def reconciler(state: WorkflowState) -> WorkflowState:
        return WorkflowState(**{**state, "reconciled_persons": persons, "duplicate_groups": []})
    return reconciler


def classifier_csm_for_executive(state: WorkflowState) -> WorkflowState:
    """Mock classifier: executives get CSM with proper reasoning; others NON_CSM."""
    reconciled = state.get("reconciled_persons", [])
    executive_titles = {"managing director", "geschäftsführer", "ceo", "cfo", "chairman"}

    classified = []
    for p in reconciled:
        title = (p.job_title or "").lower()
        if any(t in title for t in executive_titles):
            classified.append(ClassifiedPerson(
                person_id=p.person_id,
                first_name=p.first_name,
                last_name=p.last_name,
                job_title=p.job_title,
                source_references=p.source_references,
                classification="CSM",
                reasoning="Criterion 1: Executive Management Role — Managing Director has decision-making authority.",
                criteria_met=["Criterion 1: Executive Management Role"],
                confidence=0.95,
            ))
        else:
            classified.append(ClassifiedPerson(
                person_id=p.person_id,
                first_name=p.first_name,
                last_name=p.last_name,
                job_title=p.job_title,
                source_references=p.source_references,
                classification="NON_CSM",
                reasoning="Criterion 1-5 not met — Administrative/unknown role with no executive authority.",
                criteria_not_met=["Criterion 1-5: No CSM criteria met"],
                confidence=0.95,
            ))
    return WorkflowState(**{**state, "classified_persons": classified})


def classifier_missing_reasoning(state: WorkflowState) -> WorkflowState:
    """Mock classifier that produces empty reasoning — should trigger FAIL_RETRY."""
    reconciled = state.get("reconciled_persons", [])
    classified = [
        ClassifiedPerson(
            person_id=p.person_id,
            first_name=p.first_name,
            last_name=p.last_name,
            job_title=p.job_title,
            source_references=p.source_references,
            classification="CSM",
            reasoning="",  # Empty reasoning — critic_3 will reject this
            criteria_met=[],
        )
        for p in reconciled
    ]
    return WorkflowState(**{**state, "classified_persons": classified})


def make_formatter(state: WorkflowState) -> WorkflowState:
    from src.models.output import DocumentManifestEntry
    classified = state.get("classified_persons", [])
    csm_list = [p for p in classified if p.classification == "CSM"]
    non_csm_list = [p for p in classified if p.classification == "NON_CSM"]
    return WorkflowState(**{
        **state,
        "document_manifest": [DocumentManifestEntry(filename="doc1.pdf", file_type="PDF", page_count=1, processing_status="processed")],
        "csm_list": csm_list,
        "non_csm_list": non_csm_list,
        "status": "completed",
        "current_agent": "",
    })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSuccessfulClassificationFlow:

    def test_classification_succeeds_with_clear_roles(self):
        """Successful classification produces completed workflow."""
        compiled = build_compiled_workflow(
            reconciler=make_reconciler(reconciled_clear_roles()),
            classifier=classifier_csm_for_executive,
            critic_3=validate_classification_for_factory,
            formatter=make_formatter,
        )
        final_state = run_workflow_sync(compiled, create_initial_state([make_doc()]))

        assert final_state["status"] == "completed"
        assert len(final_state["classified_persons"]) == 2

    def test_managing_director_classified_as_csm(self):
        """Managing Director (Geschäftsführer) is classified as CSM."""
        compiled = build_compiled_workflow(
            reconciler=make_reconciler(reconciled_clear_roles()),
            classifier=classifier_csm_for_executive,
            critic_3=validate_classification_for_factory,
            formatter=make_formatter,
        )
        final_state = run_workflow_sync(compiled, create_initial_state([make_doc()]))

        hans = next((p for p in final_state["classified_persons"] if p.first_name == "Hans"), None)
        assert hans is not None
        assert hans.classification == "CSM"

    def test_clerk_classified_as_non_csm(self):
        """Administrative Clerk is classified as NON_CSM."""
        compiled = build_compiled_workflow(
            reconciler=make_reconciler(reconciled_clear_roles()),
            classifier=classifier_csm_for_executive,
            critic_3=validate_classification_for_factory,
            formatter=make_formatter,
        )
        final_state = run_workflow_sync(compiled, create_initial_state([make_doc()]))

        anna = next((p for p in final_state["classified_persons"] if p.first_name == "Anna"), None)
        assert anna is not None
        assert anna.classification == "NON_CSM"

    def test_classification_has_reasoning(self):
        """All classifications have non-empty reasoning."""
        compiled = build_compiled_workflow(
            reconciler=make_reconciler(reconciled_clear_roles()),
            classifier=classifier_csm_for_executive,
            critic_3=validate_classification_for_factory,
            formatter=make_formatter,
        )
        final_state = run_workflow_sync(compiled, create_initial_state([make_doc()]))

        for person in final_state["classified_persons"]:
            assert person.reasoning is not None
            assert len(person.reasoning.strip()) > 0


class TestClassificationWithInsufficientInfo:

    def test_no_job_title_classified_as_non_csm(self):
        """Person with no job title defaults to NON_CSM."""
        compiled = build_compiled_workflow(
            reconciler=make_reconciler(reconciled_no_job_title()),
            classifier=classifier_csm_for_executive,
            critic_3=validate_classification_for_factory,
            formatter=make_formatter,
        )
        final_state = run_workflow_sync(compiled, create_initial_state([make_doc()]))

        assert final_state["status"] == "completed"
        assert len(final_state["classified_persons"]) == 1
        assert final_state["classified_persons"][0].classification == "NON_CSM"


class TestClassificationValidation:

    def test_critic_passes_valid_classification(self):
        """critic_3 passes valid classification on first attempt."""
        compiled = build_compiled_workflow(
            reconciler=make_reconciler(reconciled_clear_roles()),
            classifier=classifier_csm_for_executive,
            critic_3=validate_classification_for_factory,
            formatter=make_formatter,
        )
        final_state = run_workflow_sync(compiled, create_initial_state([make_doc()]))

        assert final_state["status"] == "completed"
        assert final_state.get("classification_retry_count", 0) == 0

    def test_csm_list_and_non_csm_list_populated(self):
        """CSM and NON_CSM lists are populated in final output."""
        compiled = build_compiled_workflow(
            reconciler=make_reconciler(reconciled_clear_roles()),
            classifier=classifier_csm_for_executive,
            critic_3=validate_classification_for_factory,
            formatter=make_formatter,
        )
        final_state = run_workflow_sync(compiled, create_initial_state([make_doc()]))

        assert len(final_state["csm_list"]) == 1
        assert len(final_state["non_csm_list"]) == 1
        assert final_state["csm_list"][0].first_name == "Hans"
        assert final_state["non_csm_list"][0].first_name == "Anna"
