# Configuration

The system uses two configuration layers: **environment variables** (runtime secrets and deployment settings, loaded from `.env`) and **YAML config files** (`src/config/agents.yaml` and `src/config/workflows.yaml` for agent behaviour and workflow topology). Environment variables take precedence over defaults in `pydantic-settings`. YAML files are read at startup and are not reloaded without a process restart.

## Environment variables

### LLM Provider

| Variable | Required | Default | Valid values | Description |
|---|---|---|---|---|
| `LLM_PROVIDER` | No | `openai` | `openai`, `gemini` | Selects which LLM backend all agents use |
| `OPENAI_API_KEY` | If `LLM_PROVIDER=openai` | — | — | OpenAI API key; required for all LLM agents when using OpenAI |
| `OPENAI_MODEL` | No | `gpt-4o-mini` | Any OpenAI model name | Default model; overridable per-agent in `agents.yaml` |
| `GOOGLE_API_KEY` | If `LLM_PROVIDER=gemini` | — | — | Google API key for Gemini |
| `GEMINI_MODEL` | No | `gemini-1.5-pro` | Any Gemini model name | Default Gemini model |

### Database

| Variable | Required | Default | Valid values | Description |
|---|---|---|---|---|
| `DATABASE_URL` | No | `sqlite:///./kyc_workflows.db` | Any SQLAlchemy URL | Database for workflow runs, documents, and audit logs |

### File storage

| Variable | Required | Default | Description |
|---|---|---|---|
| `UPLOAD_DIR` | No | `./uploads` | Directory where uploaded PDFs/TXTs are stored; created on startup if missing |
| `OUTPUT_DIR` | No | `./output` | Directory where JSON compliance reports are saved after completion |
| `MAX_FILE_SIZE_MB` | No | `50` | Maximum upload size per file in megabytes |

### API server

| Variable | Required | Default | Description |
|---|---|---|---|
| `API_HOST` | No | `0.0.0.0` | Uvicorn bind address |
| `API_PORT` | No | `8000` | Uvicorn bind port |
| `CORS_ORIGINS` | No | `http://localhost:3000,http://localhost:8000` | Comma-separated list of allowed CORS origins |

### Workflow runtime

| Variable | Required | Default | Description |
|---|---|---|---|
| `MAX_RETRY_ATTEMPTS` | No | `4` | Maximum times a critic can send an agent back for retry before the workflow fails |
| `LLM_RETRY_ATTEMPTS` | No | `3` | Number of transient-error retries for LLM API calls (rate limits, network errors) |
| `LLM_RETRY_MIN_WAIT` | No | `2` | Minimum wait in seconds between LLM retries |
| `LLM_RETRY_MAX_WAIT` | No | `30` | Maximum wait in seconds between LLM retries (exponential backoff cap) |

### Logging

| Variable | Required | Default | Valid values | Description |
|---|---|---|---|---|
| `LOG_LEVEL` | No | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | Python root logging level |

## Configuration files

### `src/config/agents.yaml` — agent behaviour

The primary configuration file. Every agent reads all its settings from here — no agent-specific values are hardcoded in Python.

```yaml
version: "1.2"

defaults:                         # inherited by all agents unless overridden
  model: openai/gpt-4o-mini      # provider/model-name — openai/* or gemini/*
  temperature: 0                  # 0.0–1.0; 0 = deterministic
  max_tokens: 16384
  retry:
    max_attempts: 4               # critic-gate retries (not LLM transient retries)
    backoff: exponential          # linear | exponential | fixed
    delay_seconds: 1

agents:
  extractor:
    role: "KYC Document Extraction Specialist"
    goal: "Extract all person records..."
    backstory: |
      ...
    execution: llm                # llm | rule
    input_keys: [documents, extractor_critic_feedback]   # state keys read as context
    output_key: extracted_persons                         # state key written
    output_schema:
      ref: src.models.person.ExtractedPerson  # Pydantic class for structured output
      is_list: true                            # wrap output in list container
    system_prompt:
      file: ../prompts/extractor.md            # path relative to agents.yaml

  extractor_critic:
    execution: llm
    input_keys: [extracted_persons]
    output_key: extractor_critic_feedback
    output_schema:
      ref: src.models.workflow.ExtractorCriticFeedback
      is_list: false
    system_prompt:
      file: ../prompts/extractor_critic.md

  formatter:
    execution: llm
    input_keys: [extracted_persons]
    output_key: csm_report        # no output_schema → raw string output
    system_prompt:
      file: ../prompts/formatter.md
```

**Commented-out agents** (`reconciler`, `critic_2`, `classifier`, `critic_3`) are present in the file but disabled. Re-enabling them requires:
1. Uncommenting the agent definition in `agents.yaml`
2. Uncommenting the corresponding node and edges in `workflows.yaml`

### `src/config/workflows.yaml` — graph topology and runtime

```yaml
version: "1.2"

workflow:
  id: kyc_document_processing
  max_steps: 30                   # LangGraph recursion limit
  timeout_seconds: 600            # wall-clock timeout for entire pipeline

agents_ref: ./agents.yaml         # path to agent definitions

state:                            # WorkflowState field declarations
  workflow_id: { type: string }
  documents:   { type: object, default: [] }
  # ... (see src/core/state.py for the full TypedDict)

nodes:
  extractor:               { type: agent, agent: extractor }
  critic_1:                { type: agent, agent: extractor_critic }
  extractor_critic_router: { type: router, fn: src.core.conditions.route_on_extractor_critic_decision }
  formatter:               { type: agent, agent: formatter }
  end:                     { type: end }

edges:
  - from: __start__
    to: extractor
  - from: extractor
    to: critic_1
  - from: critic_1
    to: extractor_critic_router
  - from: formatter
    to: end

observability:
  provider: langsmith              # langsmith | langfuse | none
  project: kyc_document_processing

runtime:
  framework: langgraph
  checkpointer: sqlite             # sqlite | postgres | memory | redis
  checkpointer_uri: "sqlite:///./kyc_workflows.db"
```

## Secrets management

- **Never commit `.env` to version control.** The repository's `.gitignore` excludes it. Keep `.env.example` updated with all variables but no real values.
- **API keys** (`OPENAI_API_KEY`, `GOOGLE_API_KEY`) should be rotated immediately if accidentally exposed. They have no system-level scope restriction — any person with a key can make API calls billed to your account.
- **Production deployments**: inject secrets via environment variables from your platform's secret store (AWS Secrets Manager, GCP Secret Manager, Kubernetes Secrets). Do not write them to disk.
- **`DATABASE_URL`**: if switching to PostgreSQL for production, use a connection string with a dedicated low-privilege user that has no DDL permissions.

<!-- generated-by: project-docs-skill -->
