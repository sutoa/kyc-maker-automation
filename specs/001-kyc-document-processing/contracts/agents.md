# Agent Contracts: KYC Document Processing

**Date**: 2025-03-22
**Feature**: 001-kyc-document-processing

## Overview

This document defines the input/output contracts for each agent in the KYC workflow. These contracts are used for:
- Contract testing (verify agent schemas)
- Agent-to-agent data flow validation
- LangGraph state management

---

## Workflow State Schema

The shared state object passed through the LangGraph workflow:

```python
class WorkflowState(TypedDict):
    # Input
    workflow_id: str
    documents: list[DocumentInput]

    # Extraction phase
    extracted_persons: list[ExtractedPerson]
    extraction_retry_count: int

    # Reconciliation phase
    reconciled_persons: list[ReconciledPerson]
    reconciliation_retry_count: int

    # Classification phase
    classified_persons: list[ClassifiedPerson]
    classification_retry_count: int

    # Critic feedback (latest)
    last_critic_feedback: CriticFeedback | None

    # Final output
    document_manifest: list[DocumentManifestEntry]
    csm_list: list[ClassifiedPerson]
    non_csm_list: list[ClassifiedPerson]

    # Status tracking
    current_agent: str
    status: Literal["pending", "in_progress", "completed", "failed"]
    failure_reason: str | None
```

---

## Agent 1: Extractor

### Input Contract

```python
class ExtractorInput(BaseModel):
    documents: list[DocumentInput]
    retry_feedback: str | None = None  # Feedback from critic if retrying

class DocumentInput(BaseModel):
    document_id: str
    filename: str
    file_type: Literal["PDF", "TXT"]
    content: str  # Extracted text (with page markers)
    page_count: int
```

### Output Contract

```python
class ExtractorOutput(BaseModel):
    extracted_persons: list[ExtractedPerson]

class ExtractedPerson(BaseModel):
    extraction_id: str  # Temporary ID for this extraction
    first_name: str
    last_name: str
    job_title: str | None = None
    job_title_original: str | None = None  # Original language (e.g., "Geschäftsführer")
    date_of_birth: date | None = None
    nationality: str | None = None
    address: str | None = None
    other_info: dict = {}
    source_references: list[SourceReference]

class SourceReference(BaseModel):
    document_id: str
    filename: str
    page_number: int
    extracted_text_snippet: str | None = None
    confidence: float | None = None  # 0.0 - 1.0
```

### Validation Rules

- `first_name` and `last_name` must be non-empty strings
- `source_references` must have at least one entry per person
- `page_number` must be >= 1

---

## Agent 2: Critic 1 (Extraction Validator)

### Input Contract

```python
class Critic1Input(BaseModel):
    extracted_persons: list[ExtractedPerson]
    retry_count: int
```

### Output Contract

```python
class Critic1Output(BaseModel):
    decision: Literal["pass", "fail_retry", "fail_max"]
    issues: list[ExtractionIssue] = []
    feedback: str | None = None

class ExtractionIssue(BaseModel):
    extraction_id: str  # Which person record has the issue
    issue_type: Literal["missing_first_name", "missing_last_name",
                        "missing_source", "invalid_page_number",
                        "low_confidence", "other"]
    description: str
    severity: Literal["error", "warning"]
```

### Decision Logic

```
IF all mandatory fields present AND no severity="error" issues:
    decision = "pass"
ELSE IF retry_count < 4:
    decision = "fail_retry"
ELSE:
    decision = "fail_max"
```

---

## Agent 3: Reconciler

### Input Contract

```python
class ReconcilerInput(BaseModel):
    extracted_persons: list[ExtractedPerson]
    retry_feedback: str | None = None
```

### Output Contract

```python
class ReconcilerOutput(BaseModel):
    reconciled_persons: list[ReconciledPerson]
    duplicate_groups: list[DuplicateGroup]  # For audit trail

class ReconciledPerson(BaseModel):
    person_id: str  # Stable ID after deduplication
    first_name: str
    last_name: str
    first_name_normalized: str
    last_name_normalized: str
    job_title: str | None = None
    job_title_original: str | None = None
    date_of_birth: date | None = None
    nationality: str | None = None
    address: str | None = None
    other_info: dict = {}
    source_references: list[SourceReference]  # Consolidated from all occurrences
    has_conflicts: bool = False
    conflicts: list[FieldConflict] = []

class FieldConflict(BaseModel):
    field_name: str
    values: list[ConflictValue]

class ConflictValue(BaseModel):
    value: str
    source_document: str
    source_page: int

class DuplicateGroup(BaseModel):
    primary_person_id: str
    merged_extraction_ids: list[str]
    match_score: float  # Fuzzy match confidence
```

### Deduplication Rules

- Use fuzzy name matching (Jaro-Winkler, threshold >= 0.85)
- Normalize names: lowercase, ASCII-fold (ü → ue, etc.)
- Merge source_references from all duplicate records
- Flag conflicts when same field has different values

---

## Agent 4: Critic 2 (Reconciliation Validator)

### Input Contract

```python
class Critic2Input(BaseModel):
    reconciled_persons: list[ReconciledPerson]
    duplicate_groups: list[DuplicateGroup]
    retry_count: int
```

### Output Contract

```python
class Critic2Output(BaseModel):
    decision: Literal["pass", "fail_retry", "fail_max"]
    issues: list[ReconciliationIssue] = []
    feedback: str | None = None

class ReconciliationIssue(BaseModel):
    person_id: str | None = None  # null for global issues
    issue_type: Literal["missed_duplicate", "incorrect_merge",
                        "undetected_conflict", "lost_source_reference",
                        "other"]
    description: str
    evidence: str | None = None
```

---

## Agent 5: Classifier

### Input Contract

```python
class ClassifierInput(BaseModel):
    reconciled_persons: list[ReconciledPerson]
    csm_definition: str  # The official CSM definition text
    retry_feedback: str | None = None
```

### Output Contract

```python
class ClassifierOutput(BaseModel):
    classified_persons: list[ClassifiedPerson]

class ClassifiedPerson(BaseModel):
    person_id: str
    first_name: str
    last_name: str
    job_title: str | None = None
    job_title_original: str | None = None
    date_of_birth: date | None = None
    nationality: str | None = None
    address: str | None = None
    other_info: dict = {}
    source_references: list[SourceReference]
    has_conflicts: bool = False
    conflicts: list[FieldConflict] = []

    # Classification result
    classification: Literal["CSM", "NON_CSM"]
    reasoning: str  # Must cite specific CSM criteria
    criteria_met: list[str] = []
    criteria_not_met: list[str] = []
    confidence: float | None = None
    supporting_evidence: list[EvidenceReference] = []

class EvidenceReference(BaseModel):
    document: str
    page: int
    relevant_text: str
```

### Classification Rules

- Each person must receive exactly one classification
- `reasoning` must reference specific CSM definition criteria
- German job titles must be mapped to their English equivalents for evaluation

---

## Agent 6: Critic 3 (Classification Validator)

### Input Contract

```python
class Critic3Input(BaseModel):
    classified_persons: list[ClassifiedPerson]
    csm_definition: str
    retry_count: int
```

### Output Contract

```python
class Critic3Output(BaseModel):
    decision: Literal["pass", "fail_retry", "fail_max"]
    issues: list[ClassificationIssue] = []
    feedback: str | None = None

class ClassificationIssue(BaseModel):
    person_id: str
    issue_type: Literal["missing_reasoning", "weak_reasoning",
                        "incorrect_criteria_citation", "missing_evidence",
                        "inconsistent_classification", "other"]
    description: str
    suggested_correction: str | None = None
```

### Validation Checks

- Every person has `classification` set
- `reasoning` is non-empty and references CSM criteria
- No person appears in both CSM and NON_CSM implicitly
- Classification is consistent with stated criteria

---

## Agent 7: Output Formatter

### Input Contract

```python
class FormatterInput(BaseModel):
    workflow_id: str
    documents: list[DocumentInput]
    classified_persons: list[ClassifiedPerson]
```

### Output Contract

```python
class FormatterOutput(BaseModel):
    document_manifest: list[DocumentManifestEntry]
    csm_list: list[ClassifiedPerson]
    non_csm_list: list[ClassifiedPerson]

class DocumentManifestEntry(BaseModel):
    filename: str
    file_type: Literal["PDF", "TXT"]
    page_count: int
    processing_status: Literal["processed", "failed", "partial"]
```

---

## LangGraph Transitions

```yaml
extractor:
  on_complete: critic_1

critic_1:
  on_pass: reconciler
  on_fail_retry: extractor
  on_fail_max: FAILED

reconciler:
  on_complete: critic_2

critic_2:
  on_pass: classifier
  on_fail_retry: reconciler
  on_fail_max: FAILED

classifier:
  on_complete: critic_3

critic_3:
  on_pass: formatter
  on_fail_retry: classifier
  on_fail_max: FAILED

formatter:
  on_complete: COMPLETED
```
