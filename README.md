# KYC Maker Automation

> **Automated KYC document processing powered by a multi-agent LLM pipeline.**
> Upload corporate documents. Get a structured CSM/Non-CSM classification report.

---

## Overview

KYC Maker Automation is a production-grade backend system that processes Know Your Customer (KYC) documents — PDFs and text files — and produces a structured JSON report identifying all persons and classifying them as **Controlling Senior Managers (CSM)** or **Non-CSM**.

The system is built around a **7-agent LangGraph pipeline** where each processing step is validated by a critic before proceeding. All operations are fully auditable with immutable logs and 7-year data retention.

---

## Features

- **Multi-format document ingestion** — PDF (with fallback OCR) and plain text
- **LLM-powered extraction** — Handles complex layouts, German documents, and ambiguous names
- **Intelligent deduplication** — Jaro-Winkler fuzzy matching with German umlaut normalization
- **CSM classification with reasoning** — Every decision backed by cited criteria and source evidence
- **Real-time monitoring** — WebSocket events at every pipeline stage
- **Full audit trail** — Immutable logs with SHA-256 checksums, 7-year retention
- **Pluggable LLM providers** — OpenAI and Google Gemini supported out of the box

---

## Architecture

### The 7-Agent Pipeline

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         KYC Processing Pipeline                         │
│                                                                         │
│  ┌──────────┐   ┌──────────┐   ┌─────────────┐   ┌──────────┐         │
│  │ Extractor│──▶│ Critic 1 │──▶│ Reconciler  │──▶│ Critic 2 │──▶ ...  │
│  └──────────┘   └──────────┘   └─────────────┘   └──────────┘         │
│       ▲              │               ▲                 │                │
│       └── retry ─────┘               └──── retry ──────┘               │
│                                                                         │
│  ... ──▶┌────────────┐   ┌──────────┐   ┌───────────┐                 │
│         │ Classifier │──▶│ Critic 3 │──▶│ Formatter │──▶ JSON Output  │
│         └────────────┘   └──────────┘   └───────────┘                 │
│               ▲               │                                         │
│               └─── retry ─────┘                                        │
└─────────────────────────────────────────────────────────────────────────┘
```

### Agent Reference

| Agent | Execution | Responsibility |
|-------|-----------|----------------|
| **Extractor** | LLM | Extract all persons from document text with source references |
| **Critic 1** | LLM | Validate names present, sources cited, confidence adequate |
| **Reconciler** | LLM | Deduplicate persons across documents using fuzzy matching |
| **Critic 2** | Rule (`validate_reconciliation_for_factory`) | Validate no missed merges, no incorrect merges, conflicts flagged |
| **Classifier** | LLM | Classify each person as CSM or Non-CSM with reasoning |
| **Critic 3** | Rule (`validate_classification_for_factory`) | Validate reasoning non-empty, criteria cited, evidence provided |
| **Formatter** | LLM | Assemble final JSON output with manifest and person lists |

> Execution type (`llm` or `rule`) and all parameters are declared in `src/config/agents.yaml` — no hardcoding in source.

### Critic Decision Pattern

Every critic returns one of three outcomes:

```
PASS        →  Advance to next agent
FAIL_RETRY  →  Retry with structured feedback  (up to 4 attempts)
FAIL_MAX    →  Halt workflow with error
```

---

## Project Structure

```
kyc-maker-automation/
├── src/
│   ├── agents/                  # LLM-powered processing agents
│   │   ├── extractor.py         #   Person extraction
│   │   ├── critic.py            #   Validation logic (critics 1, 2, 3)
│   │   ├── reconciler.py        #   Deduplication
│   │   ├── classifier.py        #   CSM/Non-CSM classification
│   │   └── formatter.py         #   Final output assembly
│   │
│   ├── api/                     # FastAPI application
│   │   ├── main.py              #   App setup, middleware, error handlers
│   │   ├── routes/
│   │   │   ├── documents.py     #   Document upload endpoints
│   │   │   └── workflows.py     #   Workflow management endpoints
│   │   ├── websocket.py         #   Real-time WebSocket updates
│   │   ├── dependencies.py      #   Dependency injection
│   │   └── errors.py            #   Error codes and response shapes
│   │
│   ├── core/                    # Workflow engine
│   │   ├── workflow.py          #   LangGraph builder & executor
│   │   ├── agent_factory.py     #   YAML-driven agent function builder
│   │   ├── conditions.py        #   Generic critic routing (route_on_critic_decision)
│   │   ├── state.py             #   WorkflowState TypedDict & helpers
│   │   ├── events.py            #   Event emission for WebSocket
│   │   └── llm/                 #   Model-agnostic LLM abstraction
│   │       ├── base.py          #     Abstract LLMProvider interface
│   │       ├── openai.py        #     OpenAI implementation
│   │       └── gemini.py        #     Google Gemini implementation
│   │
│   ├── config/                  # YAML-based configuration
│   │   ├── agents.yaml          #   Agent definitions & LLM parameters
│   │   ├── workflows.yaml       #   State machine transitions
│   │   ├── loader.py            #   Config loading & schema validation
│   │   └── schemas/             #   JSON schema validators
│   │
│   ├── models/                  # Pydantic data models
│   │   ├── person.py            #   ExtractedPerson, ReconciledPerson, ClassifiedPerson
│   │   ├── workflow.py          #   WorkflowRun, AgentExecution, CriticFeedback
│   │   ├── output.py            #   WorkflowOutput, DocumentManifestEntry
│   │   └── enums.py             #   Status enums and classifications
│   │
│   ├── services/                # Business logic
│   │   ├── document.py          #   PDF/TXT text extraction
│   │   ├── matching.py          #   Fuzzy name matching
│   │   ├── storage.py           #   SQLAlchemy ORM models
│   │   ├── database.py          #   DB connection & initialization
│   │   └── audit.py             #   Immutable audit trail logging
│   │
│   └── prompts/                 # LLM prompt templates (Markdown)
│       ├── extractor.md
│       ├── critic_1.md / critic_2.md / critic_3.md
│       ├── classifier.md
│       ├── reconciler.md
│       ├── formatter.md
│       └── csm_definition.md
│
├── tests/
│   ├── unit/                    # Services and state helpers
│   ├── contract/                # Agent I/O schema validation
│   ├── integration/             # End-to-end workflow tests
│   └── api/                     # REST and WebSocket endpoint tests
│
├── specs/
│   └── 001-kyc-document-processing/
│       ├── spec.md              # Requirements (FR-001 – FR-029)
│       ├── plan.md              # Implementation phases
│       ├── tasks.md             # Task breakdown
│       ├── data-model.md        # Data schema
│       ├── contracts/           # API & agent contracts
│       └── quickstart.md        # Setup guide
│
├── requirements.txt             # Production dependencies
├── requirements-dev.txt         # Dev dependencies
└── .env                         # Environment configuration
```

---

## Data Flow

### Input
Upload one or more PDF or TXT documents containing corporate/KYC information.

### Processing Stages

```
Stage 1 — Extraction
  Raw document text  →  ExtractedPerson[]
  Each person has: first_name, last_name, job_title, date_of_birth,
                   nationality, address, + source_references[]

Stage 2 — Reconciliation
  ExtractedPerson[]  →  ReconciledPerson[]
  Jaro-Winkler fuzzy match (threshold: 0.85) collapses duplicates.
  Field conflicts (same person, different values) are flagged with sources.

Stage 3 — Classification
  ReconciledPerson[]  →  ClassifiedPerson[]
  Each person receives:
    • classification:    "CSM" | "NON_CSM"
    • reasoning:         citation of specific criteria
    • criteria_met:      list of matched CSM criteria
    • criteria_not_met:  list of unmatched criteria
    • confidence:        0.0 – 1.0
    • supporting_evidence: document + page + relevant text
```

### Output

```json
{
  "workflow_id": "3fa85f64-...",
  "completed_at": "2026-03-25T14:30:00Z",
  "document_manifest": [
    {
      "filename": "shareholder_agreement.pdf",
      "file_type": "PDF",
      "page_count": 12,
      "processing_status": "processed"
    }
  ],
  "csm_list": [
    {
      "first_name": "Johann",
      "last_name": "Müller",
      "classification": "CSM",
      "reasoning": "Holds 35% equity stake exceeding 25% threshold...",
      "criteria_met": ["equity_stake_above_25pct", "board_member"],
      "confidence": 0.94,
      "supporting_evidence": [
        {
          "document": "shareholder_agreement.pdf",
          "page": 4,
          "relevant_text": "Johann Müller hält 35% der Gesellschaftsanteile..."
        }
      ]
    }
  ],
  "non_csm_list": [ ... ]
}
```

---

## REST API Reference

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/workflows` | Upload documents and create a workflow |
| `POST` | `/api/v1/workflows/{id}/start` | Start workflow processing |
| `GET` | `/api/v1/workflows/{id}` | Get status and summary |
| `GET` | `/api/v1/workflows/{id}/output` | Download JSON results |
| `GET` | `/api/v1/workflows/{id}/trace` | Full agent execution trace |
| `GET` | `/api/v1/workflows` | List workflows (paginated) |
| `WS` | `/ws/workflows/{id}` | Real-time WebSocket event stream |

### WebSocket Events

```
agent_started        — An agent has begun processing
agent_completed      — An agent finished successfully
critic_decision      — A critic returned PASS / FAIL_RETRY / FAIL_MAX
retry_triggered      — An agent is being retried with feedback
workflow_completed   — Pipeline finished; output is ready
workflow_failed      — Pipeline halted due to max retries exceeded
```

### Standard Error Response

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable description",
    "details": null
  }
}
```

---

## Workflow Lifecycle

```
POST /workflows          →  status: pending
POST /workflows/{id}/start  →  status: in_progress
  (WebSocket stream of events...)
GET  /workflows/{id}     →  status: completed | failed
GET  /workflows/{id}/output  →  Download results JSON
```

---

## Configuration

### Environment Variables

```bash
# ── LLM Provider ──────────────────────────────────────────────
OPENAI_API_KEY=sk-...        # Required if using openai/* models
GOOGLE_API_KEY=...           # Required if using gemini/* models

# ── Database ──────────────────────────────────────────────────
DATABASE_URL=sqlite:///./kyc_workflows.db

# ── File Handling ─────────────────────────────────────────────
UPLOAD_DIR=./uploads
OUTPUT_DIR=./outputs
MAX_FILE_SIZE_MB=50

# ── Application ───────────────────────────────────────────────
API_HOST=0.0.0.0
API_PORT=8000
LOG_LEVEL=INFO
SQL_ECHO=false               # Set "true" to log SQL queries
```

> **Model, temperature, max_tokens, and retry settings are no longer env vars.** They are configured per-agent in `src/config/agents.yaml` and apply at build time via the agent factory.

### Agent & Workflow Configuration

All agents, LLM parameters, retry logic, and workflow topology are declared in YAML — no code changes needed to tune behaviour.

```yaml
# src/config/agents.yaml  (excerpt — v1.2)
defaults:
  model: openai/gpt-4o-mini
  temperature: 0
  max_tokens: 16384
  retry:
    max_attempts: 4
    backoff: exponential
    delay_seconds: 1

agents:
  extractor:
    execution: llm
    system_prompt:
      file: ../prompts/extractor.md
    input_keys: [documents, extraction_feedback]
    output_key: extracted_persons
    retry_count_key: extraction_retry_count
    output_schema:
      ref: src.models.person.ExtractedPerson
      is_list: true

  critic_2:
    execution: rule
    rule_fn: src.agents.critic.validate_reconciliation_for_factory
    input_keys: [reconciled_persons, reconciliation_retry_count]
    output_key: last_critic_feedback
```

```yaml
# src/config/workflows.yaml  (excerpt — v1.2)
edges:
  - from: extractor
    to: critic_1
  - from: critic_1
    condition:
      fn: src.core.conditions.route_on_critic_decision
      routes:
        pass: reconciler
        fail_retry: extractor
        fail_max: end
```

At startup, `compile_workflow()` reads both files, calls `build_agent_functions()` to create all agent callables from the YAML declarations, then builds and compiles the LangGraph graph. No agent code is touched when tuning parameters.

---

## Data Models

### Person Lifecycle

```
ExtractedPerson          ReconciledPerson         ClassifiedPerson
─────────────────        ─────────────────────    ────────────────────────────
extraction_id        →   person_id            →   person_id
first_name               first_name_normalized     classification: CSM|NON_CSM
last_name                last_name_normalized      reasoning
job_title                has_conflicts             criteria_met[]
job_title_original        conflicts[]              criteria_not_met[]
date_of_birth               FieldConflict          confidence
nationality                   field_name            supporting_evidence[]
address                       values[]
other_info{}                    value
source_references[]             source_document
  document_id                   source_page
  page_number              source_references[]
```

### Database Schema (SQLAlchemy)

```
WorkflowRunDB
  ├── UploadedDocumentDB[]    (uploaded files)
  ├── AgentExecutionDB[]      (per-agent timing + payloads)
  │     └── CriticFeedbackDB  (decision + issues found)
  ├── PersonDB[]              (person records per stage)
  └── AuditLogDB[]            (immutable event log)
```

> **Compliance note:** All data is retained for 7 years (FR-029). Audit logs are immutable — UPDATE and DELETE are prevented at the database level.

---

## Getting Started

### 1. Clone & Install

```bash
git clone <repo-url>
cd kyc-maker-automation

python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

pip install -r requirements.txt
pip install -r requirements-dev.txt   # for development
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env — add your OPENAI_API_KEY (or GOOGLE_API_KEY for Gemini)
```

### 3. Initialize Database

```bash
python -c "from src.services.database import init_db; init_db()"
```

### 4. Start the Server

```bash
# Development (auto-reload)
uvicorn src.api.main:app --reload --port 8000

# Production
python -c "from src.api.main import run_production; run_production()"
```

### 5. Process Your First Document

```bash
# Upload documents and create a workflow
curl -X POST http://localhost:8000/api/v1/workflows \
  -F "files=@my_document.pdf"

# Start processing
curl -X POST http://localhost:8000/api/v1/workflows/{workflow_id}/start

# Poll for completion
curl http://localhost:8000/api/v1/workflows/{workflow_id}

# Download results
curl http://localhost:8000/api/v1/workflows/{workflow_id}/output -o results.json
```

---

## Development

### Running Tests

```bash
# All tests
pytest

# With coverage report
pytest --cov=src --cov-report=term-missing

# Specific test category
pytest tests/unit/
pytest tests/integration/
pytest tests/contract/
pytest tests/api/
```

### Linting & Formatting

```bash
ruff check .           # Lint
ruff format .          # Format
mypy src/              # Type checking
```

### Test Categories

| Category | Path | Purpose |
|----------|------|---------|
| **Unit** | `tests/unit/` | Services, state helpers, LLM mocking |
| **Contract** | `tests/contract/` | Agent input/output schema validation |
| **Integration** | `tests/integration/` | Full pipeline execution with mocked LLMs |
| **API** | `tests/api/` | REST endpoints and WebSocket events |

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| **Orchestration** | LangGraph ≥ 0.2 |
| **Web API** | FastAPI ≥ 0.115 |
| **LLM Providers** | OpenAI (GPT-4o-mini) · Google Gemini (1.5 Pro) |
| **PDF Extraction** | pdfplumber ≥ 0.11 · PyMuPDF ≥ 1.24 (fallback) |
| **Fuzzy Matching** | rapidfuzz ≥ 3.10 · unidecode ≥ 1.3 |
| **Database** | SQLAlchemy ≥ 2.0 · SQLite (default) |
| **Validation** | Pydantic ≥ 2.9 |
| **Retries** | tenacity ≥ 9.0 |
| **ASGI Server** | Uvicorn with standard extras |
| **Testing** | pytest · pytest-asyncio · pytest-cov · pytest-mock |
| **Linting** | Ruff · mypy |

---

## Compliance & Security

- **Immutable audit logs** — SHA-256 checksums on all logged entries; UPDATE/DELETE blocked at DB level
- **7-year data retention** — `retention_until` field on every workflow run (FR-029)
- **Source provenance** — Every extracted field links back to its source document and page number
- **Input validation** — All API inputs validated via Pydantic; file type and size limits enforced
- **No secrets in code** — All credentials via environment variables only

---

## Specifications

Full feature specifications live in `specs/001-kyc-document-processing/`:

| File | Contents |
|------|---------|
| `spec.md` | User stories (P1–P6), acceptance scenarios, requirements FR-001–FR-029 |
| `plan.md` | 10-phase implementation plan |
| `tasks.md` | Granular task breakdown |
| `data-model.md` | Full data schema reference |
| `contracts/` | API and agent I/O contracts |
| `quickstart.md` | Quick setup guide |
| `research.md` | Background research and design decisions |
