# Architecture

## Overview

The KYC Maker Automation system is a multi-agent document processing pipeline that ingests
investor onboarding packets (PDFs and structured files), extracts and classifies every
natural person named in those documents, and produces a structured CSM/NON-CSM report for
compliance review. The pipeline is orchestrated by LangGraph, which treats each processing
step — extraction, validation, reconciliation, classification — as a discrete graph node
whose transitions are controlled by critic agents that enforce quality gates before
advancing.

The core design decision is strict separation between *configuration* and *execution*. All
agent behaviour (model, prompts, temperature, retry limits, output schemas) lives in
`src/config/agents.yaml`; all topology (nodes, edges, routing, checkpointer) lives in
`src/config/workflows.yaml`. No agent name, model string, or prompt path is hardcoded in
Python source. The factory in `src/core/agent_factory.py` reads these files at runtime and
constructs LangGraph-compatible callables dynamically. This makes the entire pipeline
reconfigurable without code changes.

State is immutable by convention: every agent receives a `WorkflowState` TypedDict and
returns a *new* TypedDict with updated fields — no mutation in place. Critics write a
`CriticFeedback` object to `last_critic_feedback`; a single generic router
(`route_on_critic_decision`) reads it and emits `"pass"`, `"fail_retry"`, or `"fail_max"`.
This means adding a new critic requires only a YAML entry — no new Python routing function.

## System diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                         FastAPI / WebSocket                          │
│  POST /workflows/start   GET /workflows/{id}   WS /workflows/{id}    │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ DocumentInput[]
                                ▼
                     ┌──────────────────┐
                     │  WorkflowService │  creates WorkflowState, runs graph
                     └────────┬─────────┘
                              │ LangGraph .invoke()
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        LangGraph Workflow                           │
│                                                                     │
│  START ──► extractor ──► extractor_critic_router ──► critic_1      │
│                                        │                │           │
│                               pass ◄──┘    fail_retry──┘           │
│                                │           fail_max ──► END(fail)  │
│                                ▼                                    │
│                          reconciler ──► critic_2 (rule)            │
│                                │                                    │
│                          classifier ──► critic_3 (rule)            │
│                                │                                    │
│                           formatter ──► END(success)               │
└─────────────────────────────────────────────────────────────────────┘
                              │
                    WorkflowState (final)
                              │
                    ┌─────────▼──────────┐
                    │  AuditService      │  SHA-256 checksums, SQLite
                    │  StorageService    │  file persistence
                    └────────────────────┘
```

## Components

### agent_factory

- **Location**: `src/core/agent_factory.py`
- **Purpose**: Builds LangGraph-compatible agent callables from `agents.yaml` config at runtime — the single place where LLM providers are instantiated and prompt templates are loaded.
- **Inputs**: Agent name, merged agent config dict, path to agents directory
- **Outputs**: `(state: WorkflowState) -> WorkflowState` callable
- **Key types/interfaces**: `build_agent_fn(agent_name, agent_cfg, agents_dir) -> Callable`
- **Design notes**: Two execution paths — `execution: llm` builds a structured-output LangChain chain; `execution: rule` resolves a dotted-path callable and wraps it. Schema classes are resolved once at build time (fail-fast), not per invocation.

### workflow compiler

- **Location**: `src/core/workflow.py`
- **Purpose**: Reads `workflows.yaml` and assembles a compiled LangGraph `StateGraph` — translates declarative YAML topology into `add_node` / `add_edge` / `add_conditional_edges` calls.
- **Inputs**: Paths to `agents.yaml` and `workflows.yaml`; optional checkpointer URI
- **Outputs**: Compiled `CompiledStateGraph` ready for `.invoke()` / `.stream()`
- **Key types/interfaces**: `compile_workflow() -> CompiledStateGraph`
- **Design notes**: Router nodes (type: `router`) are wired with `add_conditional_edges`; the routing function is resolved from `conditions.route_on_critic_decision` via dotted path. Regular nodes are wrapped in a thin lambda that increments the `on_traverse.increment_key` counter before delegating to the agent function.

### WorkflowState

- **Location**: `src/core/state.py`
- **Purpose**: Single shared state object that flows through every graph node — carries inputs, intermediate results, retry counters, critic feedback, and final outputs.
- **Inputs**: `DocumentInput[]` at workflow start
- **Outputs**: `csm_list`, `non_csm_list`, `csm_report` at graph end
- **Key types/interfaces**: `WorkflowState` (TypedDict); `create_initial_state()`, `update_workflow_failed()`
- **Design notes**: `total=False` so every field is optional — agents only assert the fields they read. Immutable update pattern: all helpers return `WorkflowState(**{**state, key: value})`.

### config loader

- **Location**: `src/config/loader.py`
- **Purpose**: Loads and validates `agents.yaml` and `workflows.yaml` against JSON Schema, performs semantic cross-validation (e.g. every `agents_ref` node references a known agent key), and merges per-agent config with `defaults`.
- **Inputs**: YAML file paths
- **Outputs**: Validated dicts consumed by `agent_factory` and `workflow compiler`
- **Key types/interfaces**: `ConfigError`, `ConfigValidationError`

### FastAPI app

- **Location**: `src/api/main.py`, `src/api/routes/`
- **Purpose**: HTTP and WebSocket interface — accepts document uploads, starts workflows, streams events to clients, exposes workflow status and audit log endpoints.
- **Inputs**: Multipart file uploads, workflow IDs
- **Outputs**: JSON responses; WebSocket event stream (start, agent_complete, completed, failed)
- **Key types/interfaces**: FastAPI `APIRouter` per route group

### AuditService

- **Location**: `src/services/audit.py`
- **Purpose**: Writes immutable audit log entries for every workflow action with SHA-256 checksums; enforces 7-year retention.
- **Inputs**: Workflow ID, action name, payload
- **Outputs**: `audit_logs` table rows (SQLite via SQLAlchemy)
- **Design notes**: UPDATE and DELETE are prevented at the database trigger level — audit entries are append-only by design (FR-029).

### DocumentService

- **Location**: `src/services/document.py`
- **Purpose**: Extracts raw text from PDFs and structured files; normalises encoding and produces `DocumentInput` objects consumed by the extractor agent.
- **Inputs**: Uploaded file bytes (PDF, DOCX, structured)
- **Outputs**: `DocumentInput` (filename, content, mime_type)

## Data model

```
audit_logs
  id            INTEGER PK
  workflow_id   TEXT
  action        TEXT
  payload       TEXT (JSON)
  checksum      TEXT (SHA-256)
  created_at    TIMESTAMP

workflows
  id            TEXT PK (UUID)
  status        TEXT  (pending | in_progress | completed | failed)
  created_at    TIMESTAMP
  completed_at  TIMESTAMP NULL
  failure_reason TEXT NULL
```

## Design decisions

1. **Configuration-driven agent factory over individual agent files**

   *Choice*: All agents are built by one factory reading `agents.yaml`; no per-agent Python files.
   *Alternatives considered*: Individual `extractor.py`, `critic.py` files with hardcoded config.
   *Rationale*: Eliminates duplication; allows prompt/model changes without touching Python; makes adding a new agent a YAML-only operation.

2. **Single generic critic router (`route_on_critic_decision`)**

   *Choice*: One routing function reads `last_critic_feedback.decision` and returns `"pass"` / `"fail_retry"` / `"fail_max"` for all critics.
   *Alternatives considered*: Per-critic routing functions (`route_on_critic_1`, `route_on_critic_2`).
   *Rationale*: The routing logic is identical for every critic — only the feedback writer differs. One function means one place to change retry semantics across the whole pipeline.

3. **Immutable state updates**

   *Choice*: Every node returns a new `WorkflowState(**{**state, key: value})` — no in-place mutation.
   *Alternatives considered*: Mutable dict; dataclass with `__setattr__`.
   *Rationale*: LangGraph checkpointing and replay require stable snapshots. Immutable updates make it trivial to reproduce any intermediate state from the checkpoint store.

4. **Rule-based critics declared in YAML with `execution: rule`**

   *Choice*: Critics that apply deterministic rules are Python functions resolved at runtime via dotted path in `rule_fn`.
   *Alternatives considered*: Separate node type; hardcoded `if` branches in workflow compiler.
   *Rationale*: Keeps the factory pattern universal — both LLM and rule agents are configured identically in YAML and built by the same public API.

5. **Router nodes (type: router) as explicit graph nodes**

   *Choice*: Critic routing is a dedicated node in the graph, not a `conditional_edge` function that mutates state.
   *Alternatives considered*: Inline `conditional_edge` functions that wrote to state before returning a route string.
   *Rationale*: LangGraph docs warn against state mutation inside conditional edge functions. A router node is a proper node that can safely write state and then route.

## External dependencies

| Dependency | Version | Purpose | Alternatives considered |
|---|---|---|---|
| `langgraph` | ≥0.2.0 | Multi-agent workflow orchestration with checkpointing | LangChain LCEL chains (no persistent graph state), Prefect (heavyweight) |
| `langchain-openai` / `langchain-google-genai` | latest | Chat model wrappers for OpenAI and Gemini | Direct SDK calls (loses `with_structured_output` and provider abstraction) |
| `fastapi` | ≥0.115.0 | HTTP API and WebSocket server | Flask (no async-native WebSocket), Django (too heavy) |
| `pdfplumber` | ≥0.11.0 | PDF text extraction with layout awareness | PyPDF2 (less accurate on complex layouts), pdfminer (lower-level API) |
| `rapidfuzz` | ≥3.10.0 | Fuzzy string matching for person deduplication | fuzzywuzzy (deprecated, slower), difflib (no token-set ratio) |
| `sqlalchemy` | latest | ORM for audit log and workflow persistence | Raw sqlite3 (no migration support), Tortoise ORM (async-only, less mature) |

<!-- generated-by: project-docs-skill -->
