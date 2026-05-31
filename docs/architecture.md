# Architecture

## Overview

kyc-maker-automation is a YAML-driven multi-agent pipeline built on LangGraph. Its core job is to take a set of corporate documents (PDFs, TXT files) and extract, validate, and classify every named person into CSM (Controlling Senior Manager) or NON_CSM categories — producing a structured JSON compliance report. The domain involves German legal documents with multilingual terminology, so extraction quality is critical; a critic-gated retry loop ensures records meet mandatory field requirements before advancing.

The architecture separates three concerns: the HTTP surface (FastAPI, `src/api/`) accepts documents and manages workflow lifecycle; the workflow engine (`src/core/`) compiles a LangGraph `StateGraph` from YAML at startup and executes agents as graph nodes; and the services layer (`src/services/`) handles document text extraction, SQLAlchemy persistence, and an immutable audit trail. Every configurable value — model names, temperatures, prompt file paths, retry counts, state key names — lives in `src/config/agents.yaml` or `src/config/workflows.yaml`. Python source contains no hardcoded agent identifiers, model strings, or threshold values.

The system is designed for a single-tenant compliance workflow: one SQLite database, one FastAPI process, no external message queues. LangGraph checkpoints state to SQLite after every node, enabling resume after process restart. Real-time progress is delivered via a WebSocket that the agent node wrapper emits events to after each step.

## System diagram

```
                         ┌────────────────────────────────────────────┐
                         │              FastAPI Process                │
                         │                                             │
  HTTP Client ──POST──►  │  /api/v1/workflows          ┌──────────┐   │
                         │  /api/v1/workflows/{id}/start│  Config  │   │
  HTTP Client ──GET───►  │  /api/v1/workflows/{id}     │  Loader  │   │
                         │  /api/v1/documents/upload   └────┬─────┘   │
  WS Client ─────WS───►  │  /ws/workflows/{id}              │         │
                         │          │                        │ YAML    │
                         │    ┌─────┴──────┐         agents.yaml      │
                         │    │  Workflow   │◄────── workflows.yaml   │
                         │    │  Engine    │                          │
                         │    │ (LangGraph) │                          │
                         │    └─────┬──────┘                          │
                         │          │ nodes                            │
                         │    ┌─────▼──────────────────────┐          │
                         │    │  Agent Node Wrapper         │──events─►WS
                         │    │  ┌──────────────────────┐  │          │
                         │    │  │  Extractor (LLM)     │  │          │
                         │    │  │  ExtractorCritic(LLM)│  │          │
                         │    │  │  CriticRouter (rule)  │  │          │
                         │    │  │  Formatter (LLM)     │  │          │
                         │    │  └──────────────────────┘  │          │
                         │    └─────┬──────────────────────┘          │
                         │          │                                  │
                         │    ┌─────▼──────────────────────────────┐  │
                         │    │  Services Layer                     │  │
                         │    │  DocumentService  (pdfplumber)      │  │
                         │    │  AuditService     (SHA-256 log)     │  │
                         │    │  StorageService   (SQLAlchemy)      │  │
                         │    └─────┬──────────────────────────────┘  │
                         │          │                                  │
                         └──────────┼──────────────────────────────────┘
                                    │
                         ┌──────────▼──────────────────┐
                         │  SQLite Database             │
                         │  workflow_runs               │
                         │  uploaded_documents          │
                         │  audit_logs (immutable)      │
                         │  LangGraph checkpoints       │
                         └─────────────────────────────┘
```

## Components

### Workflow Engine

- **Location**: `src/core/workflow.py`
- **Purpose**: Compiles a `StateGraph` from `workflows.yaml` at application startup; wraps every agent node with logging, WebSocket event emission, and audit trail writes; provides `run_workflow_sync()` for blocking execution
- **Inputs**: `WorkflowState` (initial state with documents and workflow_id)
- **Outputs**: Final `WorkflowState` containing `csm_report`, updated status, and all intermediate person records
- **Key types/interfaces**: `WorkflowState` TypedDict, `AgentFunction = Callable[[WorkflowState], WorkflowState]`
- **Design notes**: Router nodes return `Command` objects instead of plain strings to atomically combine state updates with routing decisions. See `compile_workflow` deep-dive in [docs/deep-dive.md](deep-dive.md) for full internals.

### Agent Factory

- **Location**: `src/core/agent_factory.py`
- **Purpose**: Builds agent callables from YAML config. `execution: llm` agents get a prompt-rendering closure that calls a LangChain ChatModel with structured output; `execution: rule` agents get a thin wrapper around a Python callable resolved by dotted path
- **Inputs**: `agent_name`, `agent_cfg` (merged YAML dict with defaults applied), `agents_dir` (path for resolving relative prompt file paths)
- **Outputs**: `(state: WorkflowState) -> WorkflowState` callable, ready to be registered as a LangGraph node
- **Key types/interfaces**: `build_agent_fn()` public API; `_build_llm_agent_fn()`, `_build_rule_agent_fn()` internal builders
- **Design notes**: LLM model is instantiated fresh per-invocation rather than at build time, which avoids holding open connections and simplifies testing. Schema resolution (`_resolve_schema`) happens at factory build time so misconfigured refs fail fast on startup.

### Config Loader

- **Location**: `src/config/loader.py`
- **Purpose**: Loads `agents.yaml` and `workflows.yaml`, applies per-agent defaults from `defaults:`, resolves `agents_ref` cross-references, and validates both files against JSON schemas
- **Inputs**: File paths to YAML config files
- **Outputs**: Typed config dicts; `dict[str, AgentFunction]` for all active agents
- **Key types/interfaces**: `load_agents_config()`, `load_workflows_config()`, `build_agent_functions()`

### Conditions / Router

- **Location**: `src/core/conditions.py`
- **Purpose**: Routing functions referenced by name in `workflows.yaml`. `route_on_critic_decision` is the generic router for rule-based critics; `route_on_extractor_critic_decision` is the router for the LLM extraction critic loop
- **Inputs**: `WorkflowState`
- **Outputs**: `str` route key (generic router) or `Command[Literal[...]]` (extractor router)
- **Design notes**: The extractor router returns `Command(goto=..., update={"extraction_retry_count": n+1})` to atomically increment the retry counter and select the next node. Doing this in a conditional edge function would apply state updates outside the node wrapper's write window.

### State

- **Location**: `src/core/state.py`
- **Purpose**: Defines `WorkflowState` as a `TypedDict` — the single shared dict flowing through all agents and the node wrapper. Provides immutable update helpers
- **Key types/interfaces**: `WorkflowState`, `create_initial_state(documents, workflow_id)`

### FastAPI Application

- **Location**: `src/api/main.py`
- **Purpose**: Application factory with lifespan handler that initialises the database and compiles the LangGraph workflow on startup. Configures CORS and registers error handlers
- **Design notes**: Workflow compilation is done once at startup (`app.state.compiled_workflow`) and shared across all requests, avoiding per-request YAML parsing.

### Document Routes

- **Location**: `src/api/routes/documents.py`
- **Purpose**: Upload individual documents to an existing workflow; query document metadata and processing status
- **Key types**: `DocumentUploadResponse`, `DocumentMetadataResponse`

### Workflow Routes

- **Location**: `src/api/routes/workflows.py`
- **Purpose**: Create workflow with documents (multipart upload); start pipeline execution; retrieve status, output, execution trace, and paginated workflow history
- **Key types**: `WorkflowCreateResponse`, `WorkflowStartResponse`, `WorkflowStatusResponse`, `WorkflowTraceResponse`

### WebSocket Handler

- **Location**: `src/api/websocket.py`
- **Purpose**: Manages WebSocket connections keyed by `workflow_id`; broadcasts structured JSON events from the agent node wrapper to subscribed clients in real time
- **Endpoint**: `ws://<host>/ws/workflows/{workflow_id}`

### Document Service

- **Location**: `src/services/document.py`
- **Purpose**: Extracts text from PDF files with page boundary tracking. pdfplumber is the primary extractor (preserves layout and page numbers); PyMuPDF is the fallback for malformed PDFs and is OCR-capable for scanned documents
- **Inputs**: File path (PDF or TXT)
- **Outputs**: `DocumentInput` — full text, `list[PageContent]` (per-page text), and page count
- **Key types/interfaces**: `DocumentInput`, `PageContent`, `DocumentExtractionError`
- **Design notes**: Page provenance is mandatory — every `ExtractedPerson` record carries the page numbers it was found on, enabling auditors to verify extractions against source documents.

### Audit Service

- **Location**: `src/services/audit.py`
- **Purpose**: Creates immutable audit log entries for every workflow event. Each entry includes a SHA-256 checksum of the event data. No UPDATE or DELETE operations are permitted at the service or database level
- **Inputs**: Event type, workflow_id, agent_name, payload dict
- **Outputs**: `AuditLogDB` record persisted to SQLite
- **Key types/interfaces**: `AuditEventType` enum, `create_audit_service()`, `AuditService.log_event()`

### Storage Service

- **Location**: `src/services/storage.py`
- **Purpose**: SQLAlchemy session management and CRUD operations for `WorkflowRunDB`, `UploadedDocumentDB`, and `AuditLogDB` tables
- **Key types/interfaces**: `WorkflowRunDB`, `UploadedDocumentDB`, `AuditLogDB`, `get_db()` session factory

### Pydantic Models

- **Location**: `src/models/`
- **Purpose**: Type-safe data contracts for every domain object: `ExtractedPerson` (name, titles, source pages), `ReconciledPerson`, `ClassifiedPerson`, `CriticFeedback`, `ExtractorCriticFeedback`, workflow enums
- **Key types**: `src/models/person.py`, `src/models/workflow.py`, `src/models/enums.py`

## Data model

```
WorkflowRunDB
  id (workflow_id)  PK (UUID string)
  status            ENUM (pending|in_progress|completed|failed)
  created_at        TIMESTAMP
  started_at        TIMESTAMP nullable
  completed_at      TIMESTAMP nullable
  output_json_path  VARCHAR nullable    ← path to downloaded report file

UploadedDocumentDB
  id (document_id)  PK (UUID string)
  workflow_run_id   FK → WorkflowRunDB.id
  filename          VARCHAR
  file_type         ENUM (PDF|TXT)
  file_size_bytes   INTEGER
  page_count        INTEGER nullable
  storage_path      VARCHAR
  processing_status VARCHAR
  error_message     TEXT nullable

AuditLogDB
  id                PK (auto-increment)
  workflow_id       VARCHAR (indexed)
  event_type        VARCHAR
  agent_name        VARCHAR nullable
  payload           TEXT (JSON)
  checksum          VARCHAR (SHA-256 of payload)
  created_at        TIMESTAMP
  ─── NO UPDATE or DELETE operations permitted ───
```

## Design decisions

1. **YAML as single source of truth for all agent configuration**

   *Choice*: All agent names, model strings, temperatures, prompt file paths, retry limits, and state key names declared in `agents.yaml` and `workflows.yaml`. Python source contains no hardcoded values.
   *Alternatives considered*: Per-agent Python modules with hardcoded config; environment variables per agent.
   *Rationale*: Configuration drift between agents and between environments was the primary concern. YAML makes every configurable value visible in one place, enabling non-engineers to adjust model selection or retry policy without touching Python. Adding a new agent (e.g. re-enabling the reconciler) is a YAML edit rather than a code change.

2. **One generic agent factory instead of per-agent classes**

   *Choice*: `build_agent_fn()` constructs any agent type (`llm` or `rule`) from config. No `ExtractorAgent` class, no `CriticAgent` class.
   *Alternatives considered*: Subclass hierarchy per agent; one Python file per agent with hardcoded logic.
   *Rationale*: Per-agent classes duplicate cross-cutting concerns (logging, retry increment, state update pattern). A factory ensures every agent behaves identically at the node wrapper level. Adding a new LLM agent requires only a YAML entry and a prompt file.

3. **`Command` return in critic router instead of conditional edge function**

   *Choice*: `route_on_extractor_critic_decision` is a router node that returns `Command(goto=..., update={...})`. The retry counter increment happens inside the Command, not in a separate node.
   *Alternatives considered*: A conditional edge function returning a route string; a separate `increment_retry_count` node before routing.
   *Rationale*: LangGraph conditional edge functions are pure routing functions — state mutations inside them are applied outside the node wrapper and outside the checkpointer's write window, creating subtle bugs. `Command` makes the state update and the routing decision atomic and visible to the checkpointer.

4. **Immutable audit log with SHA-256 checksums**

   *Choice*: `AuditLogDB` rows are write-only. The service layer has no `update` or `delete` methods. Each row includes a SHA-256 of its payload.
   *Alternatives considered*: Standard mutable log table; structured file-based logging only.
   *Rationale*: KYC compliance (FR-029) requires a tamper-evident audit trail with 7-year retention. SHA-256 checksums allow external auditors to verify that log entries have not been modified. The database-level immutability constraint enforces this even if application code is modified.

5. **pdfplumber primary, PyMuPDF fallback for PDF extraction**

   *Choice*: Try pdfplumber first; catch `pdfplumber.exceptions` and retry with PyMuPDF.
   *Alternatives considered*: PyMuPDF only; Tesseract OCR for all PDFs; AWS Textract.
   *Rationale*: pdfplumber preserves layout and page boundaries with high fidelity for structured PDFs, which is essential for accurate source provenance. PyMuPDF handles malformed PDFs and scanned documents that pdfplumber cannot parse. This two-library approach maximises coverage without requiring external services.

## External dependencies

| Dependency | Version | Purpose | Alternatives considered |
|---|---|---|---|
| `langgraph` | ≥0.2.0 | StateGraph orchestration; checkpointing; `Command` routing | LangChain LCEL chains (no graph topology, no state persistence) |
| `langchain-core` | ≥0.3.0 | `ChatModel` interface; `SystemMessage`; structured output | Direct OpenAI SDK (would lose provider abstraction) |
| `langchain-openai` | ≥0.3.0 | OpenAI provider for LangChain | Direct `openai` SDK |
| `langchain-google-genai` | ≥2.0.0 | Gemini provider for LangChain | `google-generativeai` SDK directly |
| `fastapi` | ≥0.115.0 | HTTP API and WebSocket | Flask (no async native), Django REST (heavier) |
| `pdfplumber` | ≥0.11.0 | PDF text extraction with layout awareness | PyMuPDF only (weaker layout preservation) |
| `pymupdf` | ≥1.24.0 | PDF fallback extractor; OCR-capable | pdfplumber only (fails on some PDFs) |
| `rapidfuzz` | ≥3.10.0 | Fuzzy name matching for reconciler | `fuzzywuzzy` (slower, less maintained) |
| `sqlalchemy` | ≥2.0.0 | ORM for workflow and audit persistence | Raw SQLite; Tortoise ORM (async-only) |
| `langgraph-checkpoint-sqlite` | ≥2.0.0 | LangGraph state persistence to SQLite | In-memory checkpointer (no resume on restart) |

<!-- generated-by: project-docs-skill -->
