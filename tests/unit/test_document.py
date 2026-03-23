"""Unit tests for document extraction service."""

import tempfile
from pathlib import Path

import pytest

from src.services.document import (
    DocumentExtractionError,
    DocumentInput,
    PageContent,
    extract_document,
    extract_txt,
    get_page_count,
)


class TestPageContent:
    """Tests for PageContent model."""

    def test_create_page_content(self):
        """Test creating PageContent."""
        page = PageContent(page_number=1, text="Hello world")
        assert page.page_number == 1
        assert page.text == "Hello world"

    def test_page_number_must_be_positive(self):
        """Test that page number must be >= 1."""
        with pytest.raises(ValueError):
            PageContent(page_number=0, text="test")


class TestDocumentInput:
    """Tests for DocumentInput model."""

    def test_create_document_input(self):
        """Test creating DocumentInput."""
        doc = DocumentInput(
            document_id="123",
            filename="test.pdf",
            file_type="PDF",
            content="[PAGE 1]\nHello",
            pages=[PageContent(page_number=1, text="Hello")],
            page_count=1,
        )
        assert doc.document_id == "123"
        assert doc.filename == "test.pdf"
        assert doc.file_type == "PDF"
        assert doc.page_count == 1


class TestExtractTxt:
    """Tests for TXT extraction."""

    def test_extract_simple_txt(self):
        """Test extracting simple TXT file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Hello, World!")
            f.flush()
            path = Path(f.name)

        try:
            pages, content = extract_txt(path)
            assert len(pages) == 1
            assert pages[0].page_number == 1
            assert pages[0].text == "Hello, World!"
            assert "[PAGE 1]" in content
        finally:
            path.unlink()

    def test_extract_txt_with_german_characters(self):
        """Test extracting TXT with German characters (umlauts)."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("Hans Müller ist Geschäftsführer bei München GmbH.")
            f.flush()
            path = Path(f.name)

        try:
            pages, content = extract_txt(path)
            assert "Müller" in pages[0].text
            assert "Geschäftsführer" in pages[0].text
            assert "München" in pages[0].text
        finally:
            path.unlink()

    def test_extract_txt_multiline(self):
        """Test extracting TXT with multiple lines."""
        text = """Name: Hans Müller
Geburtsdatum: 15.03.1975
Position: Geschäftsführer
Adresse: Berliner Str. 42, 10115 Berlin"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(text)
            f.flush()
            path = Path(f.name)

        try:
            pages, content = extract_txt(path)
            assert "Name: Hans Müller" in pages[0].text
            assert "Geschäftsführer" in pages[0].text
        finally:
            path.unlink()

    def test_extract_txt_not_found(self):
        """Test that missing file raises error."""
        with pytest.raises(DocumentExtractionError, match="File not found"):
            extract_document("/nonexistent/file.txt", "123")


class TestExtractDocument:
    """Tests for extract_document function."""

    def test_extract_txt_document(self):
        """Test extracting TXT document."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("Test content")
            f.flush()
            path = Path(f.name)

        try:
            doc = extract_document(path, document_id="test-123")
            assert isinstance(doc, DocumentInput)
            assert doc.document_id == "test-123"
            assert doc.file_type == "TXT"
            assert doc.page_count == 1
            assert "Test content" in doc.content
        finally:
            path.unlink()

    def test_extract_document_custom_filename(self):
        """Test extracting with custom filename."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
            f.write("Test")
            f.flush()
            path = Path(f.name)

        try:
            doc = extract_document(
                path, document_id="123", filename="custom_name.txt"
            )
            assert doc.filename == "custom_name.txt"
        finally:
            path.unlink()

    def test_extract_unsupported_file_type(self):
        """Test that unsupported file type raises error."""
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            f.write(b"test")
            f.flush()
            path = Path(f.name)

        try:
            with pytest.raises(ValueError, match="Unsupported file type"):
                extract_document(path, document_id="123")
        finally:
            path.unlink()


class TestGetPageCount:
    """Tests for get_page_count function."""

    def test_get_page_count_txt(self):
        """Test page count for TXT file (always 1)."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"test content")
            f.flush()
            path = Path(f.name)

        try:
            count = get_page_count(path)
            assert count == 1
        finally:
            path.unlink()

    def test_get_page_count_unsupported_type(self):
        """Test that unsupported file type raises error."""
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            f.write(b"test")
            f.flush()
            path = Path(f.name)

        try:
            with pytest.raises(ValueError, match="Unsupported file type"):
                get_page_count(path)
        finally:
            path.unlink()


class TestGermanDocumentExtraction:
    """Tests specific to German document handling."""

    def test_extract_handelsregister_style_content(self):
        """Test extracting content similar to HandelsRegister documents."""
        content = """Handelsregister Auszug

Firma: Example GmbH
Sitz: München
Geschäftsanschrift: Maximilianstraße 1, 80539 München

Geschäftsführer:
- Hans Müller, geb. 15.03.1975, wohnhaft in Berlin
- Anna Schmidt, geb. 22.07.1980, wohnhaft in München

Prokuristen:
- Peter Weber, geb. 01.12.1985

Gesellschafter:
- Hans Müller (50%)
- Anna Schmidt (50%)

Stammkapital: 25.000,00 EUR
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            doc = extract_document(path, document_id="hr-001")
            assert "Geschäftsführer" in doc.content
            assert "Hans Müller" in doc.content
            assert "München" in doc.content
            assert "Prokuristen" in doc.content
        finally:
            path.unlink()

    def test_extract_german_special_characters(self):
        """Test extraction handles all German special characters."""
        # ä, ö, ü, ß, Ä, Ö, Ü
        content = "äöüßÄÖÜ Größe Müller Geschäftsführer"

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            pages, text = extract_txt(path)
            assert "äöüßÄÖÜ" in pages[0].text
            assert "Größe" in pages[0].text
            assert "Müller" in pages[0].text
            assert "Geschäftsführer" in pages[0].text
        finally:
            path.unlink()
