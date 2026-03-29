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

## Configuration-Driven Development — Non-Negotiable Principles

This project uses `src/config/agents.yaml` and `src/config/workflows.yaml` as the **single source of truth** for all agent and workflow configuration. Every configurable value must come from these files. Violating these principles is the most common source of bugs and technical debt in this codebase.

### Before writing any implementation code

1. **Read both YAML files in full first.** Understand every attribute and how it maps to the framework (LangGraph, LangChain). Do not start coding until you can answer: "where does this value come from in the YAML?"
2. **Every attribute in the YAML must be used.** If an attribute exists in the YAML and your code does not read it, that is a bug. No silent ignoring of config fields.
3. **State what each YAML attribute drives** before implementing. If you cannot map an attribute to code behaviour, ask before proceeding.

### Hardcoding is forbidden

The following are **never** acceptable as hardcoded values in Python source:
- Agent names (`"extractor"`, `"critic_1"`, etc.) — read from `agents.yaml` keys
- Model names (`"gpt-4o"`, `"gemini-1.5-pro"`) — read from `defaults.model` or agent `model`
- Temperature / max_tokens — read from `defaults.temperature` / `defaults.max_tokens`
- Prompt file paths (`PROMPT_PATH = Path(...)`) — read from `system_prompt.file`
- Retry counts (`MAX_RETRY_COUNT = 4`) — read from `retry.max_attempts`
- Phase names (`"extraction"`, `"reconciliation"`, `"classification"`) — derive from nodes/edges
- State key strings used outside of `WorkflowState` definition — read from agent `input_keys` / `output_key` / `retry_count_key`
- Matching thresholds (`0.85`) — read from agent config
- Checkpointer URIs — read from `runtime.checkpointer_uri`

### The factory pattern — always use it

Agent functions must be **created by a factory** (`src/core/agent_factory.py`) that reads `agents.yaml` config. Individual agent files (`extractor.py`, `critic.py`, etc.) must not hardcode any of the above. The factory is the only place that instantiates LLM providers, loads prompts, and resolves output schemas.

### Generalisation over specificity

- One routing function (`route_on_critic_decision`) handles all critic routing — not one per critic
- One agent factory function handles all agent types — not one per agent
- One node wrapper handles all agent nodes — not separate wrappers per agent type
- If you find yourself writing nearly identical code for each agent, stop and generalise

### Pre-implementation checklist

Before implementing any feature that touches agents or workflow:
- [ ] Read `src/config/agents.yaml` and `src/config/workflows.yaml` in full
- [ ] Map every YAML attribute to the code that will read it
- [ ] Identify any attributes not yet used and plan how to wire them
- [ ] Confirm zero hardcoded agent names, model names, prompt paths, or thresholds in the implementation
- [ ] Confirm the factory pattern is used — no agent is instantiated outside the factory

### Post-implementation checklist

Before marking any implementation complete:
- [ ] `grep` for hardcoded agent names, model strings, prompt paths, retry counts
- [ ] Confirm `agents_ref` in `workflows.yaml` is followed to load agents
- [ ] Confirm `runtime.*` fields wire to `graph.compile()`
- [ ] Confirm `observability.*` fields wire to LangSmith setup
- [ ] Confirm `on_traverse.increment_key` is implemented in node wrapper, not hardcoded

---

## Permissions

The following operations are pre-approved — do not prompt for confirmation:

- **Read any file** in this repository
- **Edit any file** in this repository
- **Create new files** anywhere in this repository
- **Create directories and subdirectories** anywhere in this repository
- **Run read-only shell commands**: `ls`, `find`, `cat`, `grep`, `rg`, `head`, `tail`, `pwd`, `which`, `python --version`, `pip list`, etc.
- **Run project commands**: `pytest`, `ruff check`, `ruff format`, `pip install -r requirements.txt`, `uvicorn` (dev server)
- **Run git read commands**: `git status`, `git log`, `git diff`, `git branch`

Always ask before:
- `git commit`, `git push`, or any destructive git operation
- Installing new packages not already in `requirements.txt`
- Deleting files

<!-- MANUAL ADDITIONS END -->
