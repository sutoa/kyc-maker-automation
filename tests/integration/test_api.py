"""API integration tests for all REST endpoints.

This module consolidates integration tests for all API endpoints defined in
contracts/api.md, including workflow and document endpoints.

Tests:
- Workflow CRUD endpoints (POST, GET, start, output, list, trace)
- Document upload endpoints (POST, GET, list)
- Error handling and response formats
"""

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.dependencies import Settings, get_db, get_settings
from src.api.errors import ErrorCode
from src.api.main import app
from src.models.enums import WorkflowStatus
from src.services.database import Base
from src.services.storage import (
    WorkflowRunDB,
    create_workflow_run,
    persist_workflow_output,
    update_workflow_status,
)


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
def db_session(test_db):
    """Create a database session for direct operations."""
    session = test_db()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def sample_pdf_content():
    """Create minimal PDF content for testing."""
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
    return b"Test document content\nHans Mueller - Managing Director\nAnna Schmidt - Clerk"


# --- Health Check Tests ---


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    def test_health_check_returns_healthy(self, client):
        """Test health check endpoint returns healthy status."""
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


# --- Workflow Endpoint Tests ---


class TestWorkflowEndpoints:
    """Integration tests for workflow endpoints."""

    def test_create_workflow_with_txt(self, client, sample_txt_content):
        """Test creating workflow with TXT file."""
        files = [("files", ("test.txt", io.BytesIO(sample_txt_content), "text/plain"))]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 201
        data = response.json()
        assert "workflow_id" in data
        assert data["status"] == "pending"
        assert len(data["documents"]) == 1
        assert data["documents"][0]["filename"] == "test.txt"
        assert data["documents"][0]["file_type"] == "TXT"

    def test_create_workflow_with_pdf(self, client, sample_pdf_content):
        """Test creating workflow with PDF file."""
        files = [
            ("files", ("test.pdf", io.BytesIO(sample_pdf_content), "application/pdf"))
        ]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 201
        data = response.json()
        assert data["documents"][0]["file_type"] == "PDF"

    def test_create_workflow_multiple_files(
        self, client, sample_txt_content, sample_pdf_content
    ):
        """Test creating workflow with multiple files."""
        files = [
            ("files", ("doc1.txt", io.BytesIO(sample_txt_content), "text/plain")),
            ("files", ("doc2.pdf", io.BytesIO(sample_pdf_content), "application/pdf")),
        ]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 201
        data = response.json()
        assert len(data["documents"]) == 2

    def test_start_workflow(self, client, sample_txt_content):
        """Test starting a workflow."""
        # Create workflow
        files = [("files", ("test.txt", io.BytesIO(sample_txt_content), "text/plain"))]
        create_response = client.post("/api/v1/workflows", files=files)
        workflow_id = create_response.json()["workflow_id"]

        # Start workflow
        response = client.post(f"/api/v1/workflows/{workflow_id}/start")

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "in_progress"
        assert "started_at" in data

    def test_get_workflow_status(self, client, sample_txt_content):
        """Test getting workflow status."""
        files = [("files", ("test.txt", io.BytesIO(sample_txt_content), "text/plain"))]
        create_response = client.post("/api/v1/workflows", files=files)
        workflow_id = create_response.json()["workflow_id"]

        response = client.get(f"/api/v1/workflows/{workflow_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["workflow_id"] == workflow_id
        assert data["status"] == "pending"
        assert "documents" in data
        assert "retry_counts" in data

    def test_list_workflows(self, client, sample_txt_content):
        """Test listing workflows with pagination."""
        # Create several workflows
        for i in range(5):
            files = [
                ("files", (f"test{i}.txt", io.BytesIO(sample_txt_content), "text/plain"))
            ]
            client.post("/api/v1/workflows", files=files)

        # List with pagination
        response = client.get("/api/v1/workflows?limit=2&offset=0")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert len(data["workflows"]) == 2
        assert data["limit"] == 2
        assert data["offset"] == 0

    def test_list_workflows_filter_status(self, client, sample_txt_content):
        """Test filtering workflows by status."""
        # Create workflows
        files1 = [("files", ("test1.txt", io.BytesIO(sample_txt_content), "text/plain"))]
        create_response = client.post("/api/v1/workflows", files=files1)
        workflow_id = create_response.json()["workflow_id"]

        files2 = [("files", ("test2.txt", io.BytesIO(sample_txt_content), "text/plain"))]
        client.post("/api/v1/workflows", files=files2)

        # Start one workflow
        client.post(f"/api/v1/workflows/{workflow_id}/start")

        # Filter by status
        response = client.get("/api/v1/workflows?status=in_progress")
        assert response.json()["total"] == 1

        response = client.get("/api/v1/workflows?status=pending")
        assert response.json()["total"] == 1

    def test_get_workflow_trace(self, client, sample_txt_content):
        """Test getting workflow execution trace."""
        files = [("files", ("test.txt", io.BytesIO(sample_txt_content), "text/plain"))]
        create_response = client.post("/api/v1/workflows", files=files)
        workflow_id = create_response.json()["workflow_id"]

        response = client.get(f"/api/v1/workflows/{workflow_id}/trace")

        assert response.status_code == 200
        data = response.json()
        assert data["workflow_id"] == workflow_id
        assert "executions" in data

    def test_get_workflow_output_not_completed(self, client, sample_txt_content):
        """Test getting output of incomplete workflow."""
        files = [("files", ("test.txt", io.BytesIO(sample_txt_content), "text/plain"))]
        create_response = client.post("/api/v1/workflows", files=files)
        workflow_id = create_response.json()["workflow_id"]

        response = client.get(f"/api/v1/workflows/{workflow_id}/output")

        assert response.status_code == 409
        assert response.json()["error"]["code"] == ErrorCode.WORKFLOW_NOT_COMPLETED


# --- Document Endpoint Tests ---


class TestDocumentEndpoints:
    """Integration tests for document endpoints."""

    def test_upload_document_to_workflow(self, client, sample_txt_content):
        """Test uploading document to existing workflow."""
        # Create workflow without files
        files = [("files", ("initial.txt", io.BytesIO(b"initial"), "text/plain"))]
        create_response = client.post("/api/v1/workflows", files=files)
        workflow_id = create_response.json()["workflow_id"]

        # Upload additional document
        file = ("file", ("additional.txt", io.BytesIO(sample_txt_content), "text/plain"))
        response = client.post(
            f"/api/v1/workflows/{workflow_id}/documents", files=[file]
        )

        assert response.status_code == 201
        data = response.json()
        assert data["workflow_id"] == workflow_id
        assert data["filename"] == "additional.txt"
        assert data["file_type"] == "TXT"
        assert "document_id" in data

    def test_upload_document_to_started_workflow_fails(
        self, client, sample_txt_content
    ):
        """Test that uploading to started workflow fails."""
        # Create and start workflow
        files = [("files", ("test.txt", io.BytesIO(sample_txt_content), "text/plain"))]
        create_response = client.post("/api/v1/workflows", files=files)
        workflow_id = create_response.json()["workflow_id"]
        client.post(f"/api/v1/workflows/{workflow_id}/start")

        # Try to upload
        file = ("file", ("new.txt", io.BytesIO(b"content"), "text/plain"))
        response = client.post(
            f"/api/v1/workflows/{workflow_id}/documents", files=[file]
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == ErrorCode.WORKFLOW_ALREADY_STARTED

    def test_get_document_metadata(self, client, sample_txt_content):
        """Test getting document metadata."""
        # Create workflow with document
        files = [("files", ("test.txt", io.BytesIO(sample_txt_content), "text/plain"))]
        create_response = client.post("/api/v1/workflows", files=files)
        document_id = create_response.json()["documents"][0]["document_id"]

        response = client.get(f"/api/v1/documents/{document_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["document_id"] == document_id
        assert data["filename"] == "test.txt"
        assert data["file_type"] == "TXT"
        assert "processing_status" in data

    def test_get_document_not_found(self, client):
        """Test getting non-existent document."""
        response = client.get("/api/v1/documents/nonexistent-id")

        assert response.status_code == 404

    def test_list_workflow_documents(self, client, sample_txt_content, sample_pdf_content):
        """Test listing all documents for a workflow."""
        # Create workflow with multiple documents
        files = [
            ("files", ("doc1.txt", io.BytesIO(sample_txt_content), "text/plain")),
            ("files", ("doc2.pdf", io.BytesIO(sample_pdf_content), "application/pdf")),
        ]
        create_response = client.post("/api/v1/workflows", files=files)
        workflow_id = create_response.json()["workflow_id"]

        response = client.get(f"/api/v1/workflows/{workflow_id}/documents/list")

        assert response.status_code == 200
        data = response.json()
        assert data["workflow_id"] == workflow_id
        assert data["total"] == 2
        assert len(data["documents"]) == 2


# --- Error Handling Tests ---


class TestErrorHandling:
    """Tests for error response formats and handling."""

    def test_error_response_structure(self, client):
        """Test error response has correct structure."""
        response = client.get("/api/v1/workflows/nonexistent-id")

        assert response.status_code == 404
        data = response.json()
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]

    def test_invalid_file_type_error(self, client):
        """Test invalid file type returns proper error."""
        files = [
            ("files", ("test.docx", io.BytesIO(b"content"), "application/vnd.openxmlformats"))
        ]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 400
        data = response.json()
        assert data["error"]["code"] == ErrorCode.INVALID_FILE_TYPE

    def test_file_too_large_error(self, client, test_settings):
        """Test file size limit error."""
        test_settings.MAX_FILE_SIZE_BYTES = 100
        large_content = b"x" * 200

        files = [("files", ("large.txt", io.BytesIO(large_content), "text/plain"))]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 413
        assert response.json()["error"]["code"] == ErrorCode.FILE_TOO_LARGE

    def test_workflow_not_found_error(self, client):
        """Test workflow not found error."""
        response = client.get("/api/v1/workflows/nonexistent-id")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == ErrorCode.WORKFLOW_NOT_FOUND

    def test_workflow_already_started_error(self, client, sample_txt_content):
        """Test workflow already started error."""
        # Create and start workflow
        files = [("files", ("test.txt", io.BytesIO(sample_txt_content), "text/plain"))]
        create_response = client.post("/api/v1/workflows", files=files)
        workflow_id = create_response.json()["workflow_id"]
        client.post(f"/api/v1/workflows/{workflow_id}/start")

        # Try to start again
        response = client.post(f"/api/v1/workflows/{workflow_id}/start")

        assert response.status_code == 409
        assert response.json()["error"]["code"] == ErrorCode.WORKFLOW_ALREADY_STARTED


# --- Full Workflow Integration Tests ---


class TestFullWorkflowIntegration:
    """End-to-end integration tests for complete workflows."""

    def test_complete_workflow_lifecycle(
        self, client, db_session, test_settings, sample_txt_content, sample_pdf_content
    ):
        """Test complete workflow lifecycle from creation to output."""
        # 1. Create workflow with multiple files
        files = [
            ("files", ("doc1.txt", io.BytesIO(sample_txt_content), "text/plain")),
            ("files", ("doc2.pdf", io.BytesIO(sample_pdf_content), "application/pdf")),
        ]
        create_response = client.post("/api/v1/workflows", files=files)

        assert create_response.status_code == 201
        workflow_id = create_response.json()["workflow_id"]

        # 2. Verify workflow status is pending
        status_response = client.get(f"/api/v1/workflows/{workflow_id}")
        assert status_response.json()["status"] == "pending"

        # 3. Start workflow
        start_response = client.post(f"/api/v1/workflows/{workflow_id}/start")
        assert start_response.status_code == 202
        assert start_response.json()["status"] == "in_progress"

        # 4. Verify workflow is in progress
        status_response = client.get(f"/api/v1/workflows/{workflow_id}")
        assert status_response.json()["status"] == "in_progress"

        # 5. List workflows shows in progress
        list_response = client.get("/api/v1/workflows?status=in_progress")
        assert list_response.json()["total"] >= 1

        # 6. Get trace (should be empty initially)
        trace_response = client.get(f"/api/v1/workflows/{workflow_id}/trace")
        assert trace_response.status_code == 200

    def test_workflow_with_completed_output(
        self, client, db_session, test_settings, sample_txt_content
    ):
        """Test workflow output retrieval after completion."""
        # Create workflow
        files = [("files", ("test.txt", io.BytesIO(sample_txt_content), "text/plain"))]
        create_response = client.post("/api/v1/workflows", files=files)
        workflow_id = create_response.json()["workflow_id"]

        # Manually complete the workflow and create output
        update_workflow_status(db_session, workflow_id, WorkflowStatus.COMPLETED)

        # Create mock output file
        output_path = persist_workflow_output(
            workflow_id=workflow_id,
            document_manifest=[
                {
                    "filename": "test.txt",
                    "file_type": "TXT",
                    "page_count": 1,
                    "processing_status": "processed",
                }
            ],
            csm_list=[
                {
                    "first_name": "Hans",
                    "last_name": "Mueller",
                    "classification": "CSM",
                    "reasoning": "Managing Director role",
                }
            ],
            non_csm_list=[],
            output_dir=test_settings.OUTPUT_DIR,
            db=db_session,
        )

        # Get output
        response = client.get(f"/api/v1/workflows/{workflow_id}/output")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"
