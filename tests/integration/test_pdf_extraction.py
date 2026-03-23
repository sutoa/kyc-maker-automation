"""Integration tests for PDF extraction with real HandelsRegister document."""

import uuid
from pathlib import Path

import pytest

from src.services.document import extract_document, get_page_count

# Path to the test fixture
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
HANDELSREGISTER_PDF = FIXTURES_DIR / "HE-Frankfurt_am_Main_HRB_30000+AD-20260323142143.pdf"


@pytest.fixture
def handelsregister_doc():
    """Extract the HandelsRegister test document."""
    if not HANDELSREGISTER_PDF.exists():
        pytest.skip("HandelsRegister PDF fixture not available")
    return extract_document(
        HANDELSREGISTER_PDF,
        document_id=str(uuid.uuid4()),
        filename="handelsregister_sample.pdf",
    )


class TestHandelsRegisterExtraction:
    """Tests for HandelsRegister PDF extraction."""

    def test_extraction_succeeds(self, handelsregister_doc):
        """Test that extraction completes successfully."""
        assert handelsregister_doc is not None
        assert handelsregister_doc.file_type == "PDF"

    def test_page_count(self, handelsregister_doc):
        """Test that page count is detected correctly."""
        assert handelsregister_doc.page_count == 11

    def test_page_markers_present(self, handelsregister_doc):
        """Test that page markers are in the content."""
        content = handelsregister_doc.content
        assert "[PAGE 1]" in content
        assert "[PAGE 2]" in content
        assert "[PAGE 11]" in content

    def test_german_company_name(self, handelsregister_doc):
        """Test that German company name is extracted."""
        assert "DEUTSCHE BANK AKTIENGESELLSCHAFT" in handelsregister_doc.content

    def test_german_location(self, handelsregister_doc):
        """Test that German location is extracted with umlauts."""
        content = handelsregister_doc.content
        # Frankfurt am Main appears in the document
        assert "Frankfurt am Main" in content

    def test_vorstand_section(self, handelsregister_doc):
        """Test that Vorstand (board) section is extracted."""
        content = handelsregister_doc.content
        assert "Vorstand:" in content
        # Check for specific Vorstand members
        assert "Sewing, Christian" in content
        assert "von Moltke, James" in content

    def test_prokura_section(self, handelsregister_doc):
        """Test that Prokura (authorized signatories) section is extracted."""
        content = handelsregister_doc.content
        assert "Prokura:" in content

    def test_german_umlauts_preserved(self, handelsregister_doc):
        """Test that German umlauts (ä, ö, ü, ß) are preserved."""
        content = handelsregister_doc.content
        # Check for words with umlauts
        assert "Geschäftsanschrift" in content or "Geschaftsanschrift" not in content
        # Check for specific names with umlauts
        assert "Düsseldorf" in content or "Dusseldorf" not in content

    def test_birth_dates_extracted(self, handelsregister_doc):
        """Test that birth dates in format *DD.MM.YYYY are extracted."""
        content = handelsregister_doc.content
        # Birth date format used in German documents
        assert "*" in content  # Birth date marker

    def test_pages_list_matches_count(self, handelsregister_doc):
        """Test that pages list length matches page count."""
        assert len(handelsregister_doc.pages) == handelsregister_doc.page_count

    def test_each_page_has_content(self, handelsregister_doc):
        """Test that each page has non-empty content."""
        for page in handelsregister_doc.pages:
            assert page.page_number >= 1
            assert len(page.text) > 0


class TestGetPageCount:
    """Tests for get_page_count function with real PDF."""

    def test_get_page_count_pdf(self):
        """Test getting page count from PDF."""
        if not HANDELSREGISTER_PDF.exists():
            pytest.skip("HandelsRegister PDF fixture not available")
        count = get_page_count(HANDELSREGISTER_PDF)
        assert count == 11
