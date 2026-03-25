"""Integration tests for file upload functionality.

Tests:
- T252: PDF/TXT upload acceptance
- T253: Invalid file type rejection
"""

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.dependencies import Settings, get_db, get_settings
from src.api.errors import ErrorCode
from src.api.main import app
from src.services.database import Base


# --- Test Fixtures ---


@pytest.fixture
def test_engine():
    """Create a test database engine with in-memory SQLite."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def test_db(test_engine):
    """Create a test database session factory."""
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=test_engine
    )
    return TestingSessionLocal


@pytest.fixture
def test_settings(tmp_path):
    """Create test settings with temporary directories."""
    settings = Settings()
    settings.UPLOAD_DIR = tmp_path / "uploads"
    settings.OUTPUT_DIR = tmp_path / "outputs"
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return settings


@pytest.fixture
def client(test_db, test_settings):
    """Create a test client with overridden dependencies."""

    def override_get_db():
        db = test_db()
        try:
            yield db
        finally:
            db.close()

    def override_get_settings():
        return test_settings

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = override_get_settings

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
def sample_pdf_content():
    """Create minimal valid PDF content for testing."""
    return b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj
xref
0 4
0000000000 65535 f
0000000009 00000 n
0000000052 00000 n
0000000101 00000 n
trailer<</Size 4/Root 1 0 R>>
startxref
170
%%EOF"""


@pytest.fixture
def sample_txt_content():
    """Create sample TXT content for testing."""
    return b"Sample text document content\nWith multiple lines\nAnd German characters: Muller"


@pytest.fixture
def sample_german_txt_content():
    """Create TXT content with German characters."""
    return "Hans Müller - Geschäftsführer\nAnna Schröder - Prokuristin".encode("utf-8")


# --- T252: PDF/TXT Upload Acceptance Tests ---


class TestPDFTXTUploadAcceptance:
    """Tests for PDF and TXT file upload acceptance (T252)."""

    def test_accept_pdf_file_via_workflow(self, client, sample_pdf_content):
        """Test PDF file is accepted when creating workflow."""
        files = [
            ("files", ("document.pdf", io.BytesIO(sample_pdf_content), "application/pdf"))
        ]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 201
        data = response.json()
        assert data["documents"][0]["file_type"] == "PDF"
        assert data["documents"][0]["filename"] == "document.pdf"

    def test_accept_txt_file_via_workflow(self, client, sample_txt_content):
        """Test TXT file is accepted when creating workflow."""
        files = [
            ("files", ("document.txt", io.BytesIO(sample_txt_content), "text/plain"))
        ]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 201
        data = response.json()
        assert data["documents"][0]["file_type"] == "TXT"
        assert data["documents"][0]["filename"] == "document.txt"

    def test_accept_pdf_with_different_content_type(self, client, sample_pdf_content):
        """Test PDF file accepted with alternative content type."""
        # Some browsers send different content types
        files = [
            (
                "files",
                ("document.pdf", io.BytesIO(sample_pdf_content), "application/x-pdf"),
            )
        ]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 201
        data = response.json()
        assert data["documents"][0]["file_type"] == "PDF"

    def test_accept_txt_with_alternative_content_type(self, client, sample_txt_content):
        """Test TXT file accepted with text/x-txt content type."""
        files = [
            ("files", ("document.txt", io.BytesIO(sample_txt_content), "text/x-txt"))
        ]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 201

    def test_accept_txt_with_german_characters(self, client, sample_german_txt_content):
        """Test TXT file with German characters is accepted."""
        files = [
            (
                "files",
                (
                    "handelsregister.txt",
                    io.BytesIO(sample_german_txt_content),
                    "text/plain",
                ),
            )
        ]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 201
        data = response.json()
        assert data["documents"][0]["filename"] == "handelsregister.txt"

    def test_accept_multiple_pdf_files(self, client, sample_pdf_content):
        """Test multiple PDF files can be uploaded."""
        files = [
            ("files", ("doc1.pdf", io.BytesIO(sample_pdf_content), "application/pdf")),
            ("files", ("doc2.pdf", io.BytesIO(sample_pdf_content), "application/pdf")),
            ("files", ("doc3.pdf", io.BytesIO(sample_pdf_content), "application/pdf")),
        ]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 201
        data = response.json()
        assert len(data["documents"]) == 3
        assert all(d["file_type"] == "PDF" for d in data["documents"])

    def test_accept_multiple_txt_files(self, client, sample_txt_content):
        """Test multiple TXT files can be uploaded."""
        files = [
            ("files", ("doc1.txt", io.BytesIO(sample_txt_content), "text/plain")),
            ("files", ("doc2.txt", io.BytesIO(sample_txt_content), "text/plain")),
        ]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 201
        data = response.json()
        assert len(data["documents"]) == 2
        assert all(d["file_type"] == "TXT" for d in data["documents"])

    def test_accept_mixed_pdf_txt_files(
        self, client, sample_pdf_content, sample_txt_content
    ):
        """Test mixed PDF and TXT files can be uploaded together."""
        files = [
            ("files", ("doc1.pdf", io.BytesIO(sample_pdf_content), "application/pdf")),
            ("files", ("doc2.txt", io.BytesIO(sample_txt_content), "text/plain")),
            ("files", ("doc3.pdf", io.BytesIO(sample_pdf_content), "application/pdf")),
        ]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 201
        data = response.json()
        assert len(data["documents"]) == 3

        file_types = {d["filename"]: d["file_type"] for d in data["documents"]}
        assert file_types["doc1.pdf"] == "PDF"
        assert file_types["doc2.txt"] == "TXT"
        assert file_types["doc3.pdf"] == "PDF"

    def test_pdf_page_count_returned(self, client, sample_pdf_content):
        """Test that PDF page count is returned."""
        files = [
            ("files", ("document.pdf", io.BytesIO(sample_pdf_content), "application/pdf"))
        ]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 201
        data = response.json()
        # Minimal PDF has 1 page
        assert data["documents"][0]["page_count"] is not None

    def test_txt_page_count_is_one(self, client, sample_txt_content):
        """Test that TXT files have page count of 1."""
        files = [
            ("files", ("document.txt", io.BytesIO(sample_txt_content), "text/plain"))
        ]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 201
        data = response.json()
        assert data["documents"][0]["page_count"] == 1

    def test_upload_document_to_existing_workflow(self, client, sample_txt_content):
        """Test uploading document to existing pending workflow."""
        # Create workflow first
        files = [("files", ("initial.txt", io.BytesIO(b"initial"), "text/plain"))]
        create_response = client.post("/api/v1/workflows", files=files)
        workflow_id = create_response.json()["workflow_id"]

        # Upload additional document
        file = [
            ("file", ("additional.txt", io.BytesIO(sample_txt_content), "text/plain"))
        ]
        response = client.post(
            f"/api/v1/workflows/{workflow_id}/documents", files=file
        )

        assert response.status_code == 201
        data = response.json()
        assert data["workflow_id"] == workflow_id
        assert data["filename"] == "additional.txt"

    def test_file_saved_to_disk(self, client, test_settings, sample_txt_content):
        """Test that uploaded file is actually saved to disk."""
        files = [
            ("files", ("test_save.txt", io.BytesIO(sample_txt_content), "text/plain"))
        ]

        response = client.post("/api/v1/workflows", files=files)
        workflow_id = response.json()["workflow_id"]

        # Check file exists on disk
        expected_path = test_settings.UPLOAD_DIR / workflow_id / "test_save.txt"
        assert expected_path.exists()
        assert expected_path.read_bytes() == sample_txt_content


# --- T253: Invalid File Type Rejection Tests ---


class TestInvalidFileTypeRejection:
    """Tests for invalid file type rejection (T253)."""

    def test_reject_docx_file(self, client):
        """Test DOCX file is rejected."""
        files = [
            (
                "files",
                (
                    "document.docx",
                    io.BytesIO(b"PK\x03\x04fake docx content"),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
            )
        ]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 400
        data = response.json()
        assert data["error"]["code"] == ErrorCode.INVALID_FILE_TYPE
        assert "document.docx" in data["error"]["message"]

    def test_reject_xlsx_file(self, client):
        """Test XLSX (Excel) file is rejected."""
        files = [
            (
                "files",
                (
                    "spreadsheet.xlsx",
                    io.BytesIO(b"PK\x03\x04fake xlsx content"),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
            )
        ]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 400
        data = response.json()
        assert data["error"]["code"] == ErrorCode.INVALID_FILE_TYPE

    def test_reject_image_file(self, client):
        """Test image files are rejected."""
        files = [
            ("files", ("image.jpg", io.BytesIO(b"\xff\xd8\xff\xe0"), "image/jpeg"))
        ]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 400
        assert response.json()["error"]["code"] == ErrorCode.INVALID_FILE_TYPE

    def test_reject_png_file(self, client):
        """Test PNG image is rejected."""
        png_header = b"\x89PNG\r\n\x1a\n"
        files = [("files", ("image.png", io.BytesIO(png_header), "image/png"))]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 400
        assert response.json()["error"]["code"] == ErrorCode.INVALID_FILE_TYPE

    def test_reject_html_file(self, client):
        """Test HTML file is rejected."""
        files = [
            (
                "files",
                ("page.html", io.BytesIO(b"<html></html>"), "text/html"),
            )
        ]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 400
        assert response.json()["error"]["code"] == ErrorCode.INVALID_FILE_TYPE

    def test_reject_csv_file(self, client):
        """Test CSV file is rejected (not standard TXT)."""
        files = [
            ("files", ("data.csv", io.BytesIO(b"a,b,c\n1,2,3"), "text/csv"))
        ]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 400
        assert response.json()["error"]["code"] == ErrorCode.INVALID_FILE_TYPE

    def test_reject_zip_file(self, client):
        """Test ZIP archive is rejected."""
        files = [
            (
                "files",
                ("archive.zip", io.BytesIO(b"PK\x03\x04"), "application/zip"),
            )
        ]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 400
        assert response.json()["error"]["code"] == ErrorCode.INVALID_FILE_TYPE

    def test_reject_json_file(self, client):
        """Test JSON file is rejected."""
        files = [
            (
                "files",
                ("data.json", io.BytesIO(b'{"key": "value"}'), "application/json"),
            )
        ]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 400
        assert response.json()["error"]["code"] == ErrorCode.INVALID_FILE_TYPE

    def test_reject_xml_file(self, client):
        """Test XML file is rejected."""
        files = [
            (
                "files",
                ("data.xml", io.BytesIO(b"<?xml version='1.0'?>"), "application/xml"),
            )
        ]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 400
        assert response.json()["error"]["code"] == ErrorCode.INVALID_FILE_TYPE

    def test_reject_executable_file(self, client):
        """Test executable file is rejected."""
        files = [
            (
                "files",
                ("program.exe", io.BytesIO(b"MZ\x90\x00"), "application/octet-stream"),
            )
        ]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 400
        assert response.json()["error"]["code"] == ErrorCode.INVALID_FILE_TYPE

    def test_reject_with_multiple_files_one_invalid(
        self, client, sample_txt_content, sample_pdf_content
    ):
        """Test that batch with one invalid file is rejected entirely."""
        files = [
            ("files", ("doc1.txt", io.BytesIO(sample_txt_content), "text/plain")),
            ("files", ("doc2.pdf", io.BytesIO(sample_pdf_content), "application/pdf")),
            (
                "files",
                ("doc3.docx", io.BytesIO(b"invalid"), "application/vnd.openxmlformats"),
            ),
        ]

        response = client.post("/api/v1/workflows", files=files)

        # Entire batch should be rejected
        assert response.status_code == 400
        assert response.json()["error"]["code"] == ErrorCode.INVALID_FILE_TYPE

    def test_reject_disguised_file_wrong_extension(self, client):
        """Test file with wrong extension is rejected."""
        # Content claims to be PDF but extension is .exe
        files = [
            (
                "files",
                ("malware.exe", io.BytesIO(b"%PDF-1.4"), "application/pdf"),
            )
        ]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 400
        assert response.json()["error"]["code"] == ErrorCode.INVALID_FILE_TYPE


# --- File Size Tests ---


class TestFileSizeLimits:
    """Tests for file size validation."""

    def test_accept_file_within_limit(self, client, test_settings):
        """Test file within size limit is accepted."""
        test_settings.MAX_FILE_SIZE_BYTES = 1000
        content = b"x" * 500  # Half the limit

        files = [("files", ("small.txt", io.BytesIO(content), "text/plain"))]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 201

    def test_reject_file_exceeding_limit(self, client, test_settings):
        """Test file exceeding size limit is rejected."""
        test_settings.MAX_FILE_SIZE_BYTES = 100
        content = b"x" * 200  # Twice the limit

        files = [("files", ("large.txt", io.BytesIO(content), "text/plain"))]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 413
        data = response.json()
        assert data["error"]["code"] == ErrorCode.FILE_TOO_LARGE
        assert "large.txt" in data["error"]["message"]

    def test_reject_file_at_exact_limit(self, client, test_settings):
        """Test file at exact size limit is accepted."""
        test_settings.MAX_FILE_SIZE_BYTES = 100
        content = b"x" * 100  # Exactly at limit

        files = [("files", ("exact.txt", io.BytesIO(content), "text/plain"))]

        response = client.post("/api/v1/workflows", files=files)

        # At limit should be accepted
        assert response.status_code == 201

    def test_reject_one_large_file_in_batch(
        self, client, test_settings, sample_txt_content
    ):
        """Test that one large file in batch causes rejection."""
        test_settings.MAX_FILE_SIZE_BYTES = 100
        large_content = b"x" * 200

        files = [
            ("files", ("small.txt", io.BytesIO(sample_txt_content), "text/plain")),
            ("files", ("large.txt", io.BytesIO(large_content), "text/plain")),
        ]

        response = client.post("/api/v1/workflows", files=files)

        # Should fail because one file is too large
        assert response.status_code == 413
