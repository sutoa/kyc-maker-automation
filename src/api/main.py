"""FastAPI application for KYC Document Processing.

This module provides:
- FastAPI application with CORS middleware
- Standard error handlers per contracts/api.md
- Uvicorn configuration for development and production
"""

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.core.workflow import compile_workflow
from src.services.database import init_db

from .errors import ErrorCode, ErrorDetail, ErrorResponse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# --- Application Lifecycle ---


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown."""
    # Startup
    logger.info("Starting KYC Document Processing API...")
    init_db()
    logger.info("Database initialized.")
    app.state.compiled_workflow = compile_workflow()
    logger.info("Workflow compiled from YAML config.")
    yield
    # Shutdown
    logger.info("Shutting down KYC Document Processing API...")


# --- Create Application ---

app = FastAPI(
    title="KYC Document Processing API",
    description="REST API for processing KYC documents and classifying persons as CSM/NON_CSM",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    openapi_url="/api/v1/openapi.json",
)

# --- CORS Configuration ---

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Error Handlers ---


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle HTTP exceptions with standard error format."""
    # Map status codes to error codes
    code_mapping = {
        400: ErrorCode.VALIDATION_ERROR,
        404: ErrorCode.WORKFLOW_NOT_FOUND,
        409: ErrorCode.WORKFLOW_ALREADY_STARTED,
        413: ErrorCode.FILE_TOO_LARGE,
        503: ErrorCode.LLM_SERVICE_UNAVAILABLE,
    }

    error_code = code_mapping.get(exc.status_code, ErrorCode.INTERNAL_ERROR)

    # Use detail if it's a specific error code
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        error_code = exc.detail["code"]
        message = exc.detail.get("message", str(exc.detail))
        details = exc.detail.get("details")
    else:
        message = str(exc.detail)
        details = None

    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=ErrorDetail(
                code=error_code,
                message=message,
                details=details,
            )
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions with standard error format."""
    logger.exception("Unexpected error occurred")
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error=ErrorDetail(
                code=ErrorCode.INTERNAL_ERROR,
                message="An unexpected error occurred",
                details=str(exc) if app.debug else None,
            )
        ).model_dump(),
    )


# --- Include Routers ---
# Import here to avoid circular imports
from .routes.documents import router as documents_router
from .routes.workflows import router as workflows_router

app.include_router(
    workflows_router,
    prefix="/api/v1",
    tags=["workflows"],
)

app.include_router(
    documents_router,
    prefix="/api/v1",
    tags=["documents"],
)


# --- Health Check ---


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


# --- WebSocket Endpoint ---


from .websocket import websocket_endpoint


@app.websocket("/ws/workflows/{workflow_id}")
async def websocket_workflow(websocket: WebSocket, workflow_id: str):
    """WebSocket endpoint for real-time workflow updates.

    Connect to this endpoint to receive real-time updates about workflow progress.

    Events sent:
    - connected: Connection established
    - agent_started: Agent begins processing
    - agent_completed: Agent finished successfully
    - critic_decision: Critic made a decision
    - retry_triggered: Agent retry initiated
    - workflow_completed: Workflow finished successfully
    - workflow_failed: Workflow failed with error
    """
    await websocket_endpoint(websocket, workflow_id)


# --- Uvicorn Configuration ---


def run_development():
    """Run the application in development mode with hot reload."""
    uvicorn.run(
        "src.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )


def run_production():
    """Run the application in production mode."""
    uvicorn.run(
        "src.api.main:app",
        host="0.0.0.0",
        port=8000,
        workers=4,
        log_level="warning",
    )


if __name__ == "__main__":
    run_development()
