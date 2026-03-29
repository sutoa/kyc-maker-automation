"""End-to-end tests for extraction flow.

Tests the extractor → critic_1 → extractor retry loop using mock agent
functions that follow the factory contract: (state: WorkflowState) -> WorkflowState.

critic_1 is mocked as a rule-based validator so the LLM is never called.
"""

from datetime import datetime
from uuid import uuid4

import pytest

from src.core.state import WorkflowState, create_initial_state
from src.core.workflow import run_workflow_sync
from src.models.enums import CriticDecision
from src.models.person import ExtractedPerson, SourceReference
from src.models.workflow import CriticFeedback
from src.services.document import DocumentInput, PageContent

from .conftest import (
    build_compiled_workflow,
    default_classifier,
    default_critic_2_pass,
    default_critic_3_pass,
    default_formatter,
    default_reconciler,
    fail_max_feedback,
    fail_retry_feedback,
    pass_feedback,
)


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------


def create_test_document(
    doc_id: str = "doc1",
    content: str = "[PAGE 1]\nHans Müller, Geschäftsführer\nAnna Schmidt, Sachbearbeiterin",
) -> DocumentInput:
    return DocumentInput(
        document_id=doc_id,
        filename=f"{doc_id}.pdf",
        file_type="PDF",
        content=content,
        pages=[PageContent(page_number=1, text=content.replace("[PAGE 1]\n", ""))],
        page_count=1,
    )


def valid_extracted_persons() -> list[ExtractedPerson]:
    return [
        ExtractedPerson(
            extraction_id="ext_1",
            first_name="Hans",
            last_name="Müller",
            job_title="Managing Director",
            job_title_original="Geschäftsführer",
            source_references=[
                SourceReference(document_id="doc1", filename="doc1.pdf", page_number=1,
                                extracted_text_snippet="Hans Müller, Geschäftsführer", confidence=0.95)
            ],
        ),
        ExtractedPerson(
            extraction_id="ext_2",
            first_name="Anna",
            last_name="Schmidt",
            job_title="Administrative Clerk",
            job_title_original="Sachbearbeiterin",
            source_references=[
                SourceReference(document_id="doc1", filename="doc1.pdf", page_number=1,
                                extracted_text_snippet="Anna Schmidt, Sachbearbeiterin", confidence=0.90)
            ],
        ),
    ]


def invalid_extracted_persons() -> list[ExtractedPerson]:
    """Persons with whitespace-only first_name — should trigger FAIL_RETRY."""
    return [
        ExtractedPerson(
            extraction_id="ext_1",
            first_name="   ",
            last_name="Müller",
            source_references=[SourceReference(document_id="doc1", filename="doc1.pdf", page_number=1)],
        ),
    ]


# ---------------------------------------------------------------------------
# Mock agent functions
# ---------------------------------------------------------------------------


def make_extractor_succeed(state: WorkflowState) -> WorkflowState:
    return WorkflowState(**{**state, "extracted_persons": valid_extracted_persons()})


def make_extractor_fail(state: WorkflowState) -> WorkflowState:
    return WorkflowState(**{**state, "extracted_persons": invalid_extracted_persons()})


def make_extractor_fail_then_succeed(fail_count: int):
    attempts = {"n": 0}

    def extractor(state: WorkflowState) -> WorkflowState:
        attempts["n"] += 1
        if attempts["n"] <= fail_count:
            return WorkflowState(**{**state, "extracted_persons": invalid_extracted_persons()})
        return WorkflowState(**{**state, "extracted_persons": valid_extracted_persons()})

    return extractor


def make_validating_critic_1(max_retries: int = 4):
    """Rule-based critic_1 mock: validates extracted_persons; returns FAIL_MAX after max_retries."""
    retry_count: list[int] = [0]

    def critic(state: WorkflowState) -> WorkflowState:
        persons = state.get("extracted_persons", [])
        is_valid = persons and all(p.first_name and p.first_name.strip() for p in persons)
        if is_valid:
            return WorkflowState(**{**state, "last_critic_feedback": pass_feedback("critic_1")})
        if retry_count[0] >= max_retries:
            return WorkflowState(**{**state, "last_critic_feedback": fail_max_feedback("critic_1")})
        retry_count[0] += 1
        return WorkflowState(**{
            **state,
            "last_critic_feedback": fail_retry_feedback("critic_1", "Invalid extraction."),
        })

    return critic




# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSuccessfulExtractionFlow:

    def test_extraction_succeeds_on_first_try(self):
        """Valid extraction passes critic_1 on first attempt."""
        compiled = build_compiled_workflow(
            extractor=make_extractor_succeed,
            critic_1=make_validating_critic_1(),
        )
        initial_state = create_initial_state([create_test_document()])
        final_state = run_workflow_sync(compiled, initial_state)

        assert final_state["status"] == "completed"
        assert len(final_state["extracted_persons"]) == 2

    def test_extraction_produces_valid_persons(self):
        """Extracted persons have mandatory fields."""
        compiled = build_compiled_workflow(
            extractor=make_extractor_succeed,
            critic_1=make_validating_critic_1(),
        )
        initial_state = create_initial_state([create_test_document()])
        final_state = run_workflow_sync(compiled, initial_state)

        for person in final_state["extracted_persons"]:
            assert person.first_name.strip() != ""
            assert person.last_name.strip() != ""
            assert len(person.source_references) > 0


class TestExtractionRetryWithCriticFeedback:

    def test_extraction_retries_on_invalid_output(self):
        """Workflow retries when critic_1 finds issues (fails once, then succeeds)."""
        extractor_calls: list[int] = [0]

        def counting_extractor_fail_then_succeed(state: WorkflowState) -> WorkflowState:
            extractor_calls[0] += 1
            if extractor_calls[0] <= 1:
                return WorkflowState(**{**state, "extracted_persons": invalid_extracted_persons()})
            return WorkflowState(**{**state, "extracted_persons": valid_extracted_persons()})

        compiled = build_compiled_workflow(
            extractor=counting_extractor_fail_then_succeed,
            critic_1=make_validating_critic_1(),
        )
        initial_state = create_initial_state([create_test_document()])
        final_state = run_workflow_sync(compiled, initial_state)

        assert final_state["status"] == "completed"
        # Extractor was called at least twice (once with invalid output, once with valid)
        assert extractor_calls[0] >= 2

    def test_extraction_retry_increments_counter(self):
        """Workflow retries multiple times when critic_1 finds issues."""
        extractor_calls: list[int] = [0]

        def counting_extractor_fail_twice(state: WorkflowState) -> WorkflowState:
            extractor_calls[0] += 1
            if extractor_calls[0] <= 2:
                return WorkflowState(**{**state, "extracted_persons": invalid_extracted_persons()})
            return WorkflowState(**{**state, "extracted_persons": valid_extracted_persons()})

        compiled = build_compiled_workflow(
            extractor=counting_extractor_fail_twice,
            critic_1=make_validating_critic_1(),
        )
        initial_state = create_initial_state([create_test_document()])
        final_state = run_workflow_sync(compiled, initial_state)

        assert final_state["status"] == "completed"
        assert extractor_calls[0] >= 3


class TestExtractionFailureAfterMaxRetries:

    def test_extraction_fails_after_max_retries(self):
        """Workflow fails after max extraction retries (critic returns FAIL_MAX)."""
        compiled = build_compiled_workflow(
            extractor=make_extractor_fail,
            critic_1=make_validating_critic_1(max_retries=2),  # fail fast in tests
        )
        initial_state = create_initial_state([create_test_document()])
        final_state = run_workflow_sync(compiled, initial_state)

        assert final_state["status"] == "failed"

    def test_failure_reason_provided(self):
        """Failure reason is set when workflow fails."""
        compiled = build_compiled_workflow(
            extractor=make_extractor_fail,
            critic_1=make_validating_critic_1(max_retries=2),
        )
        initial_state = create_initial_state([create_test_document()])
        final_state = run_workflow_sync(compiled, initial_state)

        assert final_state["failure_reason"] is not None
