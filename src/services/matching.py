"""Fuzzy name matching service for duplicate detection.

This module provides name normalization and fuzzy matching functionality
for detecting duplicate persons across documents, with special handling
for German names (umlauts, common variations).

Uses Jaro-Winkler similarity with a 0.85 threshold as per research.md.
"""

from dataclasses import dataclass

from rapidfuzz.distance import JaroWinkler
from unidecode import unidecode

# Default similarity threshold for duplicate detection
DEFAULT_THRESHOLD = 0.85


def normalize_name(name: str) -> str:
    """Normalize a name for comparison.

    Normalization steps:
    1. Convert to lowercase
    2. Strip whitespace
    3. ASCII-fold (convert umlauts: ü → ue, etc.)

    Args:
        name: The name to normalize.

    Returns:
        Normalized name string.
    """
    if not name:
        return ""

    # Lowercase and strip
    normalized = name.lower().strip()

    # ASCII-fold using unidecode (handles ü → u, ä → a, ö → o, ß → ss)
    # Note: unidecode converts ü to u, not ue, which is acceptable
    # for matching purposes
    normalized = unidecode(normalized)

    return normalized


def compute_similarity(name1: str, name2: str) -> float:
    """Compute Jaro-Winkler similarity between two names.

    Args:
        name1: First name (will be normalized).
        name2: Second name (will be normalized).

    Returns:
        Similarity score between 0.0 and 1.0.
    """
    norm1 = normalize_name(name1)
    norm2 = normalize_name(name2)

    if not norm1 or not norm2:
        return 0.0

    # Jaro-Winkler gives higher scores to strings with matching prefixes,
    # which is ideal for name comparison
    # JaroWinkler.normalized_similarity returns 0-1
    return JaroWinkler.normalized_similarity(norm1, norm2)


def is_name_match(name1: str, name2: str, threshold: float = DEFAULT_THRESHOLD) -> bool:
    """Check if two names are similar enough to be a match.

    Args:
        name1: First name.
        name2: Second name.
        threshold: Minimum similarity score (0.0-1.0) for a match.

    Returns:
        True if similarity >= threshold.
    """
    return compute_similarity(name1, name2) >= threshold


@dataclass
class PersonNameComparison:
    """Result of comparing two person names."""

    first_name_similarity: float
    last_name_similarity: float
    full_name_similarity: float
    is_match: bool
    match_score: float


def compare_person_names(
    first_name1: str,
    last_name1: str,
    first_name2: str,
    last_name2: str,
    threshold: float = DEFAULT_THRESHOLD,
) -> PersonNameComparison:
    """Compare two person names for potential duplicate detection.

    Computes similarity for first name, last name, and combined full name.

    Args:
        first_name1: First person's first name.
        last_name1: First person's last name.
        first_name2: Second person's first name.
        last_name2: Second person's last name.
        threshold: Minimum similarity for considering a match.

    Returns:
        PersonNameComparison with detailed similarity scores.
    """
    first_sim = compute_similarity(first_name1, first_name2)
    last_sim = compute_similarity(last_name1, last_name2)

    # Full name comparison (handles name order variations)
    full1 = f"{first_name1} {last_name1}"
    full2 = f"{first_name2} {last_name2}"
    full_sim = compute_similarity(full1, full2)

    # Match score is the average of first and last name similarity
    # This ensures both parts of the name must be similar
    match_score = (first_sim + last_sim) / 2

    # Consider it a match only if BOTH first and last names meet threshold
    # The full name comparison is used for match_score but not for the match decision
    # This prevents false positives when only one name matches
    is_match = first_sim >= threshold and last_sim >= threshold

    return PersonNameComparison(
        first_name_similarity=first_sim,
        last_name_similarity=last_sim,
        full_name_similarity=full_sim,
        is_match=is_match,
        match_score=match_score,
    )


def is_same_person(
    first_name1: str,
    last_name1: str,
    first_name2: str,
    last_name2: str,
    threshold: float = DEFAULT_THRESHOLD,
) -> bool:
    """Check if two person records likely refer to the same person.

    This is the primary function for duplicate detection during
    the reconciliation phase.

    Args:
        first_name1: First person's first name.
        last_name1: First person's last name.
        first_name2: Second person's first name.
        last_name2: Second person's last name.
        threshold: Minimum similarity threshold.

    Returns:
        True if the persons are likely the same.
    """
    comparison = compare_person_names(
        first_name1, last_name1, first_name2, last_name2, threshold
    )
    return comparison.is_match


def find_duplicates(
    persons: list[tuple[str, str, str]],
    threshold: float = DEFAULT_THRESHOLD,
) -> list[list[int]]:
    """Find groups of duplicate persons in a list.

    Args:
        persons: List of (id, first_name, last_name) tuples.
        threshold: Similarity threshold for duplicate detection.

    Returns:
        List of groups, where each group is a list of indices
        that are duplicates of each other.
    """
    if not persons:
        return []

    # Track which indices have been assigned to a group
    assigned = set()
    groups = []

    for i, (id1, first1, last1) in enumerate(persons):
        if i in assigned:
            continue

        # Start a new group with this person
        group = [i]
        assigned.add(i)

        # Find all duplicates
        for j, (id2, first2, last2) in enumerate(persons[i + 1 :], start=i + 1):
            if j in assigned:
                continue

            if is_same_person(first1, last1, first2, last2, threshold):
                group.append(j)
                assigned.add(j)

        if len(group) > 1:
            groups.append(group)

    return groups
