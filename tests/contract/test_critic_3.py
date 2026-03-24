"""Contract tests for Critic 3 (Classification Validator).

These tests verify that critic_3:
- Passes when classification has valid reasoning
- Returns fail_retry when reasoning is missing/weak
"""

import pytest

from src.agents.critic import (
    Critic3Input,
    Critic3Output,
    critic_3_agent,
    validate_classification,
)
from src.core.state import MAX_RETRY_COUNT, WorkflowState, create_initial_state
from src.models.enums import CriticDecision
from src.models.person import ClassifiedPerson, EvidenceReference, SourceReference
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


def create_valid_classified_person(
    person_id: str = "person1",
    classification: str = "CSM",
) -> ClassifiedPerson:
    """Create a valid classified person."""
    return ClassifiedPerson(
        person_id=person_id,
        first_name="Hans",
        last_name="Müller",
        first_name_normalized="hans",
        last_name_normalized="muller",
        job_title="Managing Director",
        classification=classification,
        reasoning="Classified as CSM based on Criterion 1: Executive Management Role. "
        "The person holds a Managing Director position which grants significant control.",
        criteria_met=["executive_management"] if classification == "CSM" else [],
        supporting_evidence=[
            EvidenceReference(
                document="doc1.pdf",
                page=1,
                relevant_text="Managing Director",
            )
        ],
        source_references=[
            SourceReference(
                document_id="doc1",
                filename="doc1.pdf",
                page_number=1,
            )
        ],
    )


# --- Contract Tests ---


class TestCritic3InputContract:
    """Tests for Critic3Input contract."""

    def test_valid_input(self):
        """Test valid input."""
        person = create_valid_classified_person()
        input_data = Critic3Input(
            classified_persons=[person],
            retry_count=0,
        )

        assert len(input_data.classified_persons) == 1


class TestCritic3OutputContract:
    """Tests for Critic3Output contract."""

    def test_pass_decision_output(self):
        """Test output with pass decision."""
        output = Critic3Output(
            decision=CriticDecision.PASS,
            issues=[],
        )

        assert output.decision == CriticDecision.PASS


class TestPassWhenClassificationHasValidReasoning:
    """Contract test: pass when classification has valid reasoning."""

    def test_pass_with_valid_classification(self):
        """Test pass when classification has valid reasoning."""
        person = create_valid_classified_person()
        output = validate_classification([person], retry_count=0)

        assert output.decision == CriticDecision.PASS

    def test_pass_with_csm_classification(self):
        """Test pass with CSM classification and proper reasoning."""
        person = create_valid_classified_person(classification="CSM")
        output = validate_classification([person], retry_count=0)

        assert output.decision == CriticDecision.PASS

    def test_pass_with_non_csm_classification(self):
        """Test pass with NON_CSM classification and proper reasoning."""
        person = ClassifiedPerson(
            person_id="p1",
            first_name="Anna",
            last_name="Schmidt",
            first_name_normalized="anna",
            last_name_normalized="schmidt",
            job_title="Secretary",
            classification="NON_CSM",
            reasoning="Not classified as CSM. The person holds a Secretary role "
            "which does not meet executive management criteria.",
            criteria_met=[],
            supporting_evidence=[
                EvidenceReference(
                    document="doc1.pdf",
                    page=1,
                    relevant_text="Secretary",
                )
            ],
            source_references=[
                SourceReference(
                    document_id="doc1",
                    filename="doc1.pdf",
                    page_number=1,
                )
            ],
        )
        output = validate_classification([person], retry_count=0)

        assert output.decision == CriticDecision.PASS

    def test_pass_with_multiple_valid_persons(self):
        """Test pass with multiple valid classifications."""
        persons = [
            create_valid_classified_person("p1", "CSM"),
            create_valid_classified_person("p2", "NON_CSM"),
        ]
        # Fix the NON_CSM person to have proper reasoning
        persons[1] = ClassifiedPerson(
            person_id="p2",
            first_name="Anna",
            last_name="Schmidt",
            first_name_normalized="anna",
            last_name_normalized="schmidt",
            job_title="Clerk",
            classification="NON_CSM",
            reasoning="Not CSM - does not meet executive management criteria.",
            criteria_met=[],
            supporting_evidence=[
                EvidenceReference(
                    document="doc1.pdf",
                    page=1,
                    relevant_text="Clerk",
                )
            ],
            source_references=[
                SourceReference(
                    document_id="doc1",
                    filename="doc1.pdf",
                    page_number=1,
                )
            ],
        )
        output = validate_classification(persons, retry_count=0)

        assert output.decision == CriticDecision.PASS


class TestFailRetryOnMissingOrWeakReasoning:
    """Contract test: fail_retry on missing or weak reasoning."""

    def test_empty_reasoning_rejected_by_pydantic(self):
        """Test that empty reasoning is rejected by Pydantic validation."""
        import pytest

        with pytest.raises(Exception):
            ClassifiedPerson(
                person_id="p1",
                first_name="Hans",
                last_name="Müller",
                classification="CSM",
                reasoning="",  # Empty - rejected by min_length=1
                criteria_met=["executive_management"],
                source_references=[
                    SourceReference(
                        document_id="doc1",
                        filename="doc1.pdf",
                        page_number=1,
                    )
                ],
            )

    def test_fail_retry_on_whitespace_only_reasoning(self):
        """Test fail_retry when reasoning is whitespace only."""
        person = ClassifiedPerson(
            person_id="p1",
            first_name="Hans",
            last_name="Müller",
            classification="CSM",
            reasoning="   ",  # Whitespace only - passes Pydantic but fails critic
            criteria_met=["executive_management"],
            source_references=[
                SourceReference(
                    document_id="doc1",
                    filename="doc1.pdf",
                    page_number=1,
                )
            ],
        )
        output = validate_classification([person], retry_count=0)

        assert output.decision == CriticDecision.FAIL_RETRY
        assert any(i.issue_type == "missing_reasoning" for i in output.issues)

    def test_fail_retry_provides_feedback(self):
        """Test that fail_retry provides actionable feedback."""
        person = ClassifiedPerson(
            person_id="p1",
            first_name="Hans",
            last_name="Müller",
            classification="CSM",
            reasoning="   ",  # Whitespace only
            criteria_met=["executive_management"],
            source_references=[
                SourceReference(
                    document_id="doc1",
                    filename="doc1.pdf",
                    page_number=1,
                )
            ],
        )
        output = validate_classification([person], retry_count=0)

        assert output.decision == CriticDecision.FAIL_RETRY
        assert output.feedback is not None
        assert len(output.feedback) > 0

    def test_csm_without_criteria_met_fails(self):
        """Test that CSM classification without criteria_met fails."""
        person = ClassifiedPerson(
            person_id="p1",
            first_name="Hans",
            last_name="Müller",
            job_title="Director",
            classification="CSM",
            reasoning="Classified as CSM based on executive management role.",
            criteria_met=[],  # Empty - inconsistent with CSM
            source_references=[
                SourceReference(
                    document_id="doc1",
                    filename="doc1.pdf",
                    page_number=1,
                )
            ],
        )
        output = validate_classification([person], retry_count=0)

        assert output.decision == CriticDecision.FAIL_RETRY
        assert any(
            i.issue_type == "inconsistent_classification" for i in output.issues
        )


class TestFailMaxAfterMaxRetries:
    """Contract test: fail_max after max retries."""

    def test_fail_max_at_max_retries(self):
        """Test that fail_max is returned at max retry count."""
        person = ClassifiedPerson(
            person_id="p1",
            first_name="Hans",
            last_name="Müller",
            classification="CSM",
            reasoning="   ",  # Invalid - whitespace only
            criteria_met=["executive_management"],
            source_references=[
                SourceReference(
                    document_id="doc1",
                    filename="doc1.pdf",
                    page_number=1,
                )
            ],
        )
        output = validate_classification([person], retry_count=MAX_RETRY_COUNT)

        assert output.decision == CriticDecision.FAIL_MAX


class TestCritic3AgentFunction:
    """Tests for critic_3_agent function."""

    def test_agent_returns_pass_for_valid_classification(self):
        """Test agent returns pass for valid classification."""
        doc = create_test_document()
        state = create_initial_state([doc])
        state = WorkflowState(
            **{
                **state,
                "classified_persons": [create_valid_classified_person()],
            }
        )

        decision, feedback = critic_3_agent(state)

        assert decision == CriticDecision.PASS

    def test_agent_returns_fail_retry_for_empty_classification(self):
        """Test agent returns fail_retry when no persons classified."""
        doc = create_test_document()
        state = create_initial_state([doc])
        # classified_persons is empty

        decision, feedback = critic_3_agent(state)

        assert decision == CriticDecision.FAIL_RETRY
        assert feedback is not None

    def test_agent_returns_fail_max_when_retries_exceeded(self):
        """Test agent returns fail_max when max retries exceeded."""
        doc = create_test_document()
        state = create_initial_state([doc])
        state = WorkflowState(
            **{
                **state,
                "classified_persons": [],
                "classification_retry_count": MAX_RETRY_COUNT,
            }
        )

        decision, feedback = critic_3_agent(state)

        assert decision == CriticDecision.FAIL_MAX
