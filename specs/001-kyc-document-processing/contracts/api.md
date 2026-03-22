# API Contracts: KYC Document Processing

**Date**: 2025-03-22
**Feature**: 001-kyc-document-processing

## Base URL

```
http://localhost:8000/api/v1
```

---

## Endpoints

### 1. Upload Documents & Create Workflow

**POST** `/workflows`

Creates a new workflow and uploads documents for processing.

**Request**:
```
Content-Type: multipart/form-data
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| files | File[] | Yes | PDF or TXT files (multiple allowed) |

**Response** `201 Created`:
```json
{
  "workflow_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "created_at": "2025-03-22T10:30:00Z",
  "documents": [
    {
      "document_id": "660e8400-e29b-41d4-a716-446655440001",
      "filename": "handelsregister_example.pdf",
      "file_type": "PDF",
      "page_count": 5
    }
  ]
}
```

**Errors**:
- `400 Bad Request`: Invalid file type (not PDF/TXT)
- `413 Payload Too Large`: File exceeds size limit

---

### 2. Start Workflow Processing

**POST** `/workflows/{workflow_id}/start`

Triggers the document processing pipeline.

**Response** `202 Accepted`:
```json
{
  "workflow_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "in_progress",
  "started_at": "2025-03-22T10:30:05Z",
  "message": "Workflow started. Connect to WebSocket for real-time updates."
}
```

**Errors**:
- `404 Not Found`: Workflow not found
- `409 Conflict`: Workflow already started or completed

---

### 3. Get Workflow Status

**GET** `/workflows/{workflow_id}`

Returns current workflow status and summary.

**Response** `200 OK`:
```json
{
  "workflow_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "created_at": "2025-03-22T10:30:00Z",
  "completed_at": "2025-03-22T10:32:45Z",
  "duration_seconds": 165.5,
  "documents": [
    {
      "filename": "handelsregister_example.pdf",
      "processing_status": "processed"
    }
  ],
  "summary": {
    "total_persons_extracted": 12,
    "csm_count": 3,
    "non_csm_count": 9,
    "conflicts_detected": 1
  },
  "current_step": null,
  "retry_counts": {
    "extractor": 0,
    "reconciler": 1,
    "classifier": 0
  }
}
```

**Errors**:
- `404 Not Found`: Workflow not found

---

### 4. Get Workflow Output (JSON Download)

**GET** `/workflows/{workflow_id}/output`

Returns the complete output as downloadable JSON.

**Response** `200 OK`:
```
Content-Type: application/json
Content-Disposition: attachment; filename="workflow_550e8400_output.json"
```

```json
{
  "workflow_id": "550e8400-e29b-41d4-a716-446655440000",
  "completed_at": "2025-03-22T10:32:45Z",
  "document_manifest": [
    {
      "filename": "handelsregister_example.pdf",
      "file_type": "PDF",
      "page_count": 5,
      "processing_status": "processed"
    }
  ],
  "csm_list": [
    {
      "first_name": "Hans",
      "last_name": "Müller",
      "job_title": "Geschäftsführer",
      "date_of_birth": "1975-03-15",
      "nationality": "German",
      "address": "Berliner Str. 42, 10115 Berlin",
      "classification": "CSM",
      "reasoning": "Individual holds position of Geschäftsführer (Managing Director), which qualifies as a senior management role under CSM definition criteria 2.1.a.",
      "has_conflicts": false,
      "source_references": [
        { "document": "handelsregister_example.pdf", "page": 2 }
      ]
    }
  ],
  "non_csm_list": [
    {
      "first_name": "Anna",
      "last_name": "Schmidt",
      "job_title": "Prokurist",
      "classification": "NON_CSM",
      "reasoning": "Prokurist (authorized signatory) does not meet CSM criteria as this role lacks strategic decision-making authority per criteria 2.1.b.",
      "has_conflicts": false,
      "source_references": [
        { "document": "handelsregister_example.pdf", "page": 3 }
      ]
    }
  ]
}
```

**Errors**:
- `404 Not Found`: Workflow not found
- `409 Conflict`: Workflow not yet completed

---

### 5. List Workflows (History)

**GET** `/workflows`

Returns paginated list of all workflow runs.

**Query Parameters**:
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| status | string | - | Filter by status (pending/in_progress/completed/failed) |
| limit | int | 20 | Results per page (max 100) |
| offset | int | 0 | Pagination offset |
| sort | string | -created_at | Sort field (prefix `-` for descending) |

**Response** `200 OK`:
```json
{
  "total": 42,
  "limit": 20,
  "offset": 0,
  "workflows": [
    {
      "workflow_id": "550e8400-e29b-41d4-a716-446655440000",
      "status": "completed",
      "created_at": "2025-03-22T10:30:00Z",
      "completed_at": "2025-03-22T10:32:45Z",
      "duration_seconds": 165.5,
      "document_count": 1,
      "person_count": 12
    }
  ]
}
```

---

### 6. Get Workflow Trace (Detailed Execution Log)

**GET** `/workflows/{workflow_id}/trace`

Returns detailed execution trace for observability UI.

**Response** `200 OK`:
```json
{
  "workflow_id": "550e8400-e29b-41d4-a716-446655440000",
  "executions": [
    {
      "execution_id": "770e8400-e29b-41d4-a716-446655440002",
      "agent_name": "extractor",
      "started_at": "2025-03-22T10:30:05Z",
      "ended_at": "2025-03-22T10:30:45Z",
      "duration_ms": 40000,
      "status": "completed",
      "retry_count": 0,
      "input_summary": "Processing 1 document (5 pages)",
      "output_summary": "Extracted 12 persons",
      "critic_feedback": null
    },
    {
      "execution_id": "770e8400-e29b-41d4-a716-446655440003",
      "agent_name": "critic_1",
      "started_at": "2025-03-22T10:30:45Z",
      "ended_at": "2025-03-22T10:30:50Z",
      "duration_ms": 5000,
      "status": "completed",
      "decision": "pass",
      "input_summary": "Reviewing 12 extracted persons",
      "output_summary": "All mandatory fields present"
    }
  ]
}
```

---

## WebSocket: Real-Time Workflow Updates

**WS** `/ws/workflows/{workflow_id}`

Establishes WebSocket connection for real-time status updates.

**Events Sent by Server**:

```json
// Agent started
{
  "event": "agent_started",
  "timestamp": "2025-03-22T10:30:05Z",
  "data": {
    "agent_name": "extractor",
    "retry_count": 0
  }
}

// Agent completed
{
  "event": "agent_completed",
  "timestamp": "2025-03-22T10:30:45Z",
  "data": {
    "agent_name": "extractor",
    "duration_ms": 40000,
    "output_summary": "Extracted 12 persons"
  }
}

// Critic decision
{
  "event": "critic_decision",
  "timestamp": "2025-03-22T10:30:50Z",
  "data": {
    "critic_name": "critic_1",
    "decision": "pass",
    "next_agent": "reconciler"
  }
}

// Retry triggered
{
  "event": "retry_triggered",
  "timestamp": "2025-03-22T10:31:00Z",
  "data": {
    "agent_name": "reconciler",
    "retry_count": 1,
    "feedback": "Duplicate detection missed similar names"
  }
}

// Workflow completed
{
  "event": "workflow_completed",
  "timestamp": "2025-03-22T10:32:45Z",
  "data": {
    "status": "completed",
    "duration_seconds": 165.5,
    "csm_count": 3,
    "non_csm_count": 9
  }
}

// Workflow failed
{
  "event": "workflow_failed",
  "timestamp": "2025-03-22T10:35:00Z",
  "data": {
    "status": "failed",
    "failed_agent": "classifier",
    "reason": "Max retries (4) exceeded",
    "last_feedback": "Classification reasoning insufficient"
  }
}
```

---

## Error Response Format

All error responses follow this structure:

```json
{
  "error": {
    "code": "WORKFLOW_NOT_FOUND",
    "message": "Workflow with ID 550e8400-... not found",
    "details": null
  }
}
```

**Error Codes**:
| Code | HTTP Status | Description |
|------|-------------|-------------|
| INVALID_FILE_TYPE | 400 | Uploaded file is not PDF or TXT |
| FILE_TOO_LARGE | 413 | File exceeds maximum size |
| WORKFLOW_NOT_FOUND | 404 | Workflow ID does not exist |
| WORKFLOW_ALREADY_STARTED | 409 | Cannot start workflow twice |
| WORKFLOW_NOT_COMPLETED | 409 | Output not available yet |
| LLM_SERVICE_UNAVAILABLE | 503 | LLM API failed after retries |
