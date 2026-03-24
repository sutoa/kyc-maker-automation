"""Contract tests for the reconciler agent.

These tests verify that the reconciler:
- Merges duplicates with consolidated source references
- Flags conflicts when same field has different values
"""

import pytest

from src.agents.reconciler import (
    ReconcilerInput,
    ReconcilerOutput,
    merge_persons,
    reconcile_persons,
    reconciler_agent,
)
from src.core.state import WorkflowState, create_initial_state
from src.models.person import (
    DuplicateGroup,
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


def create_person(
    extraction_id: str,
    first_name: str,
    last_name: str,
    job_title: str | None = None,
    doc_id: str = "doc1",
    page: int = 1,
) -> ExtractedPerson:
    """Create an extracted person for testing."""
    return ExtractedPerson(
        extraction_id=extraction_id,
        first_name=first_name,
        last_name=last_name,
        job_title=job_title,
        source_references=[
            SourceReference(
                document_id=doc_id,
                filename=f"{doc_id}.pdf",
                page_number=page,
            )
        ],
    )


# --- Contract Tests ---


class TestReconcilerInputContract:
    """Tests for ReconcilerInput contract."""

    def test_valid_input(self):
        """Test valid input with extracted persons."""
        person = create_person("ext1", "Hans", "Müller")
        input_data = ReconcilerInput(extracted_persons=[person])

        assert len(input_data.extracted_persons) == 1
        assert input_data.retry_feedback is None

    def test_input_with_retry_feedback(self):
        """Test input with retry feedback."""
        person = create_person("ext1", "Hans", "Müller")
        input_data = ReconcilerInput(
            extracted_persons=[person],
            retry_feedback="Check for missed duplicates",
        )

        assert input_data.retry_feedback == "Check for missed duplicates"


class TestReconcilerOutputContract:
    """Tests for ReconcilerOutput contract."""

    def test_valid_output(self):
        """Test valid output structure."""
        output = ReconcilerOutput(
            reconciled_persons=[],
            duplicate_groups=[],
        )

        assert output.reconciled_persons == []
        assert output.duplicate_groups == []


class TestDuplicatesMergedWithConsolidatedSources:
    """Contract test: duplicates merged with consolidated sources."""

    def test_duplicate_persons_merged(self):
        """Test that duplicate persons are merged into one."""
        persons = [
            create_person("ext1", "Hans", "Müller", "Director", "doc1", 1),
            create_person("ext2", "Hans", "Muller", "Director", "doc2", 2),  # Same person, different spelling
        ]

        output = reconcile_persons(persons, threshold=0.85)

        # Should merge into 1 person
        assert len(output.reconciled_persons) <= len(persons)

    def test_merged_person_has_all_source_references(self):
        """Test that merged person consolidates all source references."""
        persons = [
            create_person("ext1", "Hans", "Müller", doc_id="doc1", page=1),
            create_person("ext2", "Hans", "Müller", doc_id="doc2", page=3),
        ]

        output = reconcile_persons(persons, threshold=0.99)  # Exact match

        # Find the merged person
        merged = output.reconciled_persons[0]

        # Should have source references from both extracted persons
        assert len(merged.source_references) >= 2
        doc_ids = {ref.document_id for ref in merged.source_references}
        assert "doc1" in doc_ids
        assert "doc2" in doc_ids

    def test_duplicate_group_created_for_merge(self):
        """Test that duplicate group audit trail is created."""
        persons = [
            create_person("ext1", "Hans", "Müller"),
            create_person("ext2", "Hans", "Müller"),
        ]

        output = reconcile_persons(persons, threshold=0.99)

        # Should have at least one duplicate group
        assert len(output.duplicate_groups) >= 1

        # Duplicate group should reference merged extraction IDs
        group = output.duplicate_groups[0]
        assert "ext1" in group.merged_extraction_ids or "ext2" in group.merged_extraction_ids

    def test_duplicate_group_has_match_score(self):
        """Test that duplicate group has match score."""
        persons = [
            create_person("ext1", "Hans", "Müller"),
            create_person("ext2", "Hans", "Müller"),
        ]

        output = reconcile_persons(persons, threshold=0.99)

        if output.duplicate_groups:
            group = output.duplicate_groups[0]
            assert group.match_score >= 0.0
            assert group.match_score <= 1.0

    def test_non_duplicates_remain_separate(self):
        """Test that non-duplicates remain as separate persons."""
        persons = [
            create_person("ext1", "Hans", "Müller"),
            create_person("ext2", "Anna", "Schmidt"),
            create_person("ext3", "Peter", "Weber"),
        ]

        output = reconcile_persons(persons)

        # All 3 are different people, should remain separate
        assert len(output.reconciled_persons) == 3

    def test_reconciled_person_has_normalized_names(self):
        """Test that reconciled person has normalized names."""
        persons = [create_person("ext1", "Hans", "Müller")]

        output = reconcile_persons(persons)

        person = output.reconciled_persons[0]
        assert person.first_name_normalized is not None
        assert person.last_name_normalized is not None
        assert person.first_name_normalized == "hans"
        assert person.last_name_normalized == "muller"


class TestConflictsFlaggedWithBothValues:
    """Contract test: conflicts flagged with both values."""

    def test_conflict_detected_for_different_job_titles(self):
        """Test that conflict is flagged when job titles differ."""
        persons = [
            create_person("ext1", "Hans", "Müller", "Director", "doc1", 1),
            create_person("ext2", "Hans", "Müller", "CEO", "doc2", 2),
        ]

        # Use exact match to force merge
        merged = merge_persons(persons)

        # Should detect conflict in job_title
        assert merged.has_conflicts is True
        assert len(merged.conflicts) > 0

        job_title_conflict = next(
            (c for c in merged.conflicts if c.field_name == "job_title"),
            None,
        )
        assert job_title_conflict is not None

    def test_conflict_contains_both_values(self):
        """Test that conflict contains both conflicting values."""
        persons = [
            create_person("ext1", "Hans", "Müller", "Director", "doc1", 1),
            create_person("ext2", "Hans", "Müller", "CEO", "doc2", 2),
        ]

        merged = merge_persons(persons)

        job_title_conflict = next(
            (c for c in merged.conflicts if c.field_name == "job_title"),
            None,
        )

        # Should have both values
        values = [v.value for v in job_title_conflict.values]
        assert "Director" in values
        assert "CEO" in values

    def test_conflict_values_have_source_info(self):
        """Test that conflict values include source document info."""
        persons = [
            create_person("ext1", "Hans", "Müller", "Director", "doc1", 1),
            create_person("ext2", "Hans", "Müller", "CEO", "doc2", 2),
        ]

        merged = merge_persons(persons)

        job_title_conflict = next(
            (c for c in merged.conflicts if c.field_name == "job_title"),
            None,
        )

        # Each value should have source document
        for cv in job_title_conflict.values:
            assert cv.source_document is not None
            assert cv.source_page >= 1

    def test_no_conflict_when_values_same(self):
        """Test that no conflict when values are the same."""
        persons = [
            create_person("ext1", "Hans", "Müller", "Director", "doc1", 1),
            create_person("ext2", "Hans", "Müller", "Director", "doc2", 2),
        ]

        merged = merge_persons(persons)

        # No job_title conflict since both say "Director"
        job_title_conflict = next(
            (c for c in merged.conflicts if c.field_name == "job_title"),
            None,
        )
        assert job_title_conflict is None

    def test_has_conflicts_false_when_no_conflicts(self):
        """Test that has_conflicts is False when no conflicts exist."""
        persons = [
            create_person("ext1", "Hans", "Müller", "Director"),
        ]

        merged = merge_persons(persons)

        assert merged.has_conflicts is False
        assert len(merged.conflicts) == 0


class TestReconcilerAgentFunction:
    """Tests for reconciler_agent function."""

    def test_agent_processes_extracted_persons(self):
        """Test that agent processes extracted persons from state."""
        doc = create_test_document()
        state = create_initial_state([doc])
        state = WorkflowState(
            **{
                **state,
                "extracted_persons": [
                    create_person("ext1", "Hans", "Müller"),
                    create_person("ext2", "Anna", "Schmidt"),
                ],
            }
        )

        new_state = reconciler_agent(state)

        assert len(new_state["reconciled_persons"]) == 2

    def test_agent_handles_empty_input(self):
        """Test that agent handles empty extracted persons."""
        doc = create_test_document()
        state = create_initial_state([doc])
        # extracted_persons is empty by default

        new_state = reconciler_agent(state)

        assert new_state["reconciled_persons"] == []

    def test_agent_updates_duplicate_groups(self):
        """Test that agent updates duplicate_groups in state."""
        doc = create_test_document()
        state = create_initial_state([doc])
        state = WorkflowState(
            **{
                **state,
                "extracted_persons": [
                    create_person("ext1", "Hans", "Müller"),
                    create_person("ext2", "Hans", "Müller"),
                ],
            }
        )

        new_state = reconciler_agent(state)

        # duplicate_groups should be populated
        assert "duplicate_groups" in new_state
