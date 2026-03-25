"""API integration tests for workflow endpoints.

Tests all endpoints defined in contracts/api.md:
- POST /workflows - Upload documents and create workflow
- POST /workflows/{id}/start - Start workflow processing
- GET /workflows/{id} - Get workflow status
- GET /workflows/{id}/output - Download JSON output
- GET /workflows - List workflow history with pagination
- GET /workflows/{id}/trace - Get detailed execution trace
"""

import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.dependencies import get_db, get_settings, Settings
from src.api.errors import ErrorCode
from src.api.main import app
from src.models.enums import WorkflowStatus
from src.services.database import Base
from src.services.storage import (
    WorkflowRunDB,
    create_workflow_run,
    update_workflow_status,
)


# --- Test Fixtures ---


@pytest.fixture
def test_db():
    """Create a test database with in-memory SQLite."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
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
    """Create minimal PDF content for testing."""
    # Minimal valid PDF
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
    return b"Test document content\nHans Mueller - Managing Director"


# --- Health Check Tests ---


class TestHealthCheck:
    """Tests for health check endpoint."""

    def test_health_check_returns_healthy(self, client):
        """Test health check endpoint returns healthy status."""
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


# --- POST /workflows Tests ---


class TestCreateWorkflow:
    """Tests for POST /workflows endpoint."""

    def test_create_workflow_with_txt_file(self, client, sample_txt_content):
        """Test creating workflow with a TXT file."""
        files = [("files", ("test.txt", io.BytesIO(sample_txt_content), "text/plain"))]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 201
        data = response.json()
        assert "workflow_id" in data
        assert data["status"] == "pending"
        assert len(data["documents"]) == 1
        assert data["documents"][0]["filename"] == "test.txt"
        assert data["documents"][0]["file_type"] == "TXT"

    def test_create_workflow_with_pdf_file(self, client, sample_pdf_content):
        """Test creating workflow with a PDF file."""
        files = [
            ("files", ("test.pdf", io.BytesIO(sample_pdf_content), "application/pdf"))
        ]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 201
        data = response.json()
        assert data["documents"][0]["file_type"] == "PDF"

    def test_create_workflow_with_multiple_files(
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

    def test_create_workflow_rejects_invalid_file_type(self, client):
        """Test that invalid file types are rejected."""
        files = [
            ("files", ("test.docx", io.BytesIO(b"content"), "application/vnd.openxmlformats"))
        ]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 400
        data = response.json()
        assert data["error"]["code"] == ErrorCode.INVALID_FILE_TYPE

    def test_create_workflow_rejects_large_file(self, client, test_settings):
        """Test that files exceeding size limit are rejected."""
        # Create content larger than limit
        test_settings.MAX_FILE_SIZE_BYTES = 100
        large_content = b"x" * 200

        files = [("files", ("large.txt", io.BytesIO(large_content), "text/plain"))]

        response = client.post("/api/v1/workflows", files=files)

        assert response.status_code == 413
        data = response.json()
        assert data["error"]["code"] == ErrorCode.FILE_TOO_LARGE


# --- POST /workflows/{id}/start Tests ---


class TestStartWorkflow:
    """Tests for POST /workflows/{id}/start endpoint."""

    def test_start_workflow_success(self, client, sample_txt_content):
        """Test starting a pending workflow."""
        # First create a workflow
        files = [("files", ("test.txt", io.BytesIO(sample_txt_content), "text/plain"))]
        create_response = client.post("/api/v1/workflows", files=files)
        workflow_id = create_response.json()["workflow_id"]

        # Start the workflow
        response = client.post(f"/api/v1/workflows/{workflow_id}/start")

        assert response.status_code == 202
        data = response.json()
        assert data["workflow_id"] == workflow_id
        assert data["status"] == "in_progress"
        assert "started_at" in data
        assert "message" in data

    def test_start_workflow_not_found(self, client):
        """Test starting a non-existent workflow."""
        response = client.post("/api/v1/workflows/nonexistent-id/start")

        assert response.status_code == 404
        data = response.json()
        assert data["error"]["code"] == ErrorCode.WORKFLOW_NOT_FOUND

    def test_start_workflow_already_started(self, client, sample_txt_content):
        """Test starting an already-started workflow."""
        # Create and start a workflow
        files = [("files", ("test.txt", io.BytesIO(sample_txt_content), "text/plain"))]
        create_response = client.post("/api/v1/workflows", files=files)
        workflow_id = create_response.json()["workflow_id"]
        client.post(f"/api/v1/workflows/{workflow_id}/start")

        # Try to start again
        response = client.post(f"/api/v1/workflows/{workflow_id}/start")

        assert response.status_code == 409
        data = response.json()
        assert data["error"]["code"] == ErrorCode.WORKFLOW_ALREADY_STARTED


# --- GET /workflows/{id} Tests ---


class TestGetWorkflowStatus:
    """Tests for GET /workflows/{id} endpoint."""

    def test_get_workflow_status_pending(self, client, sample_txt_content):
        """Test getting status of a pending workflow."""
        files = [("files", ("test.txt", io.BytesIO(sample_txt_content), "text/plain"))]
        create_response = client.post("/api/v1/workflows", files=files)
        workflow_id = create_response.json()["workflow_id"]

        response = client.get(f"/api/v1/workflows/{workflow_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["workflow_id"] == workflow_id
        assert data["status"] == "pending"
        assert "created_at" in data
        assert "documents" in data
        assert "retry_counts" in data

    def test_get_workflow_status_in_progress(self, client, sample_txt_content):
        """Test getting status of an in-progress workflow."""
        files = [("files", ("test.txt", io.BytesIO(sample_txt_content), "text/plain"))]
        create_response = client.post("/api/v1/workflows", files=files)
        workflow_id = create_response.json()["workflow_id"]
        client.post(f"/api/v1/workflows/{workflow_id}/start")

        response = client.get(f"/api/v1/workflows/{workflow_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "in_progress"

    def test_get_workflow_status_not_found(self, client):
        """Test getting status of a non-existent workflow."""
        response = client.get("/api/v1/workflows/nonexistent-id")

        assert response.status_code == 404
        data = response.json()
        assert data["error"]["code"] == ErrorCode.WORKFLOW_NOT_FOUND


# --- GET /workflows/{id}/output Tests ---


class TestGetWorkflowOutput:
    """Tests for GET /workflows/{id}/output endpoint."""

    def test_get_output_workflow_not_completed(self, client, sample_txt_content):
        """Test getting output of a non-completed workflow."""
        files = [("files", ("test.txt", io.BytesIO(sample_txt_content), "text/plain"))]
        create_response = client.post("/api/v1/workflows", files=files)
        workflow_id = create_response.json()["workflow_id"]

        response = client.get(f"/api/v1/workflows/{workflow_id}/output")

        assert response.status_code == 409
        data = response.json()
        assert data["error"]["code"] == ErrorCode.WORKFLOW_NOT_COMPLETED

    def test_get_output_workflow_not_found(self, client):
        """Test getting output of a non-existent workflow."""
        response = client.get("/api/v1/workflows/nonexistent-id/output")

        assert response.status_code == 404


# --- GET /workflows Tests ---


class TestListWorkflows:
    """Tests for GET /workflows endpoint."""

    def test_list_workflows_empty(self, client):
        """Test listing workflows when none exist."""
        response = client.get("/api/v1/workflows")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["workflows"] == []
        assert data["limit"] == 20
        assert data["offset"] == 0

    def test_list_workflows_with_data(self, client, sample_txt_content):
        """Test listing workflows with data."""
        # Create a few workflows
        for i in range(3):
            files = [
                ("files", (f"test{i}.txt", io.BytesIO(sample_txt_content), "text/plain"))
            ]
            client.post("/api/v1/workflows", files=files)

        response = client.get("/api/v1/workflows")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert len(data["workflows"]) == 3

    def test_list_workflows_with_pagination(self, client, sample_txt_content):
        """Test listing workflows with pagination."""
        # Create 5 workflows
        for i in range(5):
            files = [
                ("files", (f"test{i}.txt", io.BytesIO(sample_txt_content), "text/plain"))
            ]
            client.post("/api/v1/workflows", files=files)

        # Get first page
        response = client.get("/api/v1/workflows?limit=2&offset=0")
        data = response.json()
        assert data["total"] == 5
        assert len(data["workflows"]) == 2
        assert data["limit"] == 2
        assert data["offset"] == 0

        # Get second page
        response = client.get("/api/v1/workflows?limit=2&offset=2")
        data = response.json()
        assert len(data["workflows"]) == 2

    def test_list_workflows_filter_by_status(self, client, sample_txt_content):
        """Test filtering workflows by status."""
        # Create two workflows
        files = [("files", ("test1.txt", io.BytesIO(sample_txt_content), "text/plain"))]
        create_response = client.post("/api/v1/workflows", files=files)
        workflow_id = create_response.json()["workflow_id"]

        files = [("files", ("test2.txt", io.BytesIO(sample_txt_content), "text/plain"))]
        client.post("/api/v1/workflows", files=files)

        # Start one workflow
        client.post(f"/api/v1/workflows/{workflow_id}/start")

        # Filter by pending
        response = client.get("/api/v1/workflows?status=pending")
        data = response.json()
        assert data["total"] == 1

        # Filter by in_progress
        response = client.get("/api/v1/workflows?status=in_progress")
        data = response.json()
        assert data["total"] == 1


# --- GET /workflows/{id}/trace Tests ---


class TestGetWorkflowTrace:
    """Tests for GET /workflows/{id}/trace endpoint."""

    def test_get_trace_empty(self, client, sample_txt_content):
        """Test getting trace of a workflow with no executions."""
        files = [("files", ("test.txt", io.BytesIO(sample_txt_content), "text/plain"))]
        create_response = client.post("/api/v1/workflows", files=files)
        workflow_id = create_response.json()["workflow_id"]

        response = client.get(f"/api/v1/workflows/{workflow_id}/trace")

        assert response.status_code == 200
        data = response.json()
        assert data["workflow_id"] == workflow_id
        assert data["executions"] == []

    def test_get_trace_not_found(self, client):
        """Test getting trace of a non-existent workflow."""
        response = client.get("/api/v1/workflows/nonexistent-id/trace")

        assert response.status_code == 404


# --- Error Response Format Tests ---


class TestErrorResponseFormat:
    """Tests for error response format per contracts/api.md."""

    def test_error_response_has_correct_structure(self, client):
        """Test that error responses have the correct structure."""
        response = client.get("/api/v1/workflows/nonexistent-id")

        assert response.status_code == 404
        data = response.json()

        # Verify structure
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]

    def test_validation_error_format(self, client):
        """Test validation error response format."""
        # Try to create workflow without files
        response = client.post("/api/v1/workflows", files=[])

        # FastAPI returns 422 for validation errors
        assert response.status_code == 422
