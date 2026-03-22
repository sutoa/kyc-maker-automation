# Tasks: KYC Document Processing Agentic Workflow

**Feature Branch**: `001-kyc-document-processing`
**Generated**: 2025-03-22
**Source**: [plan.md](./plan.md) | [spec.md](./spec.md)

## Legend

- `[P]` = Parallelizable (can run concurrently with other `[P]` tasks in same phase)
- `[S]` = Sequential (must complete before dependent tasks)
- `[US#]` = User Story reference
- Priority: Tasks ordered by dependency, not priority

---

## Phase 0: Project Setup

Foundation tasks that must complete before any feature work.

- [ ] T001 [S] Initialize Python 3.11+ project with pyproject.toml in `./`
- [ ] T002 [S] Create virtual environment and configure .gitignore in `./`
- [ ] T003 [S] Set up project directory structure per plan.md in `src/`, `tests/`
- [ ] T004 [P] Create requirements.txt with core dependencies (langgraph, fastapi, pdfplumber, rapidfuzz, sqlalchemy) in `./requirements.txt`
- [ ] T005 [P] Create .env.example with LLM_PROVIDER, OPENAI_API_KEY, GOOGLE_API_KEY, DATABASE_URL in `./.env.example`
- [ ] T006 [P] Configure pytest with pytest-asyncio in `./pyproject.toml`
- [ ] T007 [S] Create empty __init__.py files for all packages in `src/`

---

## Phase 1: Core Infrastructure

Foundational services and models required by all user stories.

### 1.1 Data Models (Pydantic)

- [ ] T010 [S] [US1-6] Define WorkflowStatus, FileType, CriticDecision enums in `src/models/enums.py`
- [ ] T011 [P] [US1] Define Person and ExtractedPerson models with mandatory/optional fields in `src/models/person.py`
- [ ] T012 [P] [US1] Define SourceReference model with document_id, page_number, confidence in `src/models/person.py`
- [ ] T013 [P] [US2] Define ReconciledPerson model with conflicts and normalized names in `src/models/person.py`
- [ ] T014 [P] [US3] Define ClassifiedPerson model with classification, reasoning, evidence in `src/models/person.py`
- [ ] T015 [P] [US1-6] Define WorkflowRun model with status, timestamps, failure_reason in `src/models/workflow.py`
- [ ] T016 [P] [US1-6] Define AgentExecution model with agent_name, payloads, retry_count in `src/models/workflow.py`
- [ ] T017 [P] [US1-6] Define CriticFeedback model with decision, issues, suggested_corrections in `src/models/workflow.py`
- [ ] T018 [P] [US4] Define DocumentManifestEntry model with filename, file_type, page_count, status in `src/models/output.py`
- [ ] T019 [P] [US4] Define WorkflowOutput model combining manifest and person lists in `src/models/output.py`

### 1.2 Database Layer (SQLAlchemy + SQLite)

- [ ] T020 [S] [US1-6] Create SQLAlchemy database connection and session management in `src/services/database.py`
- [ ] T021 [S] [US1-6] Define WorkflowRun SQLAlchemy table schema in `src/services/storage.py`
- [ ] T022 [P] [US1-6] Define UploadedDocument SQLAlchemy table schema in `src/services/storage.py`
- [ ] T023 [P] [US1-6] Define AgentExecution SQLAlchemy table schema in `src/services/storage.py`
- [ ] T024 [P] [US1-6] Define CriticFeedback SQLAlchemy table schema in `src/services/storage.py`
- [ ] T025 [P] [US1-6] Define Person SQLAlchemy table schema in `src/services/storage.py`
- [ ] T026 [P] [US1-6] Define SourceReference SQLAlchemy table schema in `src/services/storage.py`
- [ ] T027 [P] [US1-6] Define ClassificationResult SQLAlchemy table schema in `src/services/storage.py`
- [ ] T028 [P] [US1-6] Define AuditLog SQLAlchemy table schema (immutable) in `src/services/storage.py`
- [ ] T029 [S] [US1-6] Create database migration/initialization script in `src/services/database.py`
- [ ] T030 [S] [US1-6] Write unit tests for storage CRUD operations in `tests/unit/test_storage.py`

### 1.3 LLM Abstraction Layer (Constitution Principle IX)

- [ ] T040 [S] [US1-6] Define LLMProvider Protocol (abstract interface) with complete() method in `src/core/llm/base.py`
- [ ] T041 [S] [US1-6] Define Message and Response dataclasses in `src/core/llm/base.py`
- [ ] T042 [P] [US1-6] Implement OpenAIProvider with exponential backoff retry (3 attempts) in `src/core/llm/openai.py`
- [ ] T043 [P] [US1-6] Implement GeminiProvider with exponential backoff retry (3 attempts) in `src/core/llm/gemini.py`
- [ ] T044 [S] [US1-6] Create LLM provider factory based on LLM_PROVIDER env var in `src/core/llm/__init__.py`
- [ ] T045 [S] [US1-6] Write unit tests for LLM abstraction with mocked providers in `tests/unit/test_llm.py`

### 1.4 Document Extraction Service

- [ ] T050 [S] [US1] Create PDF text extraction using pdfplumber with page boundaries in `src/services/document.py`
- [ ] T051 [P] [US1] Create TXT file text extraction with page markers in `src/services/document.py`
- [ ] T052 [P] [US1] Add PyMuPDF fallback for problematic PDFs in `src/services/document.py`
- [ ] T053 [S] [US1] Create DocumentInput model for extracted content with page_count in `src/services/document.py`
- [ ] T054 [S] [US1] Write unit tests for PDF extraction with German characters in `tests/unit/test_document.py`
- [ ] T055 [P] [US1] Add sample HandelsRegister PDF to test fixtures in `tests/fixtures/`

### 1.5 Fuzzy Matching Service

- [ ] T060 [S] [US2] Implement name normalization (lowercase, unidecode for umlauts) in `src/services/matching.py`
- [ ] T061 [S] [US2] Implement Jaro-Winkler fuzzy matching with 0.85 threshold in `src/services/matching.py`
- [ ] T062 [S] [US2] Create is_same_person() function for duplicate detection in `src/services/matching.py`
- [ ] T063 [S] [US2] Write unit tests for German name matching (Müller/Mueller) in `tests/unit/test_matching.py`

---

## Phase 2: Agent Framework

LangGraph workflow infrastructure and declarative agent configuration.

### 2.1 Workflow State Management

- [ ] T070 [S] [US1-6] Define WorkflowState TypedDict per contracts/agents.md in `src/core/state.py`
- [ ] T071 [S] [US1-6] Create state initialization from uploaded documents in `src/core/state.py`
- [ ] T072 [S] [US1-6] Create state update helpers for each agent phase in `src/core/state.py`
- [ ] T073 [S] [US1-6] Write unit tests for state management in `tests/unit/test_state.py`

### 2.2 Agent Configuration (Constitution Principle III)

- [ ] T080 [S] [US1-6] Create JSON schema for agent configuration validation in `src/config/schemas/agent.schema.json`
- [ ] T081 [S] [US1-6] Create agents.yaml with all 7 agent definitions in `src/config/agents.yaml`
- [ ] T082 [S] [US1-6] Create workflows.yaml with transition rules in `src/config/workflows.yaml`
- [ ] T083 [S] [US1-6] Create config loader with schema validation in `src/config/loader.py`
- [ ] T084 [S] [US1-6] Write unit tests for config loading and validation in `tests/unit/test_config.py`

### 2.3 Prompt Management

- [ ] T090 [P] [US1] Create extractor.md prompt with German term glossary in `src/prompts/extractor.md`
- [ ] T091 [P] [US1] Create critic_1.md prompt for extraction validation in `src/prompts/critic_1.md`
- [ ] T092 [P] [US2] Create reconciler.md prompt for deduplication in `src/prompts/reconciler.md`
- [ ] T093 [P] [US2] Create critic_2.md prompt for reconciliation validation in `src/prompts/critic_2.md`
- [ ] T094 [P] [US3] Create classifier.md prompt with CSM criteria in `src/prompts/classifier.md`
- [ ] T095 [P] [US3] Create critic_3.md prompt for classification validation in `src/prompts/critic_3.md`
- [ ] T096 [P] [US3] Create csm_definition.md with official CSM criteria in `src/prompts/csm_definition.md`
- [ ] T097 [P] [US4] Create formatter.md prompt for output generation in `src/prompts/formatter.md`

### 2.4 LangGraph Workflow Engine

- [ ] T100 [S] [US1-6] Create base agent node wrapper with logging and state updates in `src/core/workflow.py`
- [ ] T101 [S] [US1-6] Create critic node wrapper with 3-outcome routing in `src/core/workflow.py`
- [ ] T102 [S] [US1-6] Create conditional edge functions for pass/fail_retry/fail_max in `src/core/workflow.py`
- [ ] T103 [S] [US1-6] Build LangGraph StateGraph with all agents and transitions in `src/core/workflow.py`
- [ ] T104 [S] [US1-6] Add retry counter increment logic in transitions in `src/core/workflow.py`
- [ ] T105 [S] [US1-6] Write integration test for workflow graph compilation in `tests/integration/test_workflow.py`

---

## Phase 3: User Story 1 - Document Extraction (P1)

### 3.1 Extractor Agent

- [ ] T110 [S] [US1] Implement ExtractorInput/ExtractorOutput models per contracts/agents.md in `src/agents/extractor.py`
- [ ] T111 [S] [US1] Implement extractor agent calling LLM with document content in `src/agents/extractor.py`
- [ ] T112 [S] [US1] Parse LLM response into ExtractedPerson list with source references in `src/agents/extractor.py`
- [ ] T113 [S] [US1] Handle retry feedback from critic in subsequent attempts in `src/agents/extractor.py`
- [ ] T114 [S] [US1] Write contract test: verify mandatory fields extracted in `tests/contract/test_extractor.py`
- [ ] T115 [S] [US1] Write contract test: verify source references populated in `tests/contract/test_extractor.py`
- [ ] T116 [S] [US1] Write integration test with German HandelsRegister document in `tests/integration/test_extractor.py`

### 3.2 Critic 1 Agent (Extraction Validator)

- [ ] T120 [S] [US1] Implement Critic1Input/Critic1Output models per contracts/agents.md in `src/agents/critic.py`
- [ ] T121 [S] [US1] Implement critic_1 validation logic (mandatory fields, source refs) in `src/agents/critic.py`
- [ ] T122 [S] [US1] Generate ExtractionIssue list with severity levels in `src/agents/critic.py`
- [ ] T123 [S] [US1] Implement 3-outcome decision logic (pass/fail_retry/fail_max) in `src/agents/critic.py`
- [ ] T124 [S] [US1] Write contract test: pass when all fields present in `tests/contract/test_critic_1.py`
- [ ] T125 [S] [US1] Write contract test: fail_retry on missing fields in `tests/contract/test_critic_1.py`
- [ ] T126 [S] [US1] Write contract test: fail_max after 4 retries in `tests/contract/test_critic_1.py`

### 3.3 Extraction Integration

- [ ] T130 [S] [US1] Wire extractor → critic_1 → extractor retry loop in workflow in `src/core/workflow.py`
- [ ] T131 [S] [US1] Write end-to-end test: successful extraction flow in `tests/integration/test_extraction_flow.py`
- [ ] T132 [S] [US1] Write end-to-end test: extraction retry with critic feedback in `tests/integration/test_extraction_flow.py`
- [ ] T133 [S] [US1] Write end-to-end test: extraction failure after max retries in `tests/integration/test_extraction_flow.py`

---

## Phase 4: User Story 2 - Reconciliation (P2)

### 4.1 Reconciler Agent

- [ ] T140 [S] [US2] Implement ReconcilerInput/ReconcilerOutput models per contracts/agents.md in `src/agents/reconciler.py`
- [ ] T141 [S] [US2] Implement duplicate detection using fuzzy matching service in `src/agents/reconciler.py`
- [ ] T142 [S] [US2] Implement source reference consolidation for merged records in `src/agents/reconciler.py`
- [ ] T143 [S] [US2] Implement conflict detection when same field has different values in `src/agents/reconciler.py`
- [ ] T144 [S] [US2] Generate DuplicateGroup audit trail for merged records in `src/agents/reconciler.py`
- [ ] T145 [S] [US2] Handle retry feedback from critic in subsequent attempts in `src/agents/reconciler.py`
- [ ] T146 [S] [US2] Write contract test: duplicates merged with consolidated sources in `tests/contract/test_reconciler.py`
- [ ] T147 [S] [US2] Write contract test: conflicts flagged with both values in `tests/contract/test_reconciler.py`

### 4.2 Critic 2 Agent (Reconciliation Validator)

- [ ] T150 [S] [US2] Implement Critic2Input/Critic2Output models per contracts/agents.md in `src/agents/critic.py`
- [ ] T151 [S] [US2] Implement critic_2 validation logic (missed duplicates, lost sources) in `src/agents/critic.py`
- [ ] T152 [S] [US2] Generate ReconciliationIssue list with evidence in `src/agents/critic.py`
- [ ] T153 [S] [US2] Implement 3-outcome decision logic in `src/agents/critic.py`
- [ ] T154 [S] [US2] Write contract test: pass when deduplication correct in `tests/contract/test_critic_2.py`
- [ ] T155 [S] [US2] Write contract test: fail_retry on missed duplicates in `tests/contract/test_critic_2.py`

### 4.3 Reconciliation Integration

- [ ] T160 [S] [US2] Wire reconciler → critic_2 → reconciler retry loop in workflow in `src/core/workflow.py`
- [ ] T161 [S] [US2] Write end-to-end test: successful reconciliation flow in `tests/integration/test_reconciliation_flow.py`
- [ ] T162 [S] [US2] Write end-to-end test: reconciliation with German name variants in `tests/integration/test_reconciliation_flow.py`

---

## Phase 5: User Story 3 - Classification (P3)

### 5.1 Classifier Agent

- [ ] T170 [S] [US3] Implement ClassifierInput/ClassifierOutput models per contracts/agents.md in `src/agents/classifier.py`
- [ ] T171 [S] [US3] Implement classifier agent calling LLM with CSM definition in `src/agents/classifier.py`
- [ ] T172 [S] [US3] Parse LLM response into ClassifiedPerson with reasoning in `src/agents/classifier.py`
- [ ] T173 [S] [US3] Validate each person gets exactly one classification in `src/agents/classifier.py`
- [ ] T174 [S] [US3] Handle retry feedback from critic in subsequent attempts in `src/agents/classifier.py`
- [ ] T175 [S] [US3] Write contract test: CSM classification with valid reasoning in `tests/contract/test_classifier.py`
- [ ] T176 [S] [US3] Write contract test: NON_CSM classification with valid reasoning in `tests/contract/test_classifier.py`
- [ ] T177 [S] [US3] Write contract test: German job titles mapped correctly in `tests/contract/test_classifier.py`

### 5.2 Critic 3 Agent (Classification Validator)

- [ ] T180 [S] [US3] Implement Critic3Input/Critic3Output models per contracts/agents.md in `src/agents/critic.py`
- [ ] T181 [S] [US3] Implement critic_3 validation logic (reasoning quality, criteria citation) in `src/agents/critic.py`
- [ ] T182 [S] [US3] Generate ClassificationIssue list with suggested corrections in `src/agents/critic.py`
- [ ] T183 [S] [US3] Implement 3-outcome decision logic in `src/agents/critic.py`
- [ ] T184 [S] [US3] Write contract test: pass when reasoning cites criteria in `tests/contract/test_critic_3.py`
- [ ] T185 [S] [US3] Write contract test: fail_retry on weak reasoning in `tests/contract/test_critic_3.py`

### 5.3 Classification Integration

- [ ] T190 [S] [US3] Wire classifier → critic_3 → classifier retry loop in workflow in `src/core/workflow.py`
- [ ] T191 [S] [US3] Write end-to-end test: successful classification flow in `tests/integration/test_classification_flow.py`
- [ ] T192 [S] [US3] Write end-to-end test: classification with insufficient info in `tests/integration/test_classification_flow.py`

---

## Phase 6: User Story 4 - Output Generation (P4)

### 6.1 Output Formatter Agent

- [ ] T200 [S] [US4] Implement FormatterInput/FormatterOutput models per contracts/agents.md in `src/agents/formatter.py`
- [ ] T201 [S] [US4] Generate DocumentManifestEntry for each uploaded document in `src/agents/formatter.py`
- [ ] T202 [S] [US4] Split classified persons into csm_list and non_csm_list in `src/agents/formatter.py`
- [ ] T203 [S] [US4] Validate mutual exclusivity (no person in both lists) in `src/agents/formatter.py`
- [ ] T204 [S] [US4] Write contract test: output schema matches contracts/api.md in `tests/contract/test_formatter.py`
- [ ] T205 [S] [US4] Write contract test: document manifest complete in `tests/contract/test_formatter.py`

### 6.2 Output Persistence

- [ ] T210 [S] [US4] Save workflow output JSON to filesystem in `src/services/storage.py`
- [ ] T211 [S] [US4] Update WorkflowRun with output_json_path on completion in `src/services/storage.py`
- [ ] T212 [S] [US4] Write unit test for output persistence in `tests/unit/test_output.py`

### 6.3 Full Workflow Integration

- [ ] T220 [S] [US1-4] Wire formatter as final node in workflow graph in `src/core/workflow.py`
- [ ] T221 [S] [US1-4] Write end-to-end test: complete workflow success in `tests/integration/test_full_workflow.py`
- [ ] T222 [S] [US1-4] Write end-to-end test: workflow failure handling in `tests/integration/test_full_workflow.py`

---

## Phase 7: REST API (User Stories 4, 5, 6)

### 7.1 FastAPI Application Setup

- [ ] T230 [S] [US4-6] Create FastAPI application with CORS and error handlers in `src/api/main.py`
- [ ] T231 [S] [US4-6] Configure Uvicorn for development and production in `src/api/main.py`
- [ ] T232 [S] [US4-6] Set up dependency injection for services in `src/api/dependencies.py`

### 7.2 Workflow Endpoints (contracts/api.md)

- [ ] T240 [S] [US4] POST /workflows - Upload documents and create workflow in `src/api/routes/workflows.py`
- [ ] T241 [S] [US4] POST /workflows/{id}/start - Start workflow processing in `src/api/routes/workflows.py`
- [ ] T242 [S] [US4] GET /workflows/{id} - Get workflow status in `src/api/routes/workflows.py`
- [ ] T243 [S] [US4] GET /workflows/{id}/output - Download JSON output in `src/api/routes/workflows.py`
- [ ] T244 [S] [US6] GET /workflows - List workflow history with pagination in `src/api/routes/workflows.py`
- [ ] T245 [S] [US5] GET /workflows/{id}/trace - Get detailed execution trace in `src/api/routes/workflows.py`
- [ ] T246 [S] [US4-6] Implement error response format per contracts/api.md in `src/api/errors.py`
- [ ] T247 [S] [US4-6] Write API integration tests for all endpoints in `tests/integration/test_api.py`

### 7.3 File Upload Handling

- [ ] T250 [S] [US1] Create file upload endpoint with type validation in `src/api/routes/documents.py`
- [ ] T251 [S] [US1] Store uploaded files to UPLOAD_DIR in `src/api/routes/documents.py`
- [ ] T252 [S] [US1] Write test for PDF/TXT upload acceptance in `tests/integration/test_upload.py`
- [ ] T253 [S] [US1] Write test for invalid file type rejection in `tests/integration/test_upload.py`

---

## Phase 8: Real-Time Updates (User Story 5)

### 8.1 WebSocket Server

- [ ] T260 [S] [US5] Create WebSocket endpoint /ws/workflows/{id} in `src/api/websocket.py`
- [ ] T261 [S] [US5] Implement connection management (accept, close, broadcast) in `src/api/websocket.py`
- [ ] T262 [S] [US5] Define WebSocket event types per contracts/api.md in `src/api/websocket.py`

### 8.2 Workflow Event Broadcasting

- [ ] T270 [S] [US5] Create event emitter for agent_started events in `src/core/events.py`
- [ ] T271 [S] [US5] Create event emitter for agent_completed events in `src/core/events.py`
- [ ] T272 [S] [US5] Create event emitter for critic_decision events in `src/core/events.py`
- [ ] T273 [S] [US5] Create event emitter for retry_triggered events in `src/core/events.py`
- [ ] T274 [S] [US5] Create event emitter for workflow_completed/failed events in `src/core/events.py`
- [ ] T275 [S] [US5] Wire event emitters into LangGraph workflow callbacks in `src/core/workflow.py`
- [ ] T276 [S] [US5] Write integration test for WebSocket event flow in `tests/integration/test_websocket.py`

---

## Phase 9: Audit & Compliance (User Stories 1-6)

### 9.1 Audit Logging

- [ ] T280 [S] [US1-6] Create AuditLog service with immutable insert in `src/services/audit.py`
- [ ] T281 [S] [US1-6] Implement SHA-256 checksum for log integrity in `src/services/audit.py`
- [ ] T282 [S] [US1-6] Log agent actions with timestamps, inputs, outputs in `src/services/audit.py`
- [ ] T283 [S] [US1-6] Log all retry cycles with feedback in `src/services/audit.py`
- [ ] T284 [S] [US1-6] Wire audit logging into workflow callbacks in `src/core/workflow.py`
- [ ] T285 [S] [US1-6] Write test verifying audit log immutability in `tests/unit/test_audit.py`

### 9.2 Data Retention

- [ ] T290 [S] [US1-6] Document 7-year retention policy in code comments in `src/services/storage.py`
- [ ] T291 [S] [US1-6] Add retention_until column to relevant tables in `src/services/storage.py`

---

## Phase 10: Polish & Documentation

### 10.1 Error Handling

- [ ] T300 [S] [US1-6] Implement LLM_SERVICE_UNAVAILABLE error for API failures in `src/core/llm/base.py`
- [ ] T301 [S] [US1-6] Implement workflow failure with detailed error messages in `src/core/workflow.py`
- [ ] T302 [S] [US1-6] Add logging throughout application in `src/`

### 10.2 Testing Coverage

- [ ] T310 [P] [US1-6] Ensure 80%+ code coverage in `tests/`
- [ ] T311 [P] [US1] Add edge case: document with no persons in `tests/integration/`
- [ ] T312 [P] [US1] Add edge case: corrupted PDF handling in `tests/integration/`
- [ ] T313 [P] [US3] Add edge case: person without job title in `tests/integration/`

### 10.3 Finalization

- [ ] T320 [S] Update CLAUDE.md with project specifics in `./CLAUDE.md`
- [ ] T321 [S] Review and finalize quickstart.md in `specs/001-kyc-document-processing/quickstart.md`

---

## Dependency Graph (Critical Path)

```
Phase 0 (Setup)
    ↓
Phase 1 (Infrastructure: Models, DB, LLM, PDF)
    ↓
Phase 2 (Agent Framework: State, Config, Prompts, LangGraph)
    ↓
Phase 3 (US1: Extraction) ─────┐
    ↓                          │
Phase 4 (US2: Reconciliation)  │
    ↓                          │
Phase 5 (US3: Classification)  │
    ↓                          │
Phase 6 (US4: Output)          │
    ↓                          │
Phase 7 (REST API) ←───────────┘
    ↓
Phase 8 (Real-Time: WebSocket)
    ↓
Phase 9 (Audit & Compliance)
    ↓
Phase 10 (Polish)
```

---

## Task Statistics

| Phase | Tasks | User Stories |
|-------|-------|--------------|
| Phase 0: Setup | 7 | - |
| Phase 1: Infrastructure | 30 | US1-6 |
| Phase 2: Agent Framework | 25 | US1-6 |
| Phase 3: Extraction | 14 | US1 |
| Phase 4: Reconciliation | 13 | US2 |
| Phase 5: Classification | 13 | US3 |
| Phase 6: Output | 9 | US4 |
| Phase 7: REST API | 15 | US4-6 |
| Phase 8: Real-Time | 10 | US5 |
| Phase 9: Audit | 8 | US1-6 |
| Phase 10: Polish | 8 | US1-6 |
| **Total** | **152** | |
