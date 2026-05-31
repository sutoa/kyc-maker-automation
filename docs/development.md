# Development Guide

## Project structure

```
kyc-maker-automation/
├── src/
│   ├── api/                    # FastAPI application
│   │   ├── main.py             # App factory, lifespan, CORS, error handlers
│   │   ├── dependencies.py     # Shared FastAPI dependencies (db session, settings)
│   │   ├── errors.py           # Error codes and response models
│   │   ├── websocket.py        # WebSocket connection manager
│   │   └── routes/
│   │       ├── documents.py    # Document upload and query endpoints
│   │       └── workflows.py    # Workflow lifecycle endpoints
│   ├── config/
│   │   ├── agents.yaml         # Agent definitions (model, prompts, schema, retry)
│   │   ├── workflows.yaml      # Graph topology, state schema, runtime config
│   │   ├── loader.py           # YAML loader and agent function builder
│   │   └── schemas/            # JSON schemas for config validation
│   ├── core/
│   │   ├── workflow.py         # LangGraph StateGraph compiler and executor
│   │   ├── agent_factory.py    # Builds agent callables from YAML config
│   │   ├── conditions.py       # Critic routing functions (referenced in YAML)
│   │   ├── state.py            # WorkflowState TypedDict and helpers
│   │   ├── events.py           # WebSocket event emitter
│   │   └── llm/                # LLM provider abstraction
│   ├── models/
│   │   ├── person.py           # ExtractedPerson, ReconciledPerson, ClassifiedPerson
│   │   ├── workflow.py         # CriticFeedback, ExtractorCriticFeedback
│   │   ├── output.py           # DocumentManifestEntry, report models
│   │   └── enums.py            # FileType, WorkflowStatus, CriticDecision
│   ├── prompts/                # Markdown prompt templates for each LLM agent
│   │   ├── extractor.md
│   │   ├── extractor_critic.md
│   │   └── formatter.md
│   └── services/
│       ├── document.py         # PDF/TXT text extraction (pdfplumber + PyMuPDF)
│       ├── audit.py            # Immutable audit log service
│       ├── storage.py          # SQLAlchemy CRUD for workflow and document tables
│       ├── database.py         # DB engine initialisation and session factory
│       └── matching.py         # Fuzzy name matching (rapidfuzz) for reconciler
├── tests/
│   ├── unit/                   # Isolated service and model tests
│   ├── integration/            # Full workflow tests with mocked LLMs
│   ├── contract/               # Agent input/output schema validation tests
│   └── fixtures/               # Shared test data (sample PDFs, mock states)
├── specs/                      # Feature specifications and implementation plans
│   └── 001-kyc-document-processing/
├── docs/                       # Generated documentation (you are here)
├── .env.example                # Template for environment variables
├── pyproject.toml              # Package metadata, tool config (pytest, ruff, mypy)
└── requirements.txt            # Runtime dependencies
```

## Local setup

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate

# 2. Install runtime + dev dependencies
pip install -r requirements.txt
pip install -e ".[dev]"

# 3. Configure environment
cp .env.example .env
# Edit .env — set OPENAI_API_KEY (or GOOGLE_API_KEY if using Gemini)

# 4. Initialise the database
python -c "from src.services.database import init_db; init_db()"

# 5. Start the API server
uvicorn src.api.main:app --reload --port 8000

# 6. Optional: install pre-commit hooks
pre-commit install
```

The API docs are at `http://localhost:8000/api/v1/docs`.

To reset the local database and uploads:
```bash
rm -f kyc_workflows.db
rm -rf uploads/
python -c "from src.services.database import init_db; init_db()"
```

## Running tests

```bash
# All tests
pytest

# Unit tests only
pytest -m unit

# Integration tests only (mocked LLMs — no real API calls)
pytest -m integration

# Contract tests (validate agent schema compliance)
pytest -m contract

# Single test file
pytest tests/unit/test_agent_factory.py -v

# With coverage report
pytest --cov=src --cov-report=term-missing

# Coverage with HTML report
pytest --cov=src --cov-report=html
open htmlcov/index.html
```

Integration tests mock LLM calls using `pytest-mock` — they require no API keys. Tests that need a database use a temporary in-memory SQLite instance via fixtures in `tests/fixtures/`.

## Linting and formatting

```bash
# Check linting
ruff check .

# Auto-fix linting issues
ruff check . --fix

# Format code
ruff format .

# Type checking
mypy src/

# Run all checks at once (same as pre-commit)
ruff check . && ruff format --check . && mypy src/
```

## Making changes

### Adding a new LLM agent

1. **Write the prompt** — create `src/prompts/<agent_name>.md`. Use `{{key}}` placeholders for state values the agent needs (e.g. `{{extracted_persons}}`).

2. **Define the output schema** — add or reuse a Pydantic model in `src/models/`. The model name becomes the `ref` in YAML.

3. **Add the agent to `agents.yaml`**:
   ```yaml
   agents:
     my_agent:
       role: "..."
       goal: "..."
       execution: llm
       input_keys: [state_key_1, state_key_2]
       output_key: my_output_key
       output_schema:
         ref: src.models.my_module.MyOutputModel
         is_list: false
       system_prompt:
         file: ../prompts/my_agent.md
   ```

4. **Wire into `workflows.yaml`**:
   ```yaml
   nodes:
     my_node:
       type: agent
       agent: my_agent
   edges:
     - from: previous_node
       to: my_node
     - from: my_node
       to: next_node
   ```

5. **Add `output_key` to `WorkflowState`** in `src/core/state.py`.

6. **Write a contract test** in `tests/contract/` verifying the agent's output schema.

### Adding a rule-based agent (critic)

Rule-based agents skip the LLM and call a Python function directly.

1. **Write the rule function** in `src/agents/critic.py` (or a new module):
   ```python
   def validate_my_output(state: WorkflowState) -> CriticFeedback:
       # inspect state, return CriticFeedback
   ```

2. **Add to `agents.yaml`**:
   ```yaml
   my_critic:
     execution: rule
     rule_fn: src.agents.critic.validate_my_output
     input_keys: [my_output_key]
     output_key: last_critic_feedback
     output_schema:
       ref: src.models.workflow.CriticFeedback
   ```

3. **Wire into `workflows.yaml`** like any other agent node. Attach a conditional edge from the critic back to the preceding agent using `src.core.conditions.route_on_critic_decision`.

### Adding a new API endpoint

1. Add the route handler to the appropriate file in `src/api/routes/` (or create a new file).
2. Define request/response Pydantic models in the same file.
3. Register the router in `src/api/main.py`:
   ```python
   from src.api.routes import my_routes
   app.include_router(my_routes.router, prefix="/api/v1/my-resource", tags=["My Resource"])
   ```
4. Write an API test in `tests/api/`.

## Useful commands

| Command | What it does |
|---|---|
| `uvicorn src.api.main:app --reload --port 8000` | Start API with hot reload |
| `python -c "from src.services.database import init_db; init_db()"` | Initialise DB schema |
| `pytest --cov=src --cov-report=term-missing` | Run tests with coverage |
| `ruff check . --fix && ruff format .` | Fix linting and format all files |
| `mypy src/` | Run type checker |
| `rm -f kyc_workflows.db && python -c "from src.services.database import init_db; init_db()"` | Reset local database |

## Debugging tips

1. **Enable SQL query logging** — set `SQL_ECHO=true` in `.env` to print every SQLAlchemy query to stdout. Useful for diagnosing slow workflows or missing audit records.

2. **Inspect LangGraph checkpoints** — the SQLite database contains a `checkpoints` table. Use `sqlite3 kyc_workflows.db "SELECT * FROM checkpoints ORDER BY ts DESC LIMIT 10;"` to see the most recent state snapshots and identify where a workflow stalled.

3. **Trace a failed workflow** — call `GET /api/v1/workflows/{id}/trace` to retrieve the per-agent execution trace. The response includes each agent's retry count, critic feedback, and decision for each step.

4. **LLM structured output failures** — if an agent consistently fails with a JSON decode or schema validation error, the most common cause is a mismatch between the prompt and the Pydantic output schema. Enable `LOG_LEVEL=DEBUG` to see the raw LLM response before parsing.

5. **Retry counter not incrementing** — if extraction keeps looping without the retry counter advancing, the critic router may be returning a plain string instead of a `Command`. Confirm that `extractor_critic_router` is declared as `type: router` (not a conditional edge) in `workflows.yaml`.

## Implementation deep-dives

For in-depth analysis of key functions — design decisions, complexity, sequence diagrams, consumers, known issues — see [docs/deep-dive.md](deep-dive.md).

Currently documented: `compile_workflow` (the graph construction pipeline in `src/core/workflow.py`).

<!-- generated-by: project-docs-skill -->
