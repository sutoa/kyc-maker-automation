"""Contract tests for Critic 1 (Extraction Validator).

These tests verify that critic_1:
- Passes when all mandatory fields are present
- Returns fail_retry when fields are missing
- Returns fail_max after 4 retries
"""

import pytest

from src.agents.critic import (
    Critic1Input,
    Critic1Output,
    critic_1_agent,
    validate_extraction,
)
from src.core.state import MAX_RETRY_COUNT, WorkflowState, create_initial_state
from src.models.enums import CriticDecision
from src.models.person import ExtractedPerson
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


def create_valid_person(suffix: str = "") -> ExtractedPerson:
    """Create a valid extracted person with all mandatory fields."""
    return ExtractedPerson(
        first_name="Hans",
        last_name=f"Müller{suffix}",
        job_title="Managing Director",
        doc_name="doc1.pdf",
        page_number=1,
    )


def create_person_missing_source() -> ExtractedPerson:
    """Create a person missing source references (invalid)."""
    # We need to bypass Pydantic validation for testing
    # So we'll test the validation function directly
    return None  # Placeholder - we'll use dict in tests


# --- Contract Tests ---


class TestCritic1InputContract:
    """Tests for Critic1Input contract."""

    def test_valid_input(self):
        """Test valid input with extracted persons."""
        person = create_valid_person()
        input_data = Critic1Input(
            extracted_persons=[person],
            retry_count=0,
        )

        assert len(input_data.extracted_persons) == 1
        assert input_data.retry_count == 0

    def test_input_with_multiple_persons(self):
        """Test input with multiple persons."""
        persons = [create_valid_person("1"), create_valid_person("2")]
        input_data = Critic1Input(
            extracted_persons=persons,
            retry_count=1,
        )

        assert len(input_data.extracted_persons) == 2


class TestCritic1OutputContract:
    """Tests for Critic1Output contract."""

    def test_pass_decision_output(self):
        """Test output with pass decision."""
        output = Critic1Output(
            decision=CriticDecision.PASS,
            issues=[],
            feedback=None,
        )

        assert output.decision == CriticDecision.PASS
        assert output.issues == []

    def test_fail_retry_decision_output(self):
        """Test output with fail_retry decision."""
        output = Critic1Output(
            decision=CriticDecision.FAIL_RETRY,
            issues=[],
            feedback="Please fix extraction issues",
        )

        assert output.decision == CriticDecision.FAIL_RETRY
        assert output.feedback is not None

    def test_fail_max_decision_output(self):
        """Test output with fail_max decision."""
        output = Critic1Output(
            decision=CriticDecision.FAIL_MAX,
            issues=[],
            feedback="Maximum retries exceeded",
        )

        assert output.decision == CriticDecision.FAIL_MAX


class TestPassWhenAllFieldsPresent:
    """Contract test: pass when all fields present."""

    def test_pass_with_valid_person(self):
        """Test that valid person passes validation."""
        person = create_valid_person()
        output = validate_extraction([person], retry_count=0)

        assert output.decision == CriticDecision.PASS

    def test_pass_with_multiple_valid_persons(self):
        """Test that multiple valid persons pass validation."""
        persons = [
            create_valid_person("1"),
            create_valid_person("2"),
            create_valid_person("3"),
        ]
        output = validate_extraction(persons, retry_count=0)

        assert output.decision == CriticDecision.PASS

    def test_pass_with_optional_fields_missing(self):
        """Test that missing optional fields still pass."""
        person = ExtractedPerson(
            first_name="Hans",
            last_name="Müller",
            # job_title, job_title_original are optional
            doc_name="doc1.pdf",
            page_number=1,
        )
        output = validate_extraction([person], retry_count=0)

        assert output.decision == CriticDecision.PASS

    def test_pass_includes_no_error_issues(self):
        """Test that pass decision has no error-severity issues."""
        person = create_valid_person()
        output = validate_extraction([person], retry_count=0)

        error_issues = [i for i in output.issues if i.severity == "error"]
        assert len(error_issues) == 0


class TestFailRetryOnMissingFields:
    """Contract test: fail_retry on missing fields."""

    def test_fail_retry_on_empty_first_name(self):
        """Test fail_retry when first_name is whitespace-only."""
        # Pydantic min_length=1 blocks empty string; whitespace passes Pydantic
        # but our rule-based validator catches it
        person = ExtractedPerson(
            first_name="   ",  # Whitespace only
            last_name="Müller",
            doc_name="doc1.pdf",
            page_number=1,
        )
        output = validate_extraction([person], retry_count=0)

        assert output.decision == CriticDecision.FAIL_RETRY
        assert any(i.issue_type == "missing_first_name" for i in output.issues)

    def test_fail_retry_on_empty_last_name(self):
        """Test fail_retry when last_name is whitespace-only."""
        person = ExtractedPerson(
            first_name="Hans",
            last_name="   ",  # Whitespace only
            doc_name="doc1.pdf",
            page_number=1,
        )
        output = validate_extraction([person], retry_count=0)

        assert output.decision == CriticDecision.FAIL_RETRY
        assert any(i.issue_type == "missing_last_name" for i in output.issues)

    def test_fail_retry_provides_feedback(self):
        """Test that fail_retry provides actionable feedback."""
        person = ExtractedPerson(
            first_name="   ",
            last_name="Müller",
            doc_name="doc1.pdf",
            page_number=1,
        )
        output = validate_extraction([person], retry_count=0)

        assert output.decision == CriticDecision.FAIL_RETRY
        assert output.feedback is not None
        assert len(output.feedback) > 0

    def test_fail_retry_when_retries_available(self):
        """Test that fail_retry is returned when retries are available."""
        person = ExtractedPerson(
            first_name="   ",
            last_name="Müller",
            doc_name="doc1.pdf",
            page_number=1,
        )

        # Test at various retry counts below max
        for retry_count in range(MAX_RETRY_COUNT):
            output = validate_extraction([person], retry_count=retry_count)
            assert output.decision == CriticDecision.FAIL_RETRY


class TestFailMaxAfterFourRetries:
    """Contract test: fail_max after 4 retries."""

    def test_fail_max_at_max_retries(self):
        """Test that fail_max is returned at max retry count."""
        person = ExtractedPerson(
            first_name="   ",  # Invalid
            last_name="Müller",
            doc_name="doc1.pdf",
            page_number=1,
        )
        output = validate_extraction([person], retry_count=MAX_RETRY_COUNT)

        assert output.decision == CriticDecision.FAIL_MAX

    def test_fail_max_above_max_retries(self):
        """Test that fail_max is returned above max retry count."""
        person = ExtractedPerson(
            first_name="   ",
            last_name="Müller",
            doc_name="doc1.pdf",
            page_number=1,
        )
        output = validate_extraction([person], retry_count=MAX_RETRY_COUNT + 1)

        assert output.decision == CriticDecision.FAIL_MAX

    def test_max_retry_count_is_four(self):
        """Test that max retry count is 4 as per spec."""
        assert MAX_RETRY_COUNT == 4


class TestCritic1AgentFunction:
    """Tests for critic_1_agent function."""

    def test_agent_returns_pass_for_valid_extraction(self):
        """Test agent returns pass for valid extraction."""
        doc = create_test_document()
        state = create_initial_state([doc])
        state = WorkflowState(
            **{
                **state,
                "extracted_persons": [create_valid_person()],
            }
        )

        decision, feedback = critic_1_agent(state)

        assert decision == CriticDecision.PASS
        assert feedback is None

    def test_agent_returns_fail_retry_for_empty_extraction(self):
        """Test agent returns fail_retry when no persons extracted."""
        doc = create_test_document()
        state = create_initial_state([doc])
        # extracted_persons is empty

        decision, feedback = critic_1_agent(state)

        assert decision == CriticDecision.FAIL_RETRY
        assert feedback is not None

    def test_agent_returns_fail_max_when_retries_exceeded(self):
        """Test agent returns fail_max when max retries exceeded."""
        doc = create_test_document()
        state = create_initial_state([doc])
        state = WorkflowState(
            **{
                **state,
                "extracted_persons": [],
                "extraction_retry_count": MAX_RETRY_COUNT,
            }
        )

        decision, feedback = critic_1_agent(state)

        assert decision == CriticDecision.FAIL_MAX
