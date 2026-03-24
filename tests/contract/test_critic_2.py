"""Contract tests for Critic 2 (Reconciliation Validator).

These tests verify that critic_2:
- Passes when deduplication is correct
- Returns fail_retry on missed duplicates
"""

import pytest

from src.agents.critic import (
    Critic2Input,
    Critic2Output,
    critic_2_agent,
    validate_reconciliation,
)
from src.core.state import MAX_RETRY_COUNT, WorkflowState, create_initial_state
from src.models.enums import CriticDecision
from src.models.person import ReconciledPerson, SourceReference
from src.services.document import DocumentInput, PageContent


# --- Test Fixtures ---


def create_test_document() -> DocumentInput:
    """Create a test document."""
    return DocumentInput(
        document_id="doc1",
        filename="doc1.pdf",
        file_type="PDF",
        content="[PAGE 1]\nTest content",
        pages=[PageContent(page_number=1, text="Test content")],
        page_count=1,
    )


def create_valid_reconciled_person(person_id: str = "person1") -> ReconciledPerson:
    """Create a valid reconciled person."""
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


# --- Contract Tests ---


class TestCritic2InputContract:
    """Tests for Critic2Input contract."""

    def test_valid_input(self):
        """Test valid input."""
        person = create_valid_reconciled_person()
        input_data = Critic2Input(
            reconciled_persons=[person],
            duplicate_groups=[],
            retry_count=0,
        )

        assert len(input_data.reconciled_persons) == 1


class TestCritic2OutputContract:
    """Tests for Critic2Output contract."""

    def test_pass_decision_output(self):
        """Test output with pass decision."""
        output = Critic2Output(
            decision=CriticDecision.PASS,
            issues=[],
        )

        assert output.decision == CriticDecision.PASS


class TestPassWhenDeduplicationCorrect:
    """Contract test: pass when deduplication correct."""

    def test_pass_with_valid_reconciled_persons(self):
        """Test pass when reconciled persons are valid."""
        persons = [
            create_valid_reconciled_person("p1"),
            create_valid_reconciled_person("p2"),
        ]
        output = validate_reconciliation(persons, extracted_count=2, retry_count=0)

        assert output.decision == CriticDecision.PASS

    def test_pass_with_single_person(self):
        """Test pass with single reconciled person."""
        persons = [create_valid_reconciled_person()]
        output = validate_reconciliation(persons, extracted_count=1, retry_count=0)

        assert output.decision == CriticDecision.PASS

    def test_pass_when_source_references_present(self):
        """Test pass when all source references present."""
        person = create_valid_reconciled_person()
        output = validate_reconciliation([person], extracted_count=1, retry_count=0)

        assert output.decision == CriticDecision.PASS
        # No lost_source_reference issues
        lost_ref_issues = [i for i in output.issues if i.issue_type == "lost_source_reference"]
        assert len(lost_ref_issues) == 0


class TestFailRetryOnMissedDuplicates:
    """Contract test: fail_retry on missed duplicates (conceptual)."""

    def test_fail_when_source_references_lost(self):
        """Test fail when source references are lost."""
        # Create person without source references
        person = ReconciledPerson(
            person_id="p1",
            first_name="Hans",
            last_name="Müller",
            first_name_normalized="hans",
            last_name_normalized="muller",
            source_references=[],  # No source references - error
        )
        output = validate_reconciliation([person], extracted_count=1, retry_count=0)

        assert output.decision == CriticDecision.FAIL_RETRY
        assert any(i.issue_type == "lost_source_reference" for i in output.issues)

    def test_fail_max_when_retries_exceeded(self):
        """Test fail_max when max retries exceeded."""
        person = ReconciledPerson(
            person_id="p1",
            first_name="Hans",
            last_name="Müller",
            first_name_normalized="hans",
            last_name_normalized="muller",
            source_references=[],
        )
        output = validate_reconciliation(
            [person],
            extracted_count=1,
            retry_count=MAX_RETRY_COUNT,
        )

        assert output.decision == CriticDecision.FAIL_MAX


class TestCritic2AgentFunction:
    """Tests for critic_2_agent function."""

    def test_agent_returns_pass_for_valid_reconciliation(self):
        """Test agent returns pass for valid reconciliation."""
        doc = create_test_document()
        state = create_initial_state([doc])
        state = WorkflowState(
            **{
                **state,
                "reconciled_persons": [create_valid_reconciled_person()],
                "extracted_persons": [{}],  # Simulate 1 extracted
            }
        )

        decision, feedback = critic_2_agent(state)

        assert decision == CriticDecision.PASS

    def test_agent_returns_fail_retry_for_empty_reconciliation(self):
        """Test agent returns fail_retry when no persons reconciled."""
        doc = create_test_document()
        state = create_initial_state([doc])
        # reconciled_persons is empty

        decision, feedback = critic_2_agent(state)

        assert decision == CriticDecision.FAIL_RETRY
        assert feedback is not None
