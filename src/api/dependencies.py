"""Dependency injection for FastAPI endpoints.

This module provides:
- Database session dependency
- Storage service dependency
- Workflow service dependency
"""

from collections.abc import Generator
from pathlib import Path
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from src.services.database import SessionLocal


# --- Database Session ---


def get_db() -> Generator[Session, None, None]:
    """Provide a database session for request scope."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Type alias for dependency injection
DbSession = Annotated[Session, Depends(get_db)]


# --- Configuration ---


class Settings:
    """Application settings."""

    # File upload settings
    MAX_FILE_SIZE_MB: int = 50
    MAX_FILE_SIZE_BYTES: int = MAX_FILE_SIZE_MB * 1024 * 1024
    ALLOWED_FILE_TYPES: set[str] = {"application/pdf", "text/plain"}
    ALLOWED_EXTENSIONS: set[str] = {".pdf", ".txt"}

    # Storage paths
    UPLOAD_DIR: Path = Path("uploads")
    OUTPUT_DIR: Path = Path("outputs")

    # Workflow settings
    MAX_RETRIES: int = 4

    def __init__(self):
        """Initialize settings and create directories."""
        self.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    """Get application settings (singleton)."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


# Type alias for settings dependency
AppSettings = Annotated[Settings, Depends(get_settings)]


# --- File Upload Utilities ---


def validate_file_type(filename: str, content_type: str | None, settings: Settings) -> bool:
    """Validate file type based on extension and content type."""
    from pathlib import Path as P

    ext = P(filename).suffix.lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        return False

    if content_type and content_type not in settings.ALLOWED_FILE_TYPES:
        # Allow common variations
        if ext == ".pdf" and "pdf" in content_type.lower():
            return True
        if ext == ".txt" and "text" in content_type.lower():
            return True
        return False

    return True


def validate_file_size(file_size: int, settings: Settings) -> bool:
    """Validate file size is within limits."""
    return file_size <= settings.MAX_FILE_SIZE_BYTES
