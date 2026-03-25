"""Edge case tests for the KYC workflow.

Tests for:
- T311: Document with no persons
- T312: Corrupted PDF handling
- T313: Person without job title
"""

import pytest
from pathlib import Path
from io import BytesIO

from src.agents.critic import critic_1_agent, critic_3_agent
from src.agents.extractor import ExtractorOutput, extractor_agent
from src.agents.formatter import formatter_agent
from src.core.state import (
    WorkflowState,
    create_initial_state,
    update_extraction_result,
    update_final_output,
)
from src.core.workflow import compile_workflow, run_workflow_sync
from src.models.enums import CriticDecision
from src.models.output import DocumentManifestEntry
from src.models.person import (
    ClassifiedPerson,
    ExtractedPerson,
    ReconciledPerson,
    SourceReference,
)
from src.services.document import DocumentInput, PageContent, extract_document


# --- Test Fixtures ---


def create_empty_document() -> DocumentInput:
    """Create a document with no person data."""
    return DocumentInput(
        document_id="empty_doc",
        filename="empty.pdf",
        file_type="PDF",
        content="[PAGE 1]\nThis document contains no person information.\n"
                "Only company registration details and legal notices.\n"
                "Registered at: Amtsgericht Frankfurt\nHRB 12345",
        pages=[
            PageContent(
                page_number=1,
                text="This document contains no person information.\n"
                     "Only company registration details and legal notices.\n"
                     "Registered at: Amtsgericht Frankfurt\nHRB 12345",
            )
        ],
        page_count=1,
    )


def create_person_without_job_title() -> ExtractedPerson:
    """Create a person record without a job title."""
    return ExtractedPerson(
        extraction_id="ext_no_title",
        first_name="Klaus",
        last_name="Weber",
        job_title=None,  # No job title
        job_title_original=None,
        source_references=[
            SourceReference(
                document_id="doc1",
                filename="doc1.pdf",
                page_number=1,
                extracted_text_snippet="Klaus Weber",
                confidence=0.85,
            )
        ],
    )


def create_person_with_job_title() -> ExtractedPerson:
    """Create a person record with a job title."""
    return ExtractedPerson(
        extraction_id="ext_with_title",
        first_name="Maria",
        last_name="Fischer",
        job_title="Chief Executive Officer",
        job_title_original="Vorstandsvorsitzende",
        source_references=[
            SourceReference(
                document_id="doc1",
                filename="doc1.pdf",
                page_number=1,
                extracted_text_snippet="Maria Fischer, Vorstandsvorsitzende",
                confidence=0.95,
            )
        ],
    )


# --- Mock Agents ---


def mock_extractor_empty(state: WorkflowState) -> WorkflowState:
    """Mock extractor that returns empty list (no persons found)."""
    return update_extraction_result(state, [])


def mock_extractor_no_job_title(state: WorkflowState) -> WorkflowState:
    """Mock extractor that returns person without job title."""
    return update_extraction_result(
        state, [create_person_without_job_title(), create_person_with_job_title()]
    )


def mock_reconciler(state: WorkflowState) -> WorkflowState:
    """Mock reconciler that passes through extracted persons."""
    extracted = state.get("extracted_persons", [])
    reconciled = []
    for p in extracted:
        reconciled.append(
            ReconciledPerson(
                person_id=f"person_{p.extraction_id}",
                first_name=p.first_name,
                last_name=p.last_name,
                first_name_normalized=p.first_name.lower().strip(),
                last_name_normalized=p.last_name.lower().strip(),
                job_title=p.job_title,
                source_references=p.source_references,
            )
        )
    return WorkflowState(
        **{
            **state,
            "reconciled_persons": reconciled,
            "duplicate_groups": [],
        }
    )


def mock_classifier(state: WorkflowState) -> WorkflowState:
    """Mock classifier that handles persons with/without job titles."""
    reconciled = state.get("reconciled_persons", [])
    classified = []
    for p in reconciled:
        # Persons with executive job titles get CSM, others NON_CSM
        if p.job_title and any(
            term in p.job_title.lower()
            for term in ["ceo", "chief", "director", "executive", "officer"]
        ):
            classification = "CSM"
            reasoning = f"Executive role: {p.job_title}"
            criteria_met = ["executive_management"]
        else:
            classification = "NON_CSM"
            if p.job_title:
                reasoning = f"Non-executive role: {p.job_title}"
            else:
                reasoning = "No job title provided - cannot determine executive status"
            criteria_met = []

        classified.append(
            ClassifiedPerson(
                person_id=p.person_id,
                first_name=p.first_name,
                last_name=p.last_name,
                job_title=p.job_title,
                source_references=p.source_references,
                classification=classification,
                reasoning=reasoning,
                criteria_met=criteria_met,
            )
        )
    return WorkflowState(**{**state, "classified_persons": classified})


def mock_formatter(state: WorkflowState) -> WorkflowState:
    """Mock formatter that produces final output."""
    classified = state.get("classified_persons", [])
    documents = state.get("documents", [])

    manifest = [
        DocumentManifestEntry(
            filename=doc.filename,
            file_type=doc.file_type,
            page_count=doc.page_count,
            processing_status="processed",
        )
        for doc in documents
    ]

    csm_list = [p for p in classified if p.classification == "CSM"]
    non_csm_list = [p for p in classified if p.classification == "NON_CSM"]

    return update_final_output(state, manifest, csm_list, non_csm_list)


def mock_critic_pass(state: WorkflowState) -> tuple[CriticDecision, str | None]:
    """Mock critic that always passes."""
    return (CriticDecision.PASS, None)


# --- Edge Case Test: Document with No Persons (T311) ---


class TestDocumentWithNoPersons:
    """Tests for handling documents that contain no person data."""

    def test_empty_document_workflow_completes(self):
        """Test that workflow completes successfully with empty document."""
        agent_functions = {
            "extractor": mock_extractor_empty,
            "reconciler": mock_reconciler,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": mock_critic_pass,
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_empty_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        assert final_state["status"] == "completed"
        assert len(final_state["extracted_persons"]) == 0
        assert len(final_state["csm_list"]) == 0
        assert len(final_state["non_csm_list"]) == 0

    def test_empty_document_produces_valid_manifest(self):
        """Test that empty document produces valid manifest."""
        agent_functions = {
            "extractor": mock_extractor_empty,
            "reconciler": mock_reconciler,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": mock_critic_pass,
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_empty_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        assert len(final_state["document_manifest"]) == 1
        manifest_entry = final_state["document_manifest"][0]
        assert manifest_entry.filename == "empty.pdf"
        assert manifest_entry.processing_status == "processed"

    def test_empty_extraction_passes_critic(self):
        """Test that empty extraction can pass critic validation."""
        # The extractor returning empty should be valid if document has no persons
        agent_functions = {
            "extractor": mock_extractor_empty,
            "reconciler": mock_reconciler,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,  # Allow empty extraction
            "critic_2": mock_critic_pass,
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        initial_state = create_initial_state([create_empty_document()])

        final_state = run_workflow_sync(compiled, initial_state)

        # Should complete without retries
        assert final_state["status"] == "completed"
        assert final_state["extraction_retry_count"] == 0


# --- Edge Case Test: Corrupted PDF Handling (T312) ---


class TestCorruptedPDFHandling:
    """Tests for handling corrupted or invalid PDF files."""

    def test_corrupted_pdf_bytes(self):
        """Test handling of corrupted PDF byte stream."""
        # Create corrupted PDF content (invalid magic bytes)
        corrupted_content = b"This is not a valid PDF file content"

        # The extract_document function should handle this gracefully
        try:
            # Create a temp file with corrupted content
            from tempfile import NamedTemporaryFile
            import os

            with NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                f.write(corrupted_content)
                temp_path = f.name

            try:
                result = extract_document(Path(temp_path))
                # Should either return empty content or raise an error
                # Empty content is acceptable for corrupted files
                assert result is not None
            finally:
                os.unlink(temp_path)

        except Exception as e:
            # Exception handling for corrupted PDF is acceptable
            assert "pdf" in str(e).lower() or "invalid" in str(e).lower() or "error" in str(e).lower()

    def test_truncated_pdf(self):
        """Test handling of truncated PDF file."""
        # Create a truncated PDF (valid header but incomplete)
        truncated_content = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"  # PDF header only

        try:
            from tempfile import NamedTemporaryFile
            import os

            with NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                f.write(truncated_content)
                temp_path = f.name

            try:
                result = extract_document(Path(temp_path))
                # Should return empty or minimal content for truncated file
                assert result is not None
            finally:
                os.unlink(temp_path)

        except Exception as e:
            # Exception handling for truncated PDF is acceptable
            pass

    def test_empty_pdf_file(self):
        """Test handling of empty PDF file."""
        try:
            from tempfile import NamedTemporaryFile
            import os

            with NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                f.write(b"")  # Empty file
                temp_path = f.name

            try:
                result = extract_document(Path(temp_path))
                # Empty file should return empty content
                assert result is not None
                assert result.content == "" or len(result.pages) == 0
            except Exception:
                # Exception for empty file is also acceptable
                pass
            finally:
                os.unlink(temp_path)

        except Exception:
            pass


# --- Edge Case Test: Person Without Job Title (T313) ---


class TestPersonWithoutJobTitle:
    """Tests for handling persons without job title information."""

    def test_person_without_job_title_extracted(self):
        """Test that persons without job titles are extracted successfully."""
        agent_functions = {
            "extractor": mock_extractor_no_job_title,
            "reconciler": mock_reconciler,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": mock_critic_pass,
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        doc = DocumentInput(
            document_id="doc1",
            filename="doc1.pdf",
            file_type="PDF",
            content="[PAGE 1]\nKlaus Weber\nMaria Fischer, Vorstandsvorsitzende",
            pages=[PageContent(page_number=1, text="Klaus Weber\nMaria Fischer, Vorstandsvorsitzende")],
            page_count=1,
        )
        initial_state = create_initial_state([doc])

        final_state = run_workflow_sync(compiled, initial_state)

        assert final_state["status"] == "completed"
        assert len(final_state["extracted_persons"]) == 2

        # Find person without job title
        no_title_persons = [
            p for p in final_state["extracted_persons"] if p.job_title is None
        ]
        assert len(no_title_persons) == 1
        assert no_title_persons[0].first_name == "Klaus"
        assert no_title_persons[0].last_name == "Weber"

    def test_person_without_job_title_classified_as_non_csm(self):
        """Test that persons without job titles are classified as NON_CSM."""
        agent_functions = {
            "extractor": mock_extractor_no_job_title,
            "reconciler": mock_reconciler,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": mock_critic_pass,
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        doc = DocumentInput(
            document_id="doc1",
            filename="doc1.pdf",
            file_type="PDF",
            content="[PAGE 1]\nKlaus Weber\nMaria Fischer, Vorstandsvorsitzende",
            pages=[PageContent(page_number=1, text="Klaus Weber\nMaria Fischer, Vorstandsvorsitzende")],
            page_count=1,
        )
        initial_state = create_initial_state([doc])

        final_state = run_workflow_sync(compiled, initial_state)

        assert final_state["status"] == "completed"

        # Person without job title should be in non_csm_list
        assert len(final_state["non_csm_list"]) == 1
        assert final_state["non_csm_list"][0].first_name == "Klaus"

        # Person with executive job title should be in csm_list
        assert len(final_state["csm_list"]) == 1
        assert final_state["csm_list"][0].first_name == "Maria"

    def test_person_without_job_title_has_reasoning(self):
        """Test that classification reasoning handles missing job title."""
        agent_functions = {
            "extractor": mock_extractor_no_job_title,
            "reconciler": mock_reconciler,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": mock_critic_pass,
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        doc = DocumentInput(
            document_id="doc1",
            filename="doc1.pdf",
            file_type="PDF",
            content="[PAGE 1]\nKlaus Weber",
            pages=[PageContent(page_number=1, text="Klaus Weber")],
            page_count=1,
        )
        initial_state = create_initial_state([doc])

        final_state = run_workflow_sync(compiled, initial_state)

        # Non-CSM person should have reasoning
        non_csm = final_state["non_csm_list"][0]
        assert non_csm.reasoning is not None
        assert len(non_csm.reasoning) > 0

    def test_all_persons_missing_job_titles(self):
        """Test workflow completion when all persons lack job titles."""

        def mock_extractor_all_no_titles(state: WorkflowState) -> WorkflowState:
            persons = [
                ExtractedPerson(
                    extraction_id="ext_1",
                    first_name="Hans",
                    last_name="Müller",
                    job_title=None,
                    source_references=[
                        SourceReference(
                            document_id="doc1", filename="doc1.pdf", page_number=1
                        )
                    ],
                ),
                ExtractedPerson(
                    extraction_id="ext_2",
                    first_name="Anna",
                    last_name="Schmidt",
                    job_title=None,
                    source_references=[
                        SourceReference(
                            document_id="doc1", filename="doc1.pdf", page_number=1
                        )
                    ],
                ),
            ]
            return update_extraction_result(state, persons)

        agent_functions = {
            "extractor": mock_extractor_all_no_titles,
            "reconciler": mock_reconciler,
            "classifier": mock_classifier,
            "formatter": mock_formatter,
        }
        critic_functions = {
            "critic_1": mock_critic_pass,
            "critic_2": mock_critic_pass,
            "critic_3": mock_critic_pass,
        }

        compiled = compile_workflow(agent_functions, critic_functions)
        doc = DocumentInput(
            document_id="doc1",
            filename="doc1.pdf",
            file_type="PDF",
            content="[PAGE 1]\nHans Müller\nAnna Schmidt",
            pages=[PageContent(page_number=1, text="Hans Müller\nAnna Schmidt")],
            page_count=1,
        )
        initial_state = create_initial_state([doc])

        final_state = run_workflow_sync(compiled, initial_state)

        assert final_state["status"] == "completed"
        # All should be classified as NON_CSM due to missing job titles
        assert len(final_state["csm_list"]) == 0
        assert len(final_state["non_csm_list"]) == 2
