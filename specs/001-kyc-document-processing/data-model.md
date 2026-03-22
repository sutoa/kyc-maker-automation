# Data Model: KYC Document Processing

**Date**: 2025-03-22
**Feature**: 001-kyc-document-processing

## Entity Relationship Diagram

```
┌─────────────────┐       ┌──────────────────┐
│  WorkflowRun    │───────│  UploadedDocument│
│                 │ 1   * │                  │
└────────┬────────┘       └──────────────────┘
         │ 1
         │
         │ *
┌────────▼────────┐       ┌──────────────────┐
│ AgentExecution  │───────│  CriticFeedback  │
│                 │ 1   ? │                  │
└────────┬────────┘       └──────────────────┘
         │
         │ (produces)
         ▼
┌─────────────────┐       ┌──────────────────┐
│     Person      │───────│ SourceReference  │
│                 │ 1   * │                  │
└────────┬────────┘       └──────────────────┘
         │ 1
         │
         │ 1
┌────────▼────────┐
│Classification   │
│    Result       │
└─────────────────┘
```

---

## Core Entities

### 1. WorkflowRun

Represents a single execution of the KYC document processing pipeline.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID | Yes | Unique workflow identifier |
| status | Enum | Yes | pending / in_progress / completed / failed |
| created_at | DateTime | Yes | Workflow trigger timestamp |
| completed_at | DateTime | No | Workflow completion timestamp |
| duration_seconds | Float | No | Total execution time |
| failure_reason | String | No | Error message if status=failed |
| output_json_path | String | No | Path to downloadable JSON output |

**Status Transitions**:
```
pending → in_progress → completed
                     ↘ failed
```

**Validation Rules**:
- `completed_at` must be set when status changes to completed/failed
- `duration_seconds` = completed_at - created_at
- `failure_reason` required when status=failed

---

### 2. UploadedDocument

Metadata for documents uploaded as workflow input.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID | Yes | Unique document identifier |
| workflow_run_id | UUID (FK) | Yes | Parent workflow |
| filename | String | Yes | Original filename |
| file_type | Enum | Yes | PDF / TXT |
| file_path | String | Yes | Storage path on filesystem |
| file_size_bytes | Integer | Yes | File size |
| page_count | Integer | No | Number of pages (PDF only) |
| processing_status | Enum | Yes | pending / processed / failed / partial |
| error_message | String | No | Extraction error if any |

**Validation Rules**:
- `filename` max 255 characters
- `file_type` must be PDF or TXT for MVP
- `page_count` required for PDF, null for TXT

---

### 3. AgentExecution

Records a single invocation of an agent within a workflow.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID | Yes | Unique execution identifier |
| workflow_run_id | UUID (FK) | Yes | Parent workflow |
| agent_name | String | Yes | Agent identifier (e.g., "extractor", "critic_1") |
| started_at | DateTime | Yes | Execution start time |
| ended_at | DateTime | No | Execution end time |
| duration_ms | Integer | No | Execution duration in milliseconds |
| input_payload | JSON | Yes | Input data to agent |
| output_payload | JSON | No | Output data from agent |
| retry_count | Integer | Yes | Current retry attempt (0-4) |
| status | Enum | Yes | running / completed / failed |

**Validation Rules**:
- `agent_name` must match configured agent names
- `retry_count` max value is 4
- `output_payload` required when status=completed

---

### 4. CriticFeedback

Feedback from a critic agent when an output fails review.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID | Yes | Unique feedback identifier |
| agent_execution_id | UUID (FK) | Yes | The execution that produced failing output |
| critic_agent_name | String | Yes | Name of critic agent (critic_1/2/3) |
| decision | Enum | Yes | pass / fail_retry / fail_max |
| issues_found | JSON | Yes | List of specific issues identified |
| suggested_corrections | String | No | Guidance for retry |
| created_at | DateTime | Yes | Feedback timestamp |

**Validation Rules**:
- `decision` must be one of: pass, fail_retry, fail_max
- `issues_found` must be non-empty array when decision != pass

---

### 5. Person

A natural person extracted from documents.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID | Yes | Unique person identifier |
| workflow_run_id | UUID (FK) | Yes | Parent workflow |
| first_name | String | Yes | Mandatory field |
| last_name | String | Yes | Mandatory field |
| first_name_normalized | String | Yes | Lowercased, ASCII-folded for matching |
| last_name_normalized | String | Yes | Lowercased, ASCII-folded for matching |
| job_title | String | No | Optional field |
| job_title_original | String | No | Original language (e.g., "Geschäftsführer") |
| date_of_birth | Date | No | Optional field |
| nationality | String | No | Optional field |
| address | String | No | Optional field |
| other_info | JSON | No | Additional extracted fields |
| is_duplicate | Boolean | Yes | True if merged with another record |
| merged_into_id | UUID (FK) | No | Reference to primary record if duplicate |
| has_conflicts | Boolean | Yes | True if conflicting data detected |
| conflicts | JSON | No | Details of conflicting fields |

**Validation Rules**:
- `first_name` and `last_name` must be non-empty
- `*_normalized` fields auto-generated from originals
- `merged_into_id` must be null if `is_duplicate` is false

---

### 6. SourceReference

Links extracted data to its origin in source documents.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID | Yes | Unique reference identifier |
| person_id | UUID (FK) | Yes | Parent person record |
| document_id | UUID (FK) | Yes | Source document |
| page_number | Integer | Yes | Page where data was found |
| field_name | String | No | Specific field this reference supports (null = whole record) |
| extraction_confidence | Float | No | LLM confidence score (0-1) |
| extracted_text_snippet | String | No | Relevant text from document |

**Validation Rules**:
- `page_number` must be >= 1
- `extraction_confidence` must be between 0 and 1 if present

---

### 7. ClassificationResult

The CSM/Non-CSM determination for a person.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID | Yes | Unique result identifier |
| person_id | UUID (FK) | Yes | Classified person (1:1) |
| classification | Enum | Yes | CSM / NON_CSM |
| reasoning | String | Yes | Explicit explanation citing CSM criteria |
| criteria_met | JSON | No | List of CSM definition criteria that were satisfied |
| criteria_not_met | JSON | No | List of CSM definition criteria not satisfied |
| confidence_score | Float | No | Classification confidence (0-1) |
| classified_at | DateTime | Yes | Classification timestamp |
| supporting_evidence | JSON | Yes | References to source documents supporting decision |

**Validation Rules**:
- `reasoning` must be non-empty (FR-015)
- `classification` must be exactly CSM or NON_CSM
- Each person has exactly one ClassificationResult (FR-016)

---

### 8. AuditLog

Immutable event log for compliance (FR-026/027/029).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID | Yes | Unique log entry identifier |
| workflow_run_id | UUID (FK) | Yes | Associated workflow |
| event_type | String | Yes | Event category (e.g., "agent_started", "decision_made") |
| event_timestamp | DateTime | Yes | When event occurred |
| actor | String | Yes | Agent or system component |
| action | String | Yes | What happened |
| details | JSON | Yes | Full event payload |
| checksum | String | Yes | SHA-256 hash for integrity verification |

**Validation Rules**:
- Immutable: no UPDATE or DELETE operations permitted
- `checksum` = SHA-256(event_type + timestamp + actor + action + details)
- Retention: 7 years from workflow completion (FR-029)

---

## Enumerations

### WorkflowStatus
```python
class WorkflowStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
```

### DocumentProcessingStatus
```python
class DocumentProcessingStatus(Enum):
    PENDING = "pending"
    PROCESSED = "processed"
    FAILED = "failed"
    PARTIAL = "partial"
```

### FileType
```python
class FileType(Enum):
    PDF = "PDF"
    TXT = "TXT"
```

### CriticDecision
```python
class CriticDecision(Enum):
    PASS = "pass"
    FAIL_RETRY = "fail_retry"
    FAIL_MAX = "fail_max"
```

### Classification
```python
class Classification(Enum):
    CSM = "CSM"
    NON_CSM = "NON_CSM"
```

---

## Output Schema (JSON Download)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["workflow_id", "completed_at", "document_manifest", "csm_list", "non_csm_list"],
  "properties": {
    "workflow_id": { "type": "string", "format": "uuid" },
    "completed_at": { "type": "string", "format": "date-time" },
    "document_manifest": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["filename", "file_type", "page_count", "processing_status"],
        "properties": {
          "filename": { "type": "string" },
          "file_type": { "enum": ["PDF", "TXT"] },
          "page_count": { "type": "integer", "minimum": 0 },
          "processing_status": { "enum": ["processed", "failed", "partial"] }
        }
      }
    },
    "csm_list": { "$ref": "#/definitions/person_list" },
    "non_csm_list": { "$ref": "#/definitions/person_list" }
  },
  "definitions": {
    "person_list": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["first_name", "last_name", "classification", "reasoning", "source_references"],
        "properties": {
          "first_name": { "type": "string" },
          "last_name": { "type": "string" },
          "job_title": { "type": ["string", "null"] },
          "date_of_birth": { "type": ["string", "null"], "format": "date" },
          "nationality": { "type": ["string", "null"] },
          "address": { "type": ["string", "null"] },
          "other_info": { "type": "object" },
          "classification": { "enum": ["CSM", "NON_CSM"] },
          "reasoning": { "type": "string" },
          "has_conflicts": { "type": "boolean" },
          "conflicts": { "type": ["array", "null"] },
          "source_references": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["document", "page"],
              "properties": {
                "document": { "type": "string" },
                "page": { "type": "integer", "minimum": 1 }
              }
            }
          }
        }
      }
    }
  }
}
```

---

## Indexes & Performance

| Table | Index | Purpose |
|-------|-------|---------|
| workflow_runs | status, created_at | Filter/sort workflow history |
| agent_executions | workflow_run_id, agent_name | Query executions by workflow |
| persons | workflow_run_id | Fetch all persons for a workflow |
| persons | first_name_normalized, last_name_normalized | Fuzzy matching lookups |
| source_references | person_id | Fetch references for a person |
| audit_logs | workflow_run_id, event_timestamp | Audit trail queries |

---

## Data Retention Policy

Per FR-029 and clarification session:

| Data Type | Retention Period | Deletion Strategy |
|-----------|------------------|-------------------|
| Workflow runs | 7 years from completion | Soft delete, archive to cold storage |
| Uploaded documents | 7 years from workflow completion | Move to archive storage |
| Audit logs | 7 years from workflow completion | Never delete; archive only |
| Agent execution logs | 7 years from workflow completion | Cascade with workflow |
