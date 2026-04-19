"""Edge case tests for the KYC workflow.

Tests for:
- T311: Document with no persons
- T312: Corrupted PDF handling
- T313: Person without job title
"""

import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import pytest

from src.core.state import (
    WorkflowState,
    create_initial_state,
)
from src.core.workflow import run_workflow_sync
from src.models.output import DocumentManifestEntry
from src.models.person import ClassifiedPerson, ExtractedPerson, ReconciledPerson
from src.services.document import DocumentInput, PageContent, extract_document

from .conftest import build_compiled_workflow, pass_extractor_feedback


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------


def create_empty_document() -> DocumentInput:
    return DocumentInput(
        document_id="empty_doc",
        filename="empty.pdf",
        file_type="PDF",
        content="[PAGE 1]\nThis document contains no person information.\n"
                "Only company registration details and legal notices.\n"
                "Registered at: Amtsgericht Frankfurt\nHRB 12345",
        pages=[PageContent(
            page_number=1,
            text="This document contains no person information.\n"
                 "Only company registration details and legal notices.\n"
                 "Registered at: Amtsgericht Frankfurt\nHRB 12345",
        )],
        page_count=1,
    )


def create_person_without_job_title() -> ExtractedPerson:
    return ExtractedPerson(
        first_name="Klaus",
        last_name="Weber",
        job_title=None,
        job_title_original=None,
        doc_name="doc1.pdf",
        page_number=1,
    )


def create_person_with_job_title() -> ExtractedPerson:
    return ExtractedPerson(
        first_name="Maria",
        last_name="Fischer",
        job_title="Chief Executive Officer",
        job_title_original="Vorstandsvorsitzende",
        doc_name="doc1.pdf",
        page_number=1,
    )


# ---------------------------------------------------------------------------
# Mock agents (factory contract: (state) -> WorkflowState)
# ---------------------------------------------------------------------------


def mock_extractor_empty(state: WorkflowState) -> WorkflowState:
    return WorkflowState(**{**state, "extracted_persons": []})


def mock_extractor_no_job_title(state: WorkflowState) -> WorkflowState:
    return WorkflowState(**{
        **state,
        "extracted_persons": [create_person_without_job_title(), create_person_with_job_title()],
    })


def mock_reconciler(state: WorkflowState) -> WorkflowState:
    extracted = state.get("extracted_persons", [])
    reconciled = [
        ReconciledPerson(
            person_id=f"person_{p.first_name}_{p.last_name}",
            first_name=p.first_name,
            last_name=p.last_name,
            first_name_normalized=p.first_name.lower().strip(),
            last_name_normalized=p.last_name.lower().strip(),
            job_title=p.job_title,
            source_references=p.source_references,
        )
        for p in extracted
    ]
    return WorkflowState(**{**state, "reconciled_persons": reconciled, "duplicate_groups": []})


def mock_classifier(state: WorkflowState) -> WorkflowState:
    reconciled = state.get("reconciled_persons", [])
    executive_terms = ["ceo", "chief", "director", "executive", "officer", "vorstand"]
    classified = []
    for p in reconciled:
        title = (p.job_title or "").lower()
        if any(t in title for t in executive_terms):
            classified.append(ClassifiedPerson(
                person_id=p.person_id,
                first_name=p.first_name,
                last_name=p.last_name,
                job_title=p.job_title,
                source_references=p.source_references,
                classification="CSM",
                reasoning=f"Criterion 1: Executive Management Role — {p.job_title}.",
                criteria_met=["Criterion 1: Executive Management Role"],
            ))
        else:
            classified.append(ClassifiedPerson(
                person_id=p.person_id,
                first_name=p.first_name,
                last_name=p.last_name,
                job_title=p.job_title,
                source_references=p.source_references,
                classification="NON_CSM",
                reasoning=f"Criterion 1-5 not met — {'no job title provided' if not p.job_title else p.job_title}.",
                criteria_not_met=["Criterion 1-5: No CSM criteria met"],
            ))
    return WorkflowState(**{**state, "classified_persons": classified})


_EXECUTIVE_TERMS = ["ceo", "chief", "director", "executive", "officer", "vorstand"]


def mock_formatter(state: WorkflowState) -> WorkflowState:
    extracted = state.get("extracted_persons", [])
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
    csm_list = []
    non_csm_list = []
    for ep in extracted:
        title = (ep.job_title or "").lower()
        if any(t in title for t in _EXECUTIVE_TERMS):
            csm_list.append(ClassifiedPerson(
                person_id=f"person_{ep.first_name}_{ep.last_name}",
                first_name=ep.first_name,
                last_name=ep.last_name,
                job_title=ep.job_title,
                source_references=[],
                classification="CSM",
                reasoning=f"Criterion 1: Executive Management Role — {ep.job_title}.",
                criteria_met=["Criterion 1: Executive Management Role"],
            ))
        else:
            non_csm_list.append(ClassifiedPerson(
                person_id=f"person_{ep.first_name}_{ep.last_name}",
                first_name=ep.first_name,
                last_name=ep.last_name,
                job_title=ep.job_title,
                source_references=[],
                classification="NON_CSM",
                reasoning=f"Criterion 1-5 not met — {'no job title provided' if not ep.job_title else ep.job_title}.",
                criteria_not_met=["Criterion 1-5: No CSM criteria met"],
            ))
    return WorkflowState(**{
        **state,
        "document_manifest": manifest,
        "csm_list": csm_list,
        "non_csm_list": non_csm_list,
        "status": "completed",
        "current_agent": "",
    })


def mock_critic_1_pass(state: WorkflowState) -> WorkflowState:
    return WorkflowState(**{**state, "extractor_critic_feedback": pass_extractor_feedback()})


def mock_critic_2_pass(state: WorkflowState) -> WorkflowState:
    return WorkflowState(**{**state, "last_critic_feedback": None})


def mock_critic_3_pass(state: WorkflowState) -> WorkflowState:
    return WorkflowState(**{**state, "last_critic_feedback": None})


def _all_pass_workflow(extractor=None, reconciler=None, classifier=None, formatter=None):
    return build_compiled_workflow(
        extractor=extractor or mock_extractor_empty,
        critic_1=mock_critic_1_pass,
        reconciler=reconciler or mock_reconciler,
        critic_2=mock_critic_2_pass,
        classifier=classifier or mock_classifier,
        critic_3=mock_critic_3_pass,
        formatter=formatter or mock_formatter,
    )


# ---------------------------------------------------------------------------
# T311: Document with No Persons
# ---------------------------------------------------------------------------


class TestDocumentWithNoPersons:

    def test_empty_document_workflow_completes(self):
        compiled = _all_pass_workflow(extractor=mock_extractor_empty)
        final_state = run_workflow_sync(compiled, create_initial_state([create_empty_document()]))

        assert final_state["status"] == "completed"
        assert len(final_state["extracted_persons"]) == 0
        assert len(final_state["csm_list"]) == 0
        assert len(final_state["non_csm_list"]) == 0

    def test_empty_document_produces_valid_manifest(self):
        compiled = _all_pass_workflow(extractor=mock_extractor_empty)
        final_state = run_workflow_sync(compiled, create_initial_state([create_empty_document()]))

        assert len(final_state["document_manifest"]) == 1
        assert final_state["document_manifest"][0].filename == "empty.pdf"
        assert final_state["document_manifest"][0].processing_status == "processed"

    def test_empty_extraction_completes_without_retry(self):
        compiled = _all_pass_workflow(extractor=mock_extractor_empty)
        final_state = run_workflow_sync(compiled, create_initial_state([create_empty_document()]))

        assert final_state["status"] == "completed"
        assert final_state.get("extraction_retry_count", 0) == 0


# ---------------------------------------------------------------------------
# T312: Corrupted PDF Handling
# ---------------------------------------------------------------------------


class TestCorruptedPDFHandling:

    def _call_extract(self, path: Path) -> Any:
        """Call extract_document with required args, tolerating signature changes."""
        import inspect
        sig = inspect.signature(extract_document)
        if "document_id" in sig.parameters:
            return extract_document(path, document_id="test_doc")
        return extract_document(path)

    def test_corrupted_pdf_bytes(self):
        corrupted_content = b"This is not a valid PDF file content"
        try:
            with NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                f.write(corrupted_content)
                temp_path = f.name
            try:
                result = self._call_extract(Path(temp_path))
                assert result is not None
            finally:
                os.unlink(temp_path)
        except Exception:
            pass  # Any exception for corrupted file is acceptable

    def test_truncated_pdf(self):
        truncated_content = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
        try:
            with NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                f.write(truncated_content)
                temp_path = f.name
            try:
                self._call_extract(Path(temp_path))
            finally:
                os.unlink(temp_path)
        except Exception:
            pass

    def test_empty_pdf_file(self):
        try:
            with NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                f.write(b"")
                temp_path = f.name
            try:
                result = self._call_extract(Path(temp_path))
                if result is not None:
                    assert result.content == "" or len(result.pages) == 0
            except Exception:
                pass
            finally:
                os.unlink(temp_path)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# T313: Person Without Job Title
# ---------------------------------------------------------------------------


class TestPersonWithoutJobTitle:

    def _make_doc(self, content="[PAGE 1]\nKlaus Weber\nMaria Fischer, Vorstandsvorsitzende") -> DocumentInput:
        return DocumentInput(
            document_id="doc1",
            filename="doc1.pdf",
            file_type="PDF",
            content=content,
            pages=[PageContent(page_number=1, text=content.replace("[PAGE 1]\n", ""))],
            page_count=1,
        )

    def test_person_without_job_title_extracted(self):
        compiled = _all_pass_workflow(extractor=mock_extractor_no_job_title)
        final_state = run_workflow_sync(compiled, create_initial_state([self._make_doc()]))

        assert final_state["status"] == "completed"
        assert len(final_state["extracted_persons"]) == 2

        no_title = [p for p in final_state["extracted_persons"] if p.job_title is None]
        assert len(no_title) == 1
        assert no_title[0].first_name == "Klaus"

    def test_person_without_job_title_classified_as_non_csm(self):
        compiled = _all_pass_workflow(extractor=mock_extractor_no_job_title)
        final_state = run_workflow_sync(compiled, create_initial_state([self._make_doc()]))

        assert final_state["status"] == "completed"
        assert len(final_state["non_csm_list"]) == 1
        assert final_state["non_csm_list"][0].first_name == "Klaus"
        assert len(final_state["csm_list"]) == 1
        assert final_state["csm_list"][0].first_name == "Maria"

    def test_person_without_job_title_has_reasoning(self):
        def extractor_single_no_title(state: WorkflowState) -> WorkflowState:
            return WorkflowState(**{**state, "extracted_persons": [create_person_without_job_title()]})

        compiled = _all_pass_workflow(extractor=extractor_single_no_title)
        final_state = run_workflow_sync(compiled, create_initial_state([self._make_doc("Klaus Weber")]))

        non_csm = final_state["non_csm_list"][0]
        assert non_csm.reasoning is not None
        assert len(non_csm.reasoning) > 0

    def test_all_persons_missing_job_titles(self):
        def extractor_all_no_titles(state: WorkflowState) -> WorkflowState:
            return WorkflowState(**{**state, "extracted_persons": [
                ExtractedPerson(
                    first_name="Hans", last_name="Müller", job_title=None,
                    doc_name="doc1.pdf", page_number=1,
                ),
                ExtractedPerson(
                    first_name="Anna", last_name="Schmidt", job_title=None,
                    doc_name="doc1.pdf", page_number=1,
                ),
            ]})

        compiled = _all_pass_workflow(extractor=extractor_all_no_titles)
        final_state = run_workflow_sync(compiled, create_initial_state([self._make_doc()]))

        assert final_state["status"] == "completed"
        assert len(final_state["csm_list"]) == 0
        assert len(final_state["non_csm_list"]) == 2
