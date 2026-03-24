"""Contract tests for the extractor agent.

These tests verify that the extractor agent:
- Extracts mandatory fields (first_name, last_name)
- Populates source references for each person
- Follows the ExtractorInput/ExtractorOutput contract
"""

import pytest

from src.agents.extractor import (
    ExtractorInput,
    ExtractorOutput,
    parse_llm_response,
    render_prompt,
)
from src.models.person import ExtractedPerson, SourceReference
from src.services.document import DocumentInput, PageContent


# --- Test Fixtures ---


def create_test_document(
    doc_id: str = "doc1",
    content: str = "[PAGE 1]\nHans Müller, Geschäftsführer",
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


# --- Contract Tests ---


class TestExtractorInputContract:
    """Tests for ExtractorInput contract."""

    def test_valid_input_with_documents(self):
        """Test valid input with documents."""
        doc = create_test_document()
        input_data = ExtractorInput(documents=[doc])

        assert len(input_data.documents) == 1
        assert input_data.retry_feedback is None

    def test_valid_input_with_retry_feedback(self):
        """Test valid input with retry feedback."""
        doc = create_test_document()
        input_data = ExtractorInput(
            documents=[doc],
            retry_feedback="Please extract date of birth",
        )

        assert input_data.retry_feedback == "Please extract date of birth"

    def test_input_requires_documents(self):
        """Test that documents field is required."""
        with pytest.raises(Exception):
            ExtractorInput()


class TestExtractorOutputContract:
    """Tests for ExtractorOutput contract."""

    def test_valid_output_with_persons(self):
        """Test valid output with extracted persons."""
        person = ExtractedPerson(
            extraction_id="ext1",
            first_name="Hans",
            last_name="Müller",
            source_references=[
                SourceReference(
                    document_id="doc1",
                    filename="doc1.pdf",
                    page_number=1,
                )
            ],
        )
        output = ExtractorOutput(extracted_persons=[person])

        assert len(output.extracted_persons) == 1

    def test_valid_output_empty_list(self):
        """Test valid output with empty person list."""
        output = ExtractorOutput(extracted_persons=[])

        assert output.extracted_persons == []


class TestMandatoryFieldsExtraction:
    """Contract tests: verify mandatory fields extracted."""

    def test_extracted_person_has_first_name(self):
        """Test that extracted person has non-empty first_name."""
        person = ExtractedPerson(
            extraction_id="ext1",
            first_name="Hans",
            last_name="Müller",
            source_references=[
                SourceReference(
                    document_id="doc1",
                    filename="doc1.pdf",
                    page_number=1,
                )
            ],
        )

        assert person.first_name == "Hans"
        assert len(person.first_name) > 0

    def test_extracted_person_has_last_name(self):
        """Test that extracted person has non-empty last_name."""
        person = ExtractedPerson(
            extraction_id="ext1",
            first_name="Hans",
            last_name="Müller",
            source_references=[
                SourceReference(
                    document_id="doc1",
                    filename="doc1.pdf",
                    page_number=1,
                )
            ],
        )

        assert person.last_name == "Müller"
        assert len(person.last_name) > 0

    def test_empty_first_name_rejected(self):
        """Test that empty first_name is rejected by Pydantic."""
        with pytest.raises(Exception):
            ExtractedPerson(
                extraction_id="ext1",
                first_name="",  # Empty - should fail
                last_name="Müller",
                source_references=[
                    SourceReference(
                        document_id="doc1",
                        filename="doc1.pdf",
                        page_number=1,
                    )
                ],
            )

    def test_empty_last_name_rejected(self):
        """Test that empty last_name is rejected by Pydantic."""
        with pytest.raises(Exception):
            ExtractedPerson(
                extraction_id="ext1",
                first_name="Hans",
                last_name="",  # Empty - should fail
                source_references=[
                    SourceReference(
                        document_id="doc1",
                        filename="doc1.pdf",
                        page_number=1,
                    )
                ],
            )

    def test_extraction_id_required(self):
        """Test that extraction_id is required."""
        with pytest.raises(Exception):
            ExtractedPerson(
                first_name="Hans",
                last_name="Müller",
                source_references=[
                    SourceReference(
                        document_id="doc1",
                        filename="doc1.pdf",
                        page_number=1,
                    )
                ],
            )


class TestSourceReferencesPopulated:
    """Contract tests: verify source references populated."""

    def test_extracted_person_has_source_references(self):
        """Test that extracted person has at least one source reference."""
        person = ExtractedPerson(
            extraction_id="ext1",
            first_name="Hans",
            last_name="Müller",
            source_references=[
                SourceReference(
                    document_id="doc1",
                    filename="doc1.pdf",
                    page_number=1,
                )
            ],
        )

        assert len(person.source_references) >= 1

    def test_source_reference_has_document_id(self):
        """Test that source reference has document_id."""
        ref = SourceReference(
            document_id="doc1",
            filename="doc1.pdf",
            page_number=1,
        )

        assert ref.document_id == "doc1"

    def test_source_reference_has_filename(self):
        """Test that source reference has filename."""
        ref = SourceReference(
            document_id="doc1",
            filename="doc1.pdf",
            page_number=1,
        )

        assert ref.filename == "doc1.pdf"

    def test_source_reference_has_valid_page_number(self):
        """Test that source reference has valid page number (>= 1)."""
        ref = SourceReference(
            document_id="doc1",
            filename="doc1.pdf",
            page_number=1,
        )

        assert ref.page_number >= 1

    def test_invalid_page_number_rejected(self):
        """Test that page_number < 1 is rejected."""
        with pytest.raises(Exception):
            SourceReference(
                document_id="doc1",
                filename="doc1.pdf",
                page_number=0,  # Invalid
            )

    def test_empty_source_references_rejected(self):
        """Test that empty source_references list is rejected."""
        with pytest.raises(Exception):
            ExtractedPerson(
                extraction_id="ext1",
                first_name="Hans",
                last_name="Müller",
                source_references=[],  # Empty - should fail
            )


class TestParseLLMResponse:
    """Tests for LLM response parsing."""

    def test_parse_valid_json_array(self):
        """Test parsing valid JSON array response."""
        response = '''[
            {
                "extraction_id": "ext1",
                "first_name": "Hans",
                "last_name": "Müller",
                "job_title": "Managing Director",
                "source_references": [
                    {
                        "document_id": "doc1",
                        "filename": "doc1.pdf",
                        "page_number": 1
                    }
                ]
            }
        ]'''
        documents = [create_test_document()]

        persons = parse_llm_response(response, documents)

        assert len(persons) == 1
        assert persons[0].first_name == "Hans"
        assert persons[0].last_name == "Müller"

    def test_parse_json_with_markdown_code_block(self):
        """Test parsing JSON wrapped in markdown code block."""
        response = '''```json
        [
            {
                "extraction_id": "ext1",
                "first_name": "Anna",
                "last_name": "Schmidt",
                "source_references": [
                    {
                        "document_id": "doc1",
                        "filename": "doc1.pdf",
                        "page_number": 2
                    }
                ]
            }
        ]
        ```'''
        documents = [create_test_document()]

        persons = parse_llm_response(response, documents)

        assert len(persons) == 1
        assert persons[0].first_name == "Anna"

    def test_parse_json_object_with_extracted_persons_key(self):
        """Test parsing JSON object with extracted_persons key."""
        response = '''{
            "extracted_persons": [
                {
                    "extraction_id": "ext1",
                    "first_name": "Peter",
                    "last_name": "Weber",
                    "source_references": [
                        {
                            "document_id": "doc1",
                            "filename": "doc1.pdf",
                            "page_number": 1
                        }
                    ]
                }
            ]
        }'''
        documents = [create_test_document()]

        persons = parse_llm_response(response, documents)

        assert len(persons) == 1
        assert persons[0].first_name == "Peter"

    def test_parse_generates_extraction_id_if_missing(self):
        """Test that extraction_id is generated if not provided."""
        response = '''[
            {
                "first_name": "Klaus",
                "last_name": "Fischer",
                "source_references": [
                    {
                        "document_id": "doc1",
                        "filename": "doc1.pdf",
                        "page_number": 1
                    }
                ]
            }
        ]'''
        documents = [create_test_document()]

        persons = parse_llm_response(response, documents)

        assert len(persons) == 1
        assert persons[0].extraction_id is not None
        assert persons[0].extraction_id.startswith("ext_")

    def test_parse_invalid_json_raises(self):
        """Test that invalid JSON raises ValueError."""
        response = "not valid json"
        documents = [create_test_document()]

        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_llm_response(response, documents)


class TestRenderPrompt:
    """Tests for prompt rendering."""

    def test_render_prompt_includes_document_content(self):
        """Test that rendered prompt includes document content."""
        doc = create_test_document(content="[PAGE 1]\nTest document content")

        prompt = render_prompt([doc])

        assert "Test document content" in prompt

    def test_render_prompt_includes_document_metadata(self):
        """Test that rendered prompt includes document metadata."""
        doc = create_test_document(doc_id="test_doc")

        prompt = render_prompt([doc])

        assert "test_doc" in prompt
        assert "PDF" in prompt

    def test_render_prompt_with_retry_feedback(self):
        """Test that rendered prompt includes retry feedback."""
        doc = create_test_document()
        feedback = "Please extract the date of birth"

        prompt = render_prompt([doc], retry_feedback=feedback)

        assert "Please extract the date of birth" in prompt
        assert "Retry" in prompt or "feedback" in prompt.lower()

    def test_render_prompt_multiple_documents(self):
        """Test that rendered prompt includes all documents."""
        doc1 = create_test_document("doc1", "[PAGE 1]\nDocument 1 content")
        doc2 = create_test_document("doc2", "[PAGE 1]\nDocument 2 content")

        prompt = render_prompt([doc1, doc2])

        assert "Document 1 content" in prompt
        assert "Document 2 content" in prompt
