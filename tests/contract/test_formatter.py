"""Contract tests for the formatter agent.

These tests verify that the formatter:
- Generates document manifest with processing status
- Splits persons into mutually exclusive CSM and NON_CSM lists
"""

import pytest

from src.agents.formatter import (
    FormatterInput,
    FormatterOutput,
    create_document_manifest,
    determine_processing_status,
    format_output,
    formatter_agent,
    split_by_classification,
)
from src.core.state import WorkflowState, create_initial_state
from src.models.output import DocumentManifestEntry
from src.models.person import ClassifiedPerson, SourceReference
from src.services.document import DocumentInput, PageContent


# --- Test Fixtures ---


def create_test_document(
    doc_id: str = "doc1",
    content: str = "[PAGE 1]\nTest content",
) -> DocumentInput:
    """Create a test document."""
    return DocumentInput(
        document_id=doc_id,
        filename=f"{doc_id}.pdf",
        file_type="PDF",
        content=content,
        pages=[PageContent(page_number=1, text=content.replace("[PAGE 1]\n", ""))],
        page_count=1,
    )


def create_classified_person(
    person_id: str = "person1",
    classification: str = "CSM",
    doc_id: str = "doc1",
) -> ClassifiedPerson:
    """Create a classified person for testing."""
    return ClassifiedPerson(
        person_id=person_id,
        first_name="Hans",
        last_name="Müller",
        first_name_normalized="hans",
        last_name_normalized="muller",
        job_title="Managing Director",
        classification=classification,
        reasoning=f"Classified as {classification}.",
        criteria_met=["executive_management"] if classification == "CSM" else [],
        source_references=[
            SourceReference(
                document_id=doc_id,
                filename=f"{doc_id}.pdf",
                page_number=1,
            )
        ],
    )


# --- Contract Tests ---


class TestFormatterInputContract:
    """Tests for FormatterInput contract."""

    def test_valid_input(self):
        """Test valid input."""
        doc = create_test_document()
        person = create_classified_person()
        input_data = FormatterInput(
            workflow_id="test-workflow",
            documents=[doc],
            classified_persons=[person],
        )

        assert len(input_data.documents) == 1
        assert len(input_data.classified_persons) == 1


class TestFormatterOutputContract:
    """Tests for FormatterOutput contract."""

    def test_valid_output(self):
        """Test valid output structure."""
        output = FormatterOutput(
            document_manifest=[],
            csm_list=[],
            non_csm_list=[],
        )

        assert output.document_manifest == []
        assert output.csm_list == []
        assert output.non_csm_list == []


class TestDocumentManifestGeneration:
    """Contract test: document manifest generation."""

    def test_manifest_has_all_documents(self):
        """Test that manifest includes all documents."""
        docs = [
            create_test_document("doc1"),
            create_test_document("doc2"),
            create_test_document("doc3"),
        ]
        persons = [create_classified_person("p1", "CSM", "doc1")]

        manifest = create_document_manifest(docs, persons)

        assert len(manifest) == 3
        filenames = {entry.filename for entry in manifest}
        assert "doc1.pdf" in filenames
        assert "doc2.pdf" in filenames
        assert "doc3.pdf" in filenames

    def test_manifest_entry_has_required_fields(self):
        """Test that manifest entry has required fields."""
        doc = create_test_document()
        persons = [create_classified_person()]

        manifest = create_document_manifest([doc], persons)

        entry = manifest[0]
        assert entry.filename == "doc1.pdf"
        assert entry.file_type == "PDF"
        assert entry.page_count == 1
        assert entry.processing_status in ("processed", "failed", "partial")

    def test_referenced_document_status_processed(self):
        """Test that document referenced by person is 'processed'."""
        doc = create_test_document("doc1")
        person = create_classified_person("p1", "CSM", "doc1")

        status = determine_processing_status(doc, [person])

        assert status == "processed"

    def test_document_with_content_but_no_references(self):
        """Test document with content but not referenced by any person."""
        doc = create_test_document("doc1", "[PAGE 1]\nSome content")
        persons = []  # No persons reference this document

        status = determine_processing_status(doc, persons)

        assert status == "processed"  # Still processed since it has content

    def test_empty_document_status_failed(self):
        """Test that empty document is 'failed'."""
        doc = DocumentInput(
            document_id="doc1",
            filename="doc1.pdf",
            file_type="PDF",
            content="",  # Empty content
            pages=[],
            page_count=0,
        )
        persons = []

        status = determine_processing_status(doc, persons)

        assert status == "failed"


class TestCSMNONCSMListSplitting:
    """Contract test: CSM and NON_CSM list splitting."""

    def test_split_separates_csm_and_non_csm(self):
        """Test that split separates persons by classification."""
        persons = [
            create_classified_person("p1", "CSM"),
            create_classified_person("p2", "NON_CSM"),
            create_classified_person("p3", "CSM"),
        ]

        csm_list, non_csm_list = split_by_classification(persons)

        assert len(csm_list) == 2
        assert len(non_csm_list) == 1

        csm_ids = {p.person_id for p in csm_list}
        assert "p1" in csm_ids
        assert "p3" in csm_ids

        non_csm_ids = {p.person_id for p in non_csm_list}
        assert "p2" in non_csm_ids

    def test_lists_are_mutually_exclusive(self):
        """Test that CSM and NON_CSM lists have no overlap."""
        persons = [
            create_classified_person("p1", "CSM"),
            create_classified_person("p2", "NON_CSM"),
            create_classified_person("p3", "CSM"),
            create_classified_person("p4", "NON_CSM"),
        ]

        csm_list, non_csm_list = split_by_classification(persons)

        csm_ids = {p.person_id for p in csm_list}
        non_csm_ids = {p.person_id for p in non_csm_list}

        overlap = csm_ids & non_csm_ids
        assert len(overlap) == 0

    def test_all_persons_in_one_list(self):
        """Test that every person ends up in exactly one list."""
        persons = [
            create_classified_person("p1", "CSM"),
            create_classified_person("p2", "NON_CSM"),
            create_classified_person("p3", "CSM"),
        ]

        csm_list, non_csm_list = split_by_classification(persons)

        all_ids_input = {p.person_id for p in persons}
        all_ids_output = {p.person_id for p in csm_list} | {
            p.person_id for p in non_csm_list
        }

        assert all_ids_input == all_ids_output

    def test_empty_persons_produces_empty_lists(self):
        """Test that empty input produces empty lists."""
        csm_list, non_csm_list = split_by_classification([])

        assert csm_list == []
        assert non_csm_list == []


class TestFormatOutput:
    """Tests for format_output function."""

    def test_format_output_produces_all_components(self):
        """Test that format_output produces manifest and both lists."""
        docs = [create_test_document()]
        persons = [
            create_classified_person("p1", "CSM"),
            create_classified_person("p2", "NON_CSM"),
        ]

        output = format_output(docs, persons)

        assert len(output.document_manifest) == 1
        assert len(output.csm_list) == 1
        assert len(output.non_csm_list) == 1

    def test_format_output_with_multiple_documents(self):
        """Test format_output with multiple documents."""
        docs = [
            create_test_document("doc1"),
            create_test_document("doc2"),
        ]
        persons = [create_classified_person("p1", "CSM", "doc1")]

        output = format_output(docs, persons)

        assert len(output.document_manifest) == 2


class TestFormatterAgentFunction:
    """Tests for formatter_agent function."""

    def test_agent_produces_formatted_output(self):
        """Test that agent produces formatted output in state."""
        doc = create_test_document()
        state = create_initial_state([doc])
        state = WorkflowState(
            **{
                **state,
                "classified_persons": [
                    create_classified_person("p1", "CSM"),
                    create_classified_person("p2", "NON_CSM"),
                ],
            }
        )

        new_state = formatter_agent(state)

        assert "document_manifest" in new_state
        assert "csm_list" in new_state
        assert "non_csm_list" in new_state

    def test_agent_handles_empty_input(self):
        """Test that agent handles empty classified persons."""
        doc = create_test_document()
        state = create_initial_state([doc])
        # classified_persons is empty

        new_state = formatter_agent(state)

        assert new_state["csm_list"] == []
        assert new_state["non_csm_list"] == []

    def test_agent_sets_completed_status(self):
        """Test that agent sets workflow status to completed."""
        doc = create_test_document()
        state = create_initial_state([doc])
        state = WorkflowState(
            **{
                **state,
                "classified_persons": [create_classified_person()],
            }
        )

        new_state = formatter_agent(state)

        assert new_state["status"] == "completed"
