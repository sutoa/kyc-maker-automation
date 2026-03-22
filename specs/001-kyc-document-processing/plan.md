# Implementation Plan: KYC Document Processing Agentic Workflow

**Branch**: `001-kyc-document-processing` | **Date**: 2025-03-22 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-kyc-document-processing/spec.md`

## Summary

Build a multi-agent KYC document processing system that extracts person information from German HandelsRegister and English documents, deduplicates records, classifies individuals as CSM or Non-CSM with explicit reasoning, and provides real-time workflow monitoring with full audit trails. The system uses declarative YAML-based agent configuration with critic-based quality gates at every step.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: LangGraph (multi-agent orchestration), FastAPI (web API), PyPDF2/pdfplumber (PDF extraction)
**LLM Integration**: Model-agnostic abstraction supporting OpenAI and Gemini via `LLM_PROVIDER` env var
**Storage**: SQLite for MVP (workflow state, audit logs); file system for document storage
**Testing**: pytest with pytest-asyncio for async agent testing
**Target Platform**: Linux/macOS server (Docker-ready)
**Project Type**: Web service with real-time UI
**Performance Goals**: <5 minutes for typical 1-10 page document sets; <2 second UI updates
**Constraints**: 7-year data retention; German/English language support; single-user MVP
**Scale/Scope**: Single user, ~10-50 documents per day for MVP

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Accuracy First | ✅ PASS | FR-006 mandates source provenance; FR-015 requires explicit classification reasoning |
| II. Multi-Agent Quality Gates | ✅ PASS | FR-008/009/010/011 implement 3-outcome critic routing with 4-retry cap |
| III. Declarative Agent Configuration | ✅ PASS | FR-019/020/021 require YAML config with transitions |
| IV. Observability by Design | ✅ PASS | FR-022/023/024/026/027 cover tracing, real-time UI, audit logs |
| V. Test-First Development | ✅ PASS | Constitution requires tests; plan includes test structure |
| VI. Consistency & Deduplication | ✅ PASS | FR-012/012a/013 implement fuzzy matching and conflict detection |
| VII. Structured Error Handling | ✅ PASS | Edge cases define retry/fail behavior; LLM retry with backoff |
| VIII. Security & Data Protection | ✅ PASS | MVP is network-restricted; no auth needed; sensitive data handling in audit logs |
| IX. Model-Agnostic AI | ✅ PASS | LLM abstraction layer planned; env var configuration |

**Gate Status**: ✅ ALL PRINCIPLES SATISFIED - Proceed to Phase 0

## Project Structure

### Documentation (this feature)

```text
specs/001-kyc-document-processing/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks command)
```

### Source Code (repository root)

```text
src/
├── agents/              # Agent definitions and implementations
│   ├── extractor.py     # Document extraction agent
│   ├── critic.py        # Quality review agents (critic_1, critic_2, critic_3)
│   ├── reconciler.py    # Deduplication and conflict detection
│   ├── classifier.py    # CSM/Non-CSM classification
│   └── formatter.py     # Output formatting agent
├── config/
│   ├── agents.yaml      # Declarative agent configurations
│   ├── schemas/         # JSON schemas for config validation
│   └── workflows.yaml   # Workflow routing definitions
├── core/
│   ├── llm/             # Model-agnostic LLM abstraction
│   │   ├── base.py      # Abstract LLM interface
│   │   ├── openai.py    # OpenAI implementation
│   │   └── gemini.py    # Gemini implementation
│   ├── workflow.py      # LangGraph workflow orchestration
│   └── state.py         # Workflow state management
├── models/              # Data models (Pydantic)
│   ├── person.py        # Person, SourceReference entities
│   ├── workflow.py      # WorkflowRun, AgentExecution entities
│   └── output.py        # ClassificationResult, DocumentManifest
├── services/
│   ├── document.py      # PDF/TXT extraction service
│   ├── matching.py      # Fuzzy name matching service
│   └── storage.py       # SQLite storage for workflows/audit
├── api/
│   ├── main.py          # FastAPI application
│   ├── routes/          # API endpoints
│   │   ├── workflows.py # Workflow CRUD, trigger, status
│   │   └── documents.py # File upload handling
│   └── websocket.py     # Real-time status updates
├── prompts/             # External prompt files
│   ├── extractor.md
│   ├── critic_1.md
│   ├── reconciler.md
│   ├── classifier.md
│   └── csm_definition.md
└── ui/                  # Frontend (if needed, or defer to separate repo)

tests/
├── contract/            # Agent input/output schema tests
├── integration/         # Multi-agent workflow tests
├── unit/                # Individual function tests
└── fixtures/            # Sample HandelsRegister documents
```

**Structure Decision**: Web application structure with backend API and separate frontend. The backend follows a layered architecture: agents → services → models → storage. Frontend may be a separate project or embedded SPA.

## Complexity Tracking

> No constitution violations to justify.

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| LLM Abstraction Layer | Required | Constitution Principle IX mandates model-agnostic implementation |
| SQLite for MVP | Chosen | Simpler than PostgreSQL; sufficient for single-user MVP; easy migration path |
| LangGraph | Chosen | Native support for conditional routing, state management, and LangSmith observability |
