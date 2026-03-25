"""Document upload API routes.

Endpoints:
- POST /documents/upload - Upload a single document to a workflow
- GET /documents/{id} - Get document metadata
- GET /workflows/{workflow_id}/documents - List all documents for a workflow

For workflow-integrated uploads (creating a workflow with documents),
use the POST /workflows endpoint instead.
"""

import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from src.api.dependencies import AppSettings, DbSession, validate_file_size, validate_file_type
from src.api.errors import ErrorCode
from src.models.enums import FileType, WorkflowStatus
from src.services.storage import (
    create_uploaded_document,
    get_documents_for_workflow,
    get_uploaded_document,
    get_workflow_run,
)

router = APIRouter()


# --- Request/Response Models ---


class DocumentUploadResponse(BaseModel):
    """Response for single document upload."""

    document_id: str
    workflow_id: str
    filename: str
    file_type: str
    file_size_bytes: int
    page_count: int | None = None
    uploaded_at: datetime


class DocumentMetadataResponse(BaseModel):
    """Response for document metadata."""

    document_id: str
    workflow_id: str
    filename: str
    file_type: str
    file_size_bytes: int
    page_count: int | None = None
    processing_status: str
    error_message: str | None = None


class DocumentListResponse(BaseModel):
    """Response for document list."""

    workflow_id: str
    documents: list[DocumentMetadataResponse]
    total: int


# --- Helper Functions ---


def get_page_count(file_path: Path, file_type: FileType) -> int | None:
    """Get page count for a document."""
    if file_type == FileType.PDF:
        try:
            import pdfplumber

            with pdfplumber.open(file_path) as pdf:
                return len(pdf.pages)
        except Exception:
            return None
    elif file_type == FileType.TXT:
        return 1
    return None


def determine_file_type(filename: str) -> FileType:
    """Determine file type from filename extension."""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return FileType.PDF
    return FileType.TXT


def raise_document_not_found(document_id: str):
    """Raise 404 for document not found."""
    raise HTTPException(
        status_code=404,
        detail={
            "code": ErrorCode.WORKFLOW_NOT_FOUND,
            "message": f"Document with ID {document_id} not found",
        },
    )


def raise_workflow_not_found(workflow_id: str):
    """Raise 404 for workflow not found."""
    raise HTTPException(
        status_code=404,
        detail={
            "code": ErrorCode.WORKFLOW_NOT_FOUND,
            "message": f"Workflow with ID {workflow_id} not found",
        },
    )


# --- Endpoints ---


@router.post(
    "/workflows/{workflow_id}/documents",
    response_model=DocumentUploadResponse,
    status_code=201,
)
async def upload_document_to_workflow(
    workflow_id: str,
    db: DbSession,
    settings: AppSettings,
    file: UploadFile = File(..., description="PDF or TXT file"),
) -> DocumentUploadResponse:
    """Upload a document to an existing workflow.

    Adds a document to a pending workflow. The workflow must be in PENDING status.
    Supports PDF and TXT files up to the configured maximum size.
    """
    # Verify workflow exists and is in PENDING status
    workflow = get_workflow_run(db, workflow_id)
    if not workflow:
        raise_workflow_not_found(workflow_id)

    if workflow.status != WorkflowStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail={
                "code": ErrorCode.WORKFLOW_ALREADY_STARTED,
                "message": f"Cannot add documents to workflow in {workflow.status.value} status",
            },
        )

    filename = file.filename or f"document_{uuid.uuid4()}"

    # Validate file type
    if not validate_file_type(filename, file.content_type, settings):
        raise HTTPException(
            status_code=400,
            detail={
                "code": ErrorCode.INVALID_FILE_TYPE,
                "message": f"Invalid file type for {filename}. Only PDF and TXT files are allowed.",
            },
        )

    # Read file content
    content = await file.read()

    # Validate file size
    if not validate_file_size(len(content), settings):
        raise HTTPException(
            status_code=413,
            detail={
                "code": ErrorCode.FILE_TOO_LARGE,
                "message": f"File {filename} exceeds maximum size of {settings.MAX_FILE_SIZE_MB}MB",
            },
        )

    # Create workflow directory
    workflow_dir = settings.UPLOAD_DIR / workflow_id
    workflow_dir.mkdir(parents=True, exist_ok=True)

    # Determine file type
    file_type = determine_file_type(filename)

    # Save file
    file_path = workflow_dir / filename
    with open(file_path, "wb") as f:
        f.write(content)

    # Get page count
    page_count = get_page_count(file_path, file_type)

    # Create document record
    doc = create_uploaded_document(
        db=db,
        workflow_run_id=workflow_id,
        filename=filename,
        file_type=file_type,
        file_path=str(file_path),
        file_size_bytes=len(content),
        page_count=page_count,
    )

    return DocumentUploadResponse(
        document_id=doc.id,
        workflow_id=workflow_id,
        filename=filename,
        file_type=file_type.value,
        file_size_bytes=len(content),
        page_count=page_count,
        uploaded_at=datetime.utcnow(),
    )


@router.get("/documents/{document_id}", response_model=DocumentMetadataResponse)
async def get_document(
    document_id: str,
    db: DbSession,
) -> DocumentMetadataResponse:
    """Get document metadata.

    Returns metadata about a previously uploaded document.
    """
    doc = get_uploaded_document(db, document_id)
    if not doc:
        raise_document_not_found(document_id)

    return DocumentMetadataResponse(
        document_id=doc.id,
        workflow_id=doc.workflow_run_id,
        filename=doc.filename,
        file_type=doc.file_type.value,
        file_size_bytes=doc.file_size_bytes,
        page_count=doc.page_count,
        processing_status=doc.processing_status.value,
        error_message=doc.error_message,
    )


@router.get(
    "/workflows/{workflow_id}/documents/list",
    response_model=DocumentListResponse,
)
async def list_workflow_documents(
    workflow_id: str,
    db: DbSession,
) -> DocumentListResponse:
    """List all documents for a workflow.

    Returns all documents that have been uploaded to a specific workflow.
    """
    # Verify workflow exists
    workflow = get_workflow_run(db, workflow_id)
    if not workflow:
        raise_workflow_not_found(workflow_id)

    documents = get_documents_for_workflow(db, workflow_id)

    return DocumentListResponse(
        workflow_id=workflow_id,
        documents=[
            DocumentMetadataResponse(
                document_id=doc.id,
                workflow_id=doc.workflow_run_id,
                filename=doc.filename,
                file_type=doc.file_type.value,
                file_size_bytes=doc.file_size_bytes,
                page_count=doc.page_count,
                processing_status=doc.processing_status.value,
                error_message=doc.error_message,
            )
            for doc in documents
        ],
        total=len(documents),
    )
