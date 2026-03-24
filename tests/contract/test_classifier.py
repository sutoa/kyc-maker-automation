"""Contract tests for the classifier agent.

These tests verify that the classifier:
- Provides CSM classification with valid reasoning
- Provides NON_CSM classification with valid reasoning
- Maps German job titles correctly
"""

import pytest

from src.agents.classifier import (
    ClassifierInput,
    ClassifierOutput,
    classify_by_job_title,
    classify_person,
    classify_persons,
    classifier_agent,
)
from src.core.state import WorkflowState, create_initial_state
from src.models.person import ClassifiedPerson, ReconciledPerson, SourceReference
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


def create_reconciled_person(
    person_id: str = "person1",
    first_name: str = "Hans",
    last_name: str = "Müller",
    job_title: str | None = "Managing Director",
    job_title_original: str | None = None,
) -> ReconciledPerson:
    """Create a reconciled person for testing."""
    return ReconciledPerson(
        person_id=person_id,
        first_name=first_name,
        last_name=last_name,
        first_name_normalized=first_name.lower(),
        last_name_normalized=last_name.lower(),
        job_title=job_title,
        job_title_original=job_title_original,
        source_references=[
            SourceReference(
                document_id="doc1",
                filename="doc1.pdf",
                page_number=1,
            )
        ],
    )


# --- Contract Tests ---


class TestClassifierInputContract:
    """Tests for ClassifierInput contract."""

    def test_valid_input(self):
        """Test valid input."""
        person = create_reconciled_person()
        input_data = ClassifierInput(
            reconciled_persons=[person],
            csm_definition="CSM criteria text",
        )

        assert len(input_data.reconciled_persons) == 1


class TestClassifierOutputContract:
    """Tests for ClassifierOutput contract."""

    def test_valid_output(self):
        """Test valid output with classified persons."""
        output = ClassifierOutput(classified_persons=[])

        assert output.classified_persons == []


class TestCSMClassificationWithValidReasoning:
    """Contract test: CSM classification with valid reasoning."""

    def test_geschaeftsfuehrer_classified_as_csm(self):
        """Test that Geschäftsführer is classified as CSM."""
        person = create_reconciled_person(
            job_title="Managing Director",
            job_title_original="Geschäftsführer",
        )

        classified = classify_person(person)

        assert classified.classification == "CSM"

    def test_csm_has_non_empty_reasoning(self):
        """Test that CSM classification has non-empty reasoning."""
        person = create_reconciled_person(job_title="CEO")

        classified = classify_person(person)

        assert classified.classification == "CSM"
        assert classified.reasoning is not None
        assert len(classified.reasoning) > 0

    def test_csm_has_criteria_met(self):
        """Test that CSM classification has criteria_met populated."""
        person = create_reconciled_person(job_title="Managing Director")

        classified = classify_person(person)

        assert classified.classification == "CSM"
        assert len(classified.criteria_met) > 0

    def test_csm_reasoning_mentions_criteria(self):
        """Test that CSM reasoning mentions specific criteria."""
        person = create_reconciled_person(job_title="Managing Director")

        classified = classify_person(person)

        # Reasoning should mention the role or criteria
        reasoning_lower = classified.reasoning.lower()
        assert any(
            kw in reasoning_lower
            for kw in ["criterion", "executive", "management", "director"]
        )

    def test_vorstand_classified_as_csm(self):
        """Test that Vorstand (Board Member) is classified as CSM."""
        person = create_reconciled_person(
            job_title="Board Member",
            job_title_original="Vorstand",
        )

        classified = classify_person(person)

        assert classified.classification == "CSM"


class TestNONCSMClassificationWithValidReasoning:
    """Contract test: NON_CSM classification with valid reasoning."""

    def test_clerk_classified_as_non_csm(self):
        """Test that clerk is classified as NON_CSM."""
        person = create_reconciled_person(job_title="Administrative Clerk")

        classified = classify_person(person)

        assert classified.classification == "NON_CSM"

    def test_non_csm_has_non_empty_reasoning(self):
        """Test that NON_CSM classification has non-empty reasoning."""
        person = create_reconciled_person(job_title="Secretary")

        classified = classify_person(person)

        assert classified.classification == "NON_CSM"
        assert classified.reasoning is not None
        assert len(classified.reasoning) > 0

    def test_no_job_title_classified_as_non_csm(self):
        """Test that missing job title results in NON_CSM."""
        person = create_reconciled_person(job_title=None)

        classified = classify_person(person)

        assert classified.classification == "NON_CSM"

    def test_sachbearbeiter_classified_as_non_csm(self):
        """Test that Sachbearbeiter (Clerk) is classified as NON_CSM."""
        person = create_reconciled_person(
            job_title="Clerk",
            job_title_original="Sachbearbeiter",
        )

        classified = classify_person(person)

        assert classified.classification == "NON_CSM"


class TestGermanJobTitlesMappedCorrectly:
    """Contract test: German job titles mapped correctly."""

    @pytest.mark.parametrize(
        "german_title,expected_classification",
        [
            ("Geschäftsführer", "CSM"),
            ("Geschäftsführerin", "CSM"),
            ("Vorstand", "CSM"),
            ("Vorstandsvorsitzender", "CSM"),
            ("Aufsichtsrat", "CSM"),
            ("Prokurist", "CSM"),
            ("Inhaber", "CSM"),
            ("Komplementär", "CSM"),
            ("Liquidator", "CSM"),
        ],
    )
    def test_csm_german_titles(self, german_title, expected_classification):
        """Test that German CSM titles are classified correctly."""
        classification, reasoning, criteria = classify_by_job_title(german_title)

        assert classification == expected_classification, f"{german_title} should be {expected_classification}"

    @pytest.mark.parametrize(
        "german_title,expected_classification",
        [
            ("Sachbearbeiter", "NON_CSM"),
            ("Sachbearbeiterin", "NON_CSM"),
        ],
    )
    def test_non_csm_german_titles(self, german_title, expected_classification):
        """Test that German NON_CSM titles are classified correctly."""
        classification, reasoning, criteria = classify_by_job_title(german_title)

        assert classification == expected_classification

    def test_german_title_original_used_as_fallback(self):
        """Test that job_title_original is used if job_title doesn't classify."""
        person = create_reconciled_person(
            job_title="Unknown Role",  # Not clearly CSM or NON_CSM
            job_title_original="Geschäftsführer",  # CSM role
        )

        classified = classify_person(person)

        # Should use the German title for classification
        assert classified.classification == "CSM"


class TestClassifyPersons:
    """Tests for classify_persons function."""

    def test_classify_multiple_persons(self):
        """Test classifying multiple persons."""
        persons = [
            create_reconciled_person("p1", job_title="CEO"),
            create_reconciled_person("p2", job_title="Clerk"),
            create_reconciled_person("p3", job_title="Managing Director"),
        ]

        output = classify_persons(persons)

        assert len(output.classified_persons) == 3

        # Check classifications
        classifications = {p.person_id: p.classification for p in output.classified_persons}
        assert classifications["p1"] == "CSM"
        assert classifications["p2"] == "NON_CSM"
        assert classifications["p3"] == "CSM"

    def test_each_person_gets_exactly_one_classification(self):
        """Test that each person gets exactly one classification."""
        persons = [
            create_reconciled_person("p1"),
            create_reconciled_person("p2"),
        ]

        output = classify_persons(persons)

        for person in output.classified_persons:
            assert person.classification in ("CSM", "NON_CSM")


class TestClassifierAgentFunction:
    """Tests for classifier_agent function."""

    def test_agent_classifies_reconciled_persons(self):
        """Test that agent classifies reconciled persons from state."""
        doc = create_test_document()
        state = create_initial_state([doc])
        state = WorkflowState(
            **{
                **state,
                "reconciled_persons": [
                    create_reconciled_person("p1", job_title="CEO"),
                    create_reconciled_person("p2", job_title="Clerk"),
                ],
            }
        )

        new_state = classifier_agent(state)

        assert len(new_state["classified_persons"]) == 2

    def test_agent_handles_empty_input(self):
        """Test that agent handles empty reconciled persons."""
        doc = create_test_document()
        state = create_initial_state([doc])
        # reconciled_persons is empty

        new_state = classifier_agent(state)

        assert new_state["classified_persons"] == []
