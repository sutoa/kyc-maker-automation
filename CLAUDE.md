# kyc-maker-automation Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-03-24

## Active Technologies

- Python 3.11+ + LangGraph (multi-agent orchestration), FastAPI (web API), PyPDF2/pdfplumber (PDF extraction) (001-kyc-document-processing)

## Project Structure

```text
src/
├── agents/           # LLM-powered agents (extractor, reconciler, classifier, formatter, critic)
├── api/              # FastAPI application, routes, WebSocket handlers
│   └── routes/       # API endpoint definitions
├── config/           # YAML-based agent and workflow configuration
│   └── schemas/      # JSON schemas for config validation
├── core/             # Workflow engine, state management, event emission
│   └── llm/          # LLM provider abstraction (OpenAI, Gemini)
├── models/           # Pydantic data models
├── prompts/          # Agent prompt templates (markdown)
└── services/         # Business logic (document extraction, matching, audit, storage)

tests/
├── unit/             # Unit tests for services and models
├── integration/      # End-to-end workflow tests
├── contract/         # Agent contract validation tests
└── api/              # API endpoint tests

specs/
└── 001-kyc-document-processing/
    ├── spec.md       # Feature specification
    ├── plan.md       # Implementation plan
    ├── tasks.md      # Task breakdown
    └── quickstart.md # Getting started guide
```

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run tests
pytest

# Run tests with coverage
pytest --cov=src --cov-report=term-missing

# Run linting
ruff check .

# Format code
ruff format .

# Start API server (development)
uvicorn src.api.main:app --reload --port 8000

# Initialize database
python -c "from src.services.database import init_db; init_db()"
```

## Code Style

Python 3.11+: Follow standard conventions
- Type hints required for all functions
- Docstrings required for public functions and classes
- Use Pydantic for data validation
- Use SQLAlchemy for database operations

## Environment Variables

```bash
# LLM Provider Configuration
LLM_PROVIDER=openai          # or 'gemini'
OPENAI_API_KEY=sk-...        # Required if LLM_PROVIDER=openai
GOOGLE_API_KEY=...           # Required if LLM_PROVIDER=gemini

# Database
DATABASE_URL=sqlite:///./kyc_workflows.db

# File Upload
UPLOAD_DIR=./uploads
MAX_FILE_SIZE_MB=50

# Logging
SQL_ECHO=false               # Set to 'true' for SQL query logging
```

## Key Architecture Patterns

### Multi-Agent Workflow
The system uses LangGraph for orchestrating a multi-agent workflow:
- **Extractor**: Extracts person data from documents (LLM-powered)
- **Critic 1**: Validates extraction quality
- **Reconciler**: Deduplicates persons using fuzzy matching
- **Critic 2**: Validates reconciliation
- **Classifier**: Classifies persons as CSM/NON_CSM (LLM-powered)
- **Critic 3**: Validates classification reasoning
- **Formatter**: Produces final JSON output

### Critic Pattern (3-Outcome)
Each critic returns one of:
- `PASS`: Move to next agent
- `FAIL_RETRY`: Retry with feedback (up to 4 times)
- `FAIL_MAX`: Stop workflow with error

### State Management
- `WorkflowState` TypedDict flows through all agents
- Immutable state updates via helper functions in `src/core/state.py`

### Audit Trail
- All actions logged to `audit_logs` table with SHA-256 checksums
- Logs are immutable (UPDATE/DELETE prevented at database level)
- 7-year retention policy (FR-029)

## Testing Strategy

- **Unit tests**: Test services and utilities in isolation
- **Contract tests**: Verify agent input/output formats match contracts
- **Integration tests**: Test full workflow execution with mocked LLMs
- **API tests**: Test REST endpoints and WebSocket events

## Recent Changes

- 001-kyc-document-processing: Added Python 3.11+ + LangGraph (multi-agent orchestration), FastAPI (web API), PyPDF2/pdfplumber (PDF extraction)

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
