"""Workflow API routes.

Endpoints:
- POST /workflows - Upload documents and create workflow
- POST /workflows/{id}/start - Start workflow processing
- GET /workflows/{id} - Get workflow status
- GET /workflows/{id}/output - Download JSON output
- GET /workflows - List workflow history with pagination
- GET /workflows/{id}/trace - Get detailed execution trace
"""

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from src.api.dependencies import AppSettings, DbSession, validate_file_size, validate_file_type
from src.api.errors import ErrorCode
from src.models.enums import FileType, WorkflowStatus
from src.services.storage import (
    WorkflowRunDB,
    create_uploaded_document,
    create_workflow_run,
    get_workflow_run,
    load_workflow_output,
    update_workflow_status,
)

router = APIRouter()


# --- Request/Response Models ---


class DocumentInfo(BaseModel):
    """Document information in workflow response."""

    document_id: str
    filename: str
    file_type: str
    page_count: int | None = None


class WorkflowCreateResponse(BaseModel):
    """Response for workflow creation."""

    workflow_id: str
    status: str
    created_at: datetime
    documents: list[DocumentInfo]


class WorkflowStartResponse(BaseModel):
    """Response for workflow start."""

    workflow_id: str
    status: str
    started_at: datetime
    message: str


class DocumentStatusInfo(BaseModel):
    """Document status in workflow status response."""

    filename: str
    processing_status: str


class WorkflowSummaryInfo(BaseModel):
    """Summary statistics for a workflow."""

    total_persons_extracted: int = 0
    csm_count: int = 0
    non_csm_count: int = 0
    conflicts_detected: int = 0


class RetryCountsInfo(BaseModel):
    """Retry counts per agent."""

    extractor: int = 0
    reconciler: int = 0
    classifier: int = 0


class WorkflowStatusResponse(BaseModel):
    """Response for workflow status."""

    workflow_id: str
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    documents: list[DocumentStatusInfo]
    summary: WorkflowSummaryInfo | None = None
    current_step: str | None = None
    retry_counts: RetryCountsInfo


class WorkflowListItemResponse(BaseModel):
    """Workflow item in list response."""

    workflow_id: str
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    document_count: int
    person_count: int


class WorkflowListResponse(BaseModel):
    """Response for workflow list."""

    total: int
    limit: int
    offset: int
    workflows: list[WorkflowListItemResponse]


class ExecutionTraceItem(BaseModel):
    """Execution trace item."""

    execution_id: str
    agent_name: str
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = None
    status: str
    retry_count: int = 0
    input_summary: str | None = None
    output_summary: str | None = None
    critic_feedback: str | None = None
    decision: str | None = None


class WorkflowTraceResponse(BaseModel):
    """Response for workflow trace."""

    workflow_id: str
    executions: list[ExecutionTraceItem]


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


def get_retry_counts(workflow: WorkflowRunDB) -> RetryCountsInfo:
    """Get retry counts from agent executions."""
    counts = {"extractor": 0, "reconciler": 0, "classifier": 0}
    for execution in workflow.agent_executions:
        if execution.agent_name in counts:
            counts[execution.agent_name] = max(
                counts[execution.agent_name], execution.retry_count
            )
    return RetryCountsInfo(**counts)


def get_workflow_summary(workflow: WorkflowRunDB) -> WorkflowSummaryInfo | None:
    """Get workflow summary from persons."""
    if workflow.status != WorkflowStatus.COMPLETED:
        return None

    total = len(workflow.persons)
    csm = sum(
        1
        for p in workflow.persons
        if p.classification_result and p.classification_result.classification.value == "CSM"
    )
    non_csm = sum(
        1
        for p in workflow.persons
        if p.classification_result
        and p.classification_result.classification.value == "NON_CSM"
    )
    conflicts = sum(1 for p in workflow.persons if p.has_conflicts)

    return WorkflowSummaryInfo(
        total_persons_extracted=total,
        csm_count=csm,
        non_csm_count=non_csm,
        conflicts_detected=conflicts,
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


@router.post("/workflows", response_model=WorkflowCreateResponse, status_code=201)
async def create_workflow(
    db: DbSession,
    settings: AppSettings,
    files: list[UploadFile] = File(..., description="PDF or TXT files"),
) -> WorkflowCreateResponse:
    """Upload documents and create a new workflow.

    Creates a new workflow run and stores the uploaded documents for processing.
    """
    if not files:
        raise HTTPException(
            status_code=400,
            detail={
                "code": ErrorCode.VALIDATION_ERROR,
                "message": "At least one file is required",
            },
        )

    # Validate files first
    for file in files:
        if not validate_file_type(file.filename or "", file.content_type, settings):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": ErrorCode.INVALID_FILE_TYPE,
                    "message": f"Invalid file type for {file.filename}. Only PDF and TXT files are allowed.",
                },
            )

    # Create workflow
    workflow = create_workflow_run(db)
    workflow_dir = settings.UPLOAD_DIR / workflow.id
    workflow_dir.mkdir(parents=True, exist_ok=True)

    documents: list[DocumentInfo] = []

    for file in files:
        # Read file content
        content = await file.read()

        # Validate file size
        if not validate_file_size(len(content), settings):
            raise HTTPException(
                status_code=413,
                detail={
                    "code": ErrorCode.FILE_TOO_LARGE,
                    "message": f"File {file.filename} exceeds maximum size of {settings.MAX_FILE_SIZE_MB}MB",
                },
            )

        # Determine file type
        filename = file.filename or f"document_{uuid.uuid4()}"
        ext = Path(filename).suffix.lower()
        file_type = FileType.PDF if ext == ".pdf" else FileType.TXT

        # Save file
        file_path = workflow_dir / filename
        with open(file_path, "wb") as f:
            f.write(content)

        # Get page count
        page_count = get_page_count(file_path, file_type)

        # Create document record
        doc = create_uploaded_document(
            db=db,
            workflow_run_id=workflow.id,
            filename=filename,
            file_type=file_type,
            file_path=str(file_path),
            file_size_bytes=len(content),
            page_count=page_count,
        )

        documents.append(
            DocumentInfo(
                document_id=doc.id,
                filename=filename,
                file_type=file_type.value,
                page_count=page_count,
            )
        )

    return WorkflowCreateResponse(
        workflow_id=workflow.id,
        status=workflow.status.value,
        created_at=workflow.created_at,
        documents=documents,
    )


@router.post(
    "/workflows/{workflow_id}/start",
    response_model=WorkflowStartResponse,
    status_code=202,
)
async def start_workflow(
    workflow_id: str,
    db: DbSession,
) -> WorkflowStartResponse:
    """Start workflow processing.

    Triggers the document processing pipeline for the specified workflow.
    """
    workflow = get_workflow_run(db, workflow_id)
    if not workflow:
        raise_workflow_not_found(workflow_id)

    if workflow.status != WorkflowStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail={
                "code": ErrorCode.WORKFLOW_ALREADY_STARTED,
                "message": f"Workflow {workflow_id} has already been started (status: {workflow.status.value})",
            },
        )

    # Update status to in_progress
    workflow = update_workflow_status(db, workflow_id, WorkflowStatus.IN_PROGRESS)

    # TODO: Trigger actual workflow processing in background
    # For now, we just mark it as started

    return WorkflowStartResponse(
        workflow_id=workflow_id,
        status=workflow.status.value,
        started_at=workflow.started_at,
        message="Workflow started. Connect to WebSocket for real-time updates.",
    )


@router.get("/workflows/{workflow_id}", response_model=WorkflowStatusResponse)
async def get_workflow_status(
    workflow_id: str,
    db: DbSession,
) -> WorkflowStatusResponse:
    """Get workflow status and summary."""
    workflow = get_workflow_run(db, workflow_id)
    if not workflow:
        raise_workflow_not_found(workflow_id)

    documents = [
        DocumentStatusInfo(
            filename=doc.filename,
            processing_status=doc.processing_status.value,
        )
        for doc in workflow.documents
    ]

    # Determine current step
    current_step = None
    if workflow.status == WorkflowStatus.IN_PROGRESS:
        # Find the most recent agent execution
        if workflow.agent_executions:
            latest = max(workflow.agent_executions, key=lambda x: x.started_at)
            if latest.status == "running":
                current_step = latest.agent_name

    return WorkflowStatusResponse(
        workflow_id=workflow_id,
        status=workflow.status.value,
        created_at=workflow.created_at,
        completed_at=workflow.completed_at,
        duration_seconds=workflow.duration_seconds,
        documents=documents,
        summary=get_workflow_summary(workflow),
        current_step=current_step,
        retry_counts=get_retry_counts(workflow),
    )


@router.get("/workflows/{workflow_id}/output")
async def get_workflow_output(
    workflow_id: str,
    db: DbSession,
) -> FileResponse:
    """Download workflow output as JSON file."""
    workflow = get_workflow_run(db, workflow_id)
    if not workflow:
        raise_workflow_not_found(workflow_id)

    if workflow.status != WorkflowStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail={
                "code": ErrorCode.WORKFLOW_NOT_COMPLETED,
                "message": f"Workflow {workflow_id} is not yet completed (status: {workflow.status.value})",
            },
        )

    if not workflow.output_json_path:
        raise HTTPException(
            status_code=404,
            detail={
                "code": ErrorCode.WORKFLOW_NOT_FOUND,
                "message": f"Output file not found for workflow {workflow_id}",
            },
        )

    output_path = Path(workflow.output_json_path)
    if not output_path.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "code": ErrorCode.WORKFLOW_NOT_FOUND,
                "message": f"Output file not found at {workflow.output_json_path}",
            },
        )

    return FileResponse(
        path=output_path,
        filename=f"workflow_{workflow_id[:8]}_output.json",
        media_type="application/json",
    )


@router.get("/workflows", response_model=WorkflowListResponse)
async def list_workflows(
    db: DbSession,
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(20, ge=1, le=100, description="Results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    sort: str = Query("-created_at", description="Sort field (prefix - for descending)"),
) -> WorkflowListResponse:
    """List workflow history with pagination."""
    from sqlalchemy import desc, asc

    query = db.query(WorkflowRunDB)

    # Filter by status
    if status:
        try:
            status_enum = WorkflowStatus(status)
            query = query.filter(WorkflowRunDB.status == status_enum)
        except ValueError:
            pass  # Invalid status, ignore filter

    # Count total before pagination
    total = query.count()

    # Sort
    descending = sort.startswith("-")
    sort_field = sort.lstrip("-")
    if hasattr(WorkflowRunDB, sort_field):
        column = getattr(WorkflowRunDB, sort_field)
        query = query.order_by(desc(column) if descending else asc(column))
    else:
        query = query.order_by(desc(WorkflowRunDB.created_at))

    # Paginate
    workflows = query.offset(offset).limit(limit).all()

    items = [
        WorkflowListItemResponse(
            workflow_id=w.id,
            status=w.status.value,
            created_at=w.created_at,
            completed_at=w.completed_at,
            duration_seconds=w.duration_seconds,
            document_count=len(w.documents),
            person_count=len(w.persons),
        )
        for w in workflows
    ]

    return WorkflowListResponse(
        total=total,
        limit=limit,
        offset=offset,
        workflows=items,
    )


@router.get("/workflows/{workflow_id}/trace", response_model=WorkflowTraceResponse)
async def get_workflow_trace(
    workflow_id: str,
    db: DbSession,
) -> WorkflowTraceResponse:
    """Get detailed execution trace for observability."""
    workflow = get_workflow_run(db, workflow_id)
    if not workflow:
        raise_workflow_not_found(workflow_id)

    executions = []
    for execution in sorted(workflow.agent_executions, key=lambda x: x.started_at):
        # Build input/output summaries
        input_summary = None
        output_summary = None

        if execution.input_payload:
            if "documents" in execution.input_payload:
                doc_count = len(execution.input_payload.get("documents", []))
                input_summary = f"Processing {doc_count} document(s)"
            elif "persons" in execution.input_payload:
                person_count = len(execution.input_payload.get("persons", []))
                input_summary = f"Processing {person_count} person(s)"

        if execution.output_payload:
            if "persons" in execution.output_payload:
                person_count = len(execution.output_payload.get("persons", []))
                output_summary = f"Processed {person_count} person(s)"
            elif "decision" in execution.output_payload:
                output_summary = f"Decision: {execution.output_payload.get('decision')}"

        # Get critic feedback
        critic_feedback = None
        decision = None
        if execution.critic_feedback:
            critic_feedback = execution.critic_feedback.suggested_corrections
            decision = execution.critic_feedback.decision.value

        executions.append(
            ExecutionTraceItem(
                execution_id=execution.id,
                agent_name=execution.agent_name,
                started_at=execution.started_at,
                ended_at=execution.ended_at,
                duration_ms=execution.duration_ms,
                status=execution.status,
                retry_count=execution.retry_count,
                input_summary=input_summary,
                output_summary=output_summary,
                critic_feedback=critic_feedback,
                decision=decision,
            )
        )

    return WorkflowTraceResponse(
        workflow_id=workflow_id,
        executions=executions,
    )
