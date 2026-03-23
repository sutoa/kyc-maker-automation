"""Document extraction service for PDF and TXT files.

This module provides text extraction from PDF and TXT documents
with page boundary tracking for source provenance (FR-006).

Primary extraction: pdfplumber (structured text with page awareness)
Fallback: PyMuPDF (for problematic PDFs, OCR-capable)
"""

import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PageContent(BaseModel):
    """Content extracted from a single page."""

    page_number: int = Field(..., ge=1, description="1-indexed page number")
    text: str = Field(..., description="Extracted text content")


class DocumentInput(BaseModel):
    """Extracted content from a document with page boundaries."""

    document_id: str = Field(..., description="UUID of the document")
    filename: str = Field(..., description="Original filename")
    file_type: Literal["PDF", "TXT"] = Field(..., description="File type")
    content: str = Field(..., description="Full extracted text with page markers")
    pages: list[PageContent] = Field(..., description="Page-by-page content")
    page_count: int = Field(..., ge=0, description="Total number of pages")


class DocumentExtractionError(Exception):
    """Raised when document extraction fails."""

    pass


def extract_pdf_pdfplumber(file_path: Path) -> tuple[list[PageContent], str]:
    """Extract text from PDF using pdfplumber.

    Args:
        file_path: Path to the PDF file.

    Returns:
        Tuple of (list of PageContent, combined text with markers).

    Raises:
        DocumentExtractionError: If extraction fails.
    """
    try:
        import pdfplumber
    except ImportError:
        raise DocumentExtractionError(
            "pdfplumber not installed. Install with: pip install pdfplumber"
        )

    pages: list[PageContent] = []
    combined_text_parts: list[str] = []

    try:
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                pages.append(PageContent(page_number=i, text=text))
                # Add page marker for combined text
                combined_text_parts.append(f"[PAGE {i}]\n{text}")

        combined_text = "\n\n".join(combined_text_parts)
        return pages, combined_text

    except Exception as e:
        logger.warning(f"pdfplumber extraction failed: {e}")
        raise DocumentExtractionError(f"pdfplumber extraction failed: {e}")


def extract_pdf_pymupdf(file_path: Path) -> tuple[list[PageContent], str]:
    """Extract text from PDF using PyMuPDF (fallback).

    Args:
        file_path: Path to the PDF file.

    Returns:
        Tuple of (list of PageContent, combined text with markers).

    Raises:
        DocumentExtractionError: If extraction fails.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise DocumentExtractionError(
            "PyMuPDF not installed. Install with: pip install PyMuPDF"
        )

    pages: list[PageContent] = []
    combined_text_parts: list[str] = []

    try:
        doc = fitz.open(file_path)
        for i, page in enumerate(doc, start=1):
            text = page.get_text()
            pages.append(PageContent(page_number=i, text=text))
            combined_text_parts.append(f"[PAGE {i}]\n{text}")
        doc.close()

        combined_text = "\n\n".join(combined_text_parts)
        return pages, combined_text

    except Exception as e:
        logger.warning(f"PyMuPDF extraction failed: {e}")
        raise DocumentExtractionError(f"PyMuPDF extraction failed: {e}")


def extract_pdf(file_path: Path) -> tuple[list[PageContent], str]:
    """Extract text from PDF with fallback.

    Uses pdfplumber as primary extractor, falls back to PyMuPDF
    if pdfplumber fails.

    Args:
        file_path: Path to the PDF file.

    Returns:
        Tuple of (list of PageContent, combined text with markers).

    Raises:
        DocumentExtractionError: If both extractors fail.
    """
    try:
        return extract_pdf_pdfplumber(file_path)
    except DocumentExtractionError as e:
        logger.info(f"Falling back to PyMuPDF: {e}")
        try:
            return extract_pdf_pymupdf(file_path)
        except DocumentExtractionError:
            raise DocumentExtractionError(
                f"Failed to extract PDF with both pdfplumber and PyMuPDF: {file_path}"
            )


def extract_txt(file_path: Path) -> tuple[list[PageContent], str]:
    """Extract text from TXT file.

    TXT files are treated as a single page since they don't have
    inherent page structure.

    Args:
        file_path: Path to the TXT file.

    Returns:
        Tuple of (list of PageContent, combined text with markers).

    Raises:
        DocumentExtractionError: If file cannot be read.
    """
    try:
        # Try UTF-8 first, then fall back to other encodings
        encodings = ["utf-8", "utf-8-sig", "latin-1", "cp1252"]
        text = None

        for encoding in encodings:
            try:
                text = file_path.read_text(encoding=encoding)
                break
            except UnicodeDecodeError:
                continue

        if text is None:
            raise DocumentExtractionError(
                f"Could not decode TXT file with any supported encoding: {file_path}"
            )

        pages = [PageContent(page_number=1, text=text)]
        combined_text = f"[PAGE 1]\n{text}"

        return pages, combined_text

    except Exception as e:
        if isinstance(e, DocumentExtractionError):
            raise
        raise DocumentExtractionError(f"Failed to read TXT file: {e}")


def extract_document(
    file_path: str | Path,
    document_id: str,
    filename: str | None = None,
) -> DocumentInput:
    """Extract text content from a document.

    Args:
        file_path: Path to the document file.
        document_id: UUID for the document.
        filename: Original filename (defaults to file name from path).

    Returns:
        DocumentInput with extracted content and page information.

    Raises:
        DocumentExtractionError: If extraction fails.
        ValueError: If file type is not supported.
    """
    path = Path(file_path)

    if not path.exists():
        raise DocumentExtractionError(f"File not found: {file_path}")

    filename = filename or path.name
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        file_type = "PDF"
        pages, content = extract_pdf(path)
    elif suffix == ".txt":
        file_type = "TXT"
        pages, content = extract_txt(path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}. Supported: .pdf, .txt")

    return DocumentInput(
        document_id=document_id,
        filename=filename,
        file_type=file_type,
        content=content,
        pages=pages,
        page_count=len(pages),
    )


def get_page_count(file_path: str | Path) -> int:
    """Get the page count for a document without full extraction.

    Args:
        file_path: Path to the document file.

    Returns:
        Number of pages in the document.

    Raises:
        DocumentExtractionError: If page count cannot be determined.
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".txt":
        return 1

    if suffix == ".pdf":
        try:
            import pdfplumber

            with pdfplumber.open(path) as pdf:
                return len(pdf.pages)
        except Exception:
            pass

        try:
            import fitz

            doc = fitz.open(path)
            count = len(doc)
            doc.close()
            return count
        except Exception:
            pass

        raise DocumentExtractionError(f"Could not determine page count: {file_path}")

    raise ValueError(f"Unsupported file type: {suffix}")
