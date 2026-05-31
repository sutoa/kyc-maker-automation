# kyc-maker-automation

![Python](https://img.shields.io/badge/python-3.11+-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-blue)

> A multi-agent LLM pipeline that extracts, validates, and classifies persons from KYC documents — turning uploaded PDFs into structured CSM/NON_CSM compliance reports.

KYC due diligence requires reading corporate documents to identify Controlling Senior Managers (CSMs) — a task that is slow, error-prone, and expensive when done manually. This system automates the entire pipeline: upload one or more PDFs, and a chain of specialised LLM agents extracts every named person, validates extraction quality through a critic-gated retry loop, and produces a structured JSON compliance report. The entire agent topology — models, prompts, retry limits, routing logic — is declared in YAML, making the pipeline reconfigurable without touching Python code.

## Features

- **YAML-driven agent pipeline** — model names, temperatures, prompt file paths, retry limits, and state key names are all read from `src/config/agents.yaml` at startup; no hardcoded agent identifiers or model strings in Python source
- **Dual LLM provider support** — switch between OpenAI and Google Gemini by changing one env var (`LLM_PROVIDER`); adding a new provider requires only one line in `agent_factory.py`
- **PDF extraction with page provenance** — pdfplumber extracts text with page boundaries preserved; PyMuPDF is the fallback for malformed PDFs and scanned documents; every extracted person carries source page references for auditor verification
- **Critic-gated quality loop** — after extraction, a dedicated critic LLM validates mandatory fields and source references; failed checks inject specific feedback into the next extraction attempt, retrying up to 4 times before the workflow fails
- **Atomic state routing via LangGraph Command** — the critic router updates state and selects the next node in a single atomic `Command`, avoiding the state-mutation-inside-conditional-edge bug
- **Immutable audit trail** — every workflow event is logged with a SHA-256 checksum; no UPDATE or DELETE is permitted at the service or database level; 7-year retention enforced at the DB level (FR-029)
- **Real-time progress via WebSocket** — clients subscribe to `/ws/workflows/{workflow_id}` and receive structured JSON events as each agent completes
- **SQLite checkpointing** — LangGraph persists state to SQLite after every node; workflows resume from the last checkpoint after a process restart

## Requirements

- Python 3.11+
- OpenAI API key (`sk-...`) **or** Google API key — at least one LLM provider key is required
- No external services; SQLite is embedded

## Installation

```bash
# Create and activate a virtual environment
python -m venv .venv && source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment variables
cp .env.example .env
# Edit .env: set OPENAI_API_KEY (or GOOGLE_API_KEY if using Gemini)

# Initialise the database
python -c "from src.services.database import init_db; init_db()"

# Start the API server
uvicorn src.api.main:app --reload --port 8000
```

New to the project? See [Getting Started](docs/getting-started.md) for a full walkthrough including virtual environment setup and first-run troubleshooting.

## Quick Start

### Step 1 — Upload documents and create a workflow

```bash
curl -X POST http://localhost:8000/api/v1/workflows \
  -F "files=@ownership_register.pdf" \
  -F "files=@articles_of_incorporation.pdf"
```

Expected response:
```json
{
  "workflow_id": "a3f9c1d2-7b4e-4c1a-9f2e-3d8b5a6c7e9f",
  "status": "pending",
  "created_at": "2026-05-31T09:00:00Z",
  "documents": [
    { "document_id": "d1a2b3...", "filename": "ownership_register.pdf", "file_type": "PDF", "page_count": 12 },
    { "document_id": "e5f6g7...", "filename": "articles_of_incorporation.pdf", "file_type": "PDF", "page_count": 8 }
  ]
}
```

### Step 2 — Start processing

```bash
curl -X POST http://localhost:8000/api/v1/workflows/a3f9c1d2-.../start
```

Follow real-time progress in a second terminal:

```bash
# Install wscat once: npm install -g wscat
wscat -c ws://localhost:8000/ws/workflows/a3f9c1d2-...
# ← {"event":"agent_started","agent":"extractor","timestamp":"..."}
# ← {"event":"agent_completed","agent":"extractor","timestamp":"..."}
# ← {"event":"agent_completed","agent":"extractor_critic","timestamp":"..."}
# ← {"event":"workflow_completed","workflow_id":"a3f9c1d2-...","timestamp":"..."}
```

Or poll status:

```bash
curl http://localhost:8000/api/v1/workflows/a3f9c1d2-...
```

### Step 3 — Download the report

Once `status` is `"completed"`:

```bash
curl -o report.json \
  http://localhost:8000/api/v1/workflows/a3f9c1d2-.../output
```

The report is a JSON file containing all extracted persons classified as CSM or NON_CSM, with titles, source documents, and page references.

## API Reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/workflows` | Create workflow and upload documents (multipart) |
| `POST` | `/api/v1/workflows/{id}/start` | Start pipeline processing |
| `GET` | `/api/v1/workflows/{id}` | Get status, document list, and extraction summary |
| `GET` | `/api/v1/workflows/{id}/output` | Download the compliance report (JSON) |
| `GET` | `/api/v1/workflows` | List workflow history (paginated, filterable by status) |
| `GET` | `/api/v1/workflows/{id}/trace` | Per-agent execution trace with retry counts and critic feedback |
| `POST` | `/api/v1/documents/upload` | Upload a document to an existing workflow |
| `GET` | `/api/v1/documents/{id}` | Get document metadata |
| `GET` | `/api/v1/workflows/{id}/documents` | List all documents for a workflow |
| `WS` | `/ws/workflows/{workflow_id}` | Real-time agent event stream |

Interactive API docs (Swagger UI): `http://localhost:8000/api/v1/docs`

## Architecture

Three layers: a **FastAPI HTTP surface** (`src/api/`) accepts documents and manages workflow lifecycle; the **LangGraph workflow engine** (`src/core/`) compiles and executes the agent pipeline from YAML at startup; the **services layer** (`src/services/`) handles PDF extraction, persistence, and audit.

Active pipeline: `Extractor (LLM)` → `ExtractorCritic (LLM)` → `CriticRouter (rule)` → `Formatter (LLM)`

All agent configuration (models, prompts, retry limits, state keys) lives in `src/config/agents.yaml`. Graph topology (nodes, edges, checkpointer) lives in `src/config/workflows.yaml`. Python source contains no hardcoded agent names, model strings, or threshold values — the factory builds everything dynamically from YAML.

- Component breakdown, data model, and design decisions → [docs/architecture.md](docs/architecture.md)
- Request lifecycle and Mermaid sequence diagrams → [docs/data-flow.md](docs/data-flow.md)

## Configuration

Required before first run:

| Variable | When required |
|---|---|
| `OPENAI_API_KEY` | `LLM_PROVIDER=openai` (the default) |
| `GOOGLE_API_KEY` | `LLM_PROVIDER=gemini` |

Full reference (15 variables with defaults and valid values) → [docs/configuration.md](docs/configuration.md)

Agent-level overrides (model, temperature, max_tokens, retry policy) are set per-agent in `src/config/agents.yaml`.

## Documentation

- [docs/getting-started.md](docs/getting-started.md) — step-by-step setup from install to first report, with error troubleshooting
- [docs/architecture.md](docs/architecture.md) — component breakdown, data model, design decisions, external dependencies
- [docs/data-flow.md](docs/data-flow.md) — request lifecycle and Mermaid sequence diagrams for each pipeline phase
- [docs/configuration.md](docs/configuration.md) — full env var reference and annotated agents.yaml / workflows.yaml examples
- [docs/development.md](docs/development.md) — local setup, test commands, how to add a new agent or API endpoint
- [docs/deep-dive.md](docs/deep-dive.md) — implementation deep-dives (compile_workflow and more)

## Contributing

Open an issue or submit a pull request. See the `specs/` directory for feature specifications and implementation plans.

## License

MIT. See [LICENSE](LICENSE).

<!-- generated-by: project-docs-skill -->
