"""Business logic services: document extraction, matching, storage."""

from .database import get_db, get_db_session, init_db
from .document import (
    DocumentExtractionError,
    DocumentInput,
    PageContent,
    extract_document,
    get_page_count,
)
from .matching import (
    compare_person_names,
    compute_similarity,
    find_duplicates,
    is_name_match,
    is_same_person,
    normalize_name,
)

__all__ = [
    # Database
    "get_db",
    "get_db_session",
    "init_db",
    # Document extraction
    "DocumentExtractionError",
    "DocumentInput",
    "PageContent",
    "extract_document",
    "get_page_count",
    # Matching
    "compare_person_names",
    "compute_similarity",
    "find_duplicates",
    "is_name_match",
    "is_same_person",
    "normalize_name",
]
