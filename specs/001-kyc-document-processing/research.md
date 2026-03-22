# Research: KYC Document Processing Agentic Workflow

**Date**: 2025-03-22
**Feature**: 001-kyc-document-processing

## 1. Multi-Agent Orchestration Framework

### Decision: LangGraph

**Rationale**: LangGraph provides native support for:
- Graph-based workflow definition with conditional edges (matches critic 3-outcome routing)
- Built-in state management across agent invocations
- Native LangSmith integration for observability (FR-022/023/024)
- Retry logic with configurable backoff
- Python-native with strong typing support

**Alternatives Considered**:

| Framework | Pros | Cons | Verdict |
|-----------|------|------|---------|
| LangGraph | Native conditional routing, LangSmith observability, mature ecosystem | Tied to LangChain ecosystem | ✅ Selected |
| CrewAI | Simple agent definition, role-based | Less flexible routing, no native graph visualization | ❌ Rejected |
| Google ADK | Google-backed, good observability | Newer, smaller ecosystem, Gemini-focused | ❌ Rejected |
| Custom | Full control | Significant implementation overhead | ❌ Rejected |

---

## 2. Model-Agnostic LLM Abstraction

### Decision: Custom Abstraction Layer with LiteLLM-style Interface

**Rationale**: Constitution Principle IX mandates provider-agnostic implementation. A thin abstraction layer normalizes:
- Chat completion API differences (OpenAI vs Gemini)
- Authentication patterns (API keys, service accounts)
- Response format normalization
- Error handling and retry logic

**Implementation Approach**:
```python
# Abstract interface
class LLMProvider(Protocol):
    async def complete(self, messages: list[Message], **kwargs) -> Response

# Provider selection via environment
LLM_PROVIDER=openai  # or gemini
```

**Alternatives Considered**:

| Approach | Pros | Cons | Verdict |
|----------|------|------|---------|
| Custom thin wrapper | Full control, minimal dependencies | Must maintain | ✅ Selected |
| LiteLLM | 100+ providers, maintained | Heavy dependency, may include unused features | ⚠️ Consider post-MVP |
| LangChain ChatModel | Integrates with LangGraph | Abstracts too much, harder to debug | ❌ Rejected |

---

## 3. PDF Text Extraction

### Decision: pdfplumber (primary) with PyMuPDF fallback

**Rationale**:
- pdfplumber excels at structured document extraction with page/position tracking
- Preserves page boundaries (required for FR-006 source provenance)
- Handles German character encoding (umlauts: ä, ö, ü, ß)
- PyMuPDF as fallback for scanned/image PDFs with OCR

**Alternatives Considered**:

| Library | Pros | Cons | Verdict |
|---------|------|------|---------|
| pdfplumber | Page-aware, table extraction, position data | Text-based PDFs only | ✅ Primary |
| PyMuPDF (fitz) | Fast, handles images, OCR-capable | Less structured extraction | ✅ Fallback |
| PyPDF2 | Simple, lightweight | Poor German character support, no position data | ❌ Rejected |
| Textract (AWS) | Production-grade OCR | External dependency, cost, data residency concerns | ❌ Rejected |

---

## 4. Fuzzy Name Matching

### Decision: rapidfuzz with Jaro-Winkler similarity

**Rationale**:
- FR-012a requires fuzzy matching for duplicates ("Hans Müller" ≈ "Hans Mueller")
- Jaro-Winkler optimized for name comparison (weights prefix similarity)
- rapidfuzz is C-optimized, significantly faster than fuzzywuzzy
- Handles German name variations (umlaut normalization)

**Implementation Approach**:
```python
from rapidfuzz import fuzz
from unidecode import unidecode

def normalize_name(name: str) -> str:
    return unidecode(name.lower().strip())

def is_same_person(name1: str, name2: str, threshold: float = 0.85) -> bool:
    return fuzz.jaro_winkler_similarity(
        normalize_name(name1),
        normalize_name(name2)
    ) >= threshold
```

**Alternatives Considered**:

| Library | Pros | Cons | Verdict |
|---------|------|------|---------|
| rapidfuzz | Fast, multiple algorithms, well-maintained | Extra dependency | ✅ Selected |
| fuzzywuzzy | Simple API, popular | Slow (Python-based), GPL license | ❌ Rejected |
| jellyfish | Multiple phonetic algorithms | Less suited for German names | ❌ Rejected |
| Embedding similarity | Semantic matching | Overkill for name matching, adds complexity | ❌ Rejected |

---

## 5. Workflow State & Audit Storage

### Decision: SQLite with SQLAlchemy ORM

**Rationale**:
- FR-029 requires 7-year retention with full audit trails
- SQLite sufficient for single-user MVP (no connection pooling needed)
- SQLAlchemy provides migration path to PostgreSQL post-MVP
- File-based database simplifies backup and retention compliance

**Schema Approach**:
- `workflow_runs` - Workflow metadata and status
- `agent_executions` - Individual agent invocations with timing
- `audit_logs` - Immutable event log for compliance
- `documents` - Uploaded file metadata (files stored on filesystem)

**Alternatives Considered**:

| Storage | Pros | Cons | Verdict |
|---------|------|------|---------|
| SQLite + SQLAlchemy | Simple, portable, ORM migration path | Single-writer limitation | ✅ Selected for MVP |
| PostgreSQL | Production-ready, concurrent access | Overkill for single-user MVP | ⚠️ Post-MVP |
| MongoDB | Flexible schema | Less suited for audit/compliance | ❌ Rejected |
| File-based JSON | Simplest | No query capability, poor for audit trails | ❌ Rejected |

---

## 6. Real-Time UI Updates

### Decision: WebSocket with FastAPI

**Rationale**:
- FR-024 requires real-time updates without page refresh
- FastAPI has native WebSocket support
- LangGraph callbacks can push state changes to WebSocket
- Sub-2-second latency achievable (SC-005)

**Implementation Approach**:
```python
@app.websocket("/ws/workflow/{workflow_id}")
async def workflow_status(websocket: WebSocket, workflow_id: str):
    await websocket.accept()
    async for event in workflow_events(workflow_id):
        await websocket.send_json(event)
```

**Alternatives Considered**:

| Approach | Pros | Cons | Verdict |
|----------|------|------|---------|
| WebSocket | True real-time, bidirectional | Requires connection management | ✅ Selected |
| Server-Sent Events (SSE) | Simpler, unidirectional | Less browser support, reconnection handling | ❌ Rejected |
| Polling | Simplest | Not real-time, wastes resources | ❌ Rejected |

---

## 7. Agent Configuration Format

### Decision: YAML with JSON Schema Validation

**Rationale**:
- Constitution Principle III mandates declarative agent configuration
- YAML is human-readable and supports multi-line prompts
- JSON Schema enables config validation before runtime
- Matches PRD examples (Section 5)

**Configuration Structure**:
```yaml
agents:
  - name: extractor
    role: Named Entity Extractor
    goal: Extract person data with source provenance
    prompt_file: prompts/extractor.md
    tools: [pdf_reader, text_parser]
    output_key: extracted_persons
    transitions:
      - condition: always
        next: critic_1

  - name: critic_1
    role: Extraction Quality Reviewer
    prompt_file: prompts/critic_1.md
    output_key: critic_1_decision
    transitions:
      - condition: decision == "pass"
        next: reconciler
      - condition: decision == "fail" AND retry_count < 4
        next: extractor
        action: increment_retry
      - condition: decision == "fail" AND retry_count >= 4
        next: FAILED
```

---

## 8. German HandelsRegister Document Handling

### Decision: Custom Extraction Prompts with German Term Mapping

**Rationale**:
- MVP focuses on HandelsRegister documents (FR-003b)
- Common German titles must map to CSM evaluation:
  - Geschäftsführer → Managing Director
  - Vorstand → Board Member
  - Prokurist → Authorized Signatory
  - Gesellschafter → Shareholder

**Implementation Approach**:
- Extraction prompt includes German-English term glossary
- Classifier prompt references official CSM definition with German examples
- Fuzzy matching handles umlaut variations (ü → ue, etc.)

---

## 9. LLM Retry Strategy

### Decision: Exponential Backoff with 3 Retries

**Rationale**:
- Clarification session specified: "Retry with exponential backoff (3 attempts), then fail with clear error"
- Separate from agent-level retries (4 max via critic)
- Handles transient API failures without blocking workflow

**Implementation**:
```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(LLMServiceError)
)
async def call_llm(messages: list[Message]) -> Response:
    ...
```

---

## 10. Output Format

### Decision: JSON with Structured Schema

**Rationale**:
- Clarification session specified: "JSON file download"
- FR-018c mandates downloadable JSON
- Structured schema enables downstream integration

**Output Structure**:
```json
{
  "workflow_id": "uuid",
  "completed_at": "ISO-8601",
  "document_manifest": [
    {"filename": "...", "file_type": "PDF", "page_count": 5, "status": "processed"}
  ],
  "csm_list": [
    {
      "first_name": "...",
      "last_name": "...",
      "classification": "CSM",
      "reasoning": "...",
      "source_references": [{"document": "...", "page": 1}]
    }
  ],
  "non_csm_list": [...]
}
```

---

## Summary of Technology Stack

| Component | Technology | Version |
|-----------|------------|---------|
| Language | Python | 3.11+ |
| Web Framework | FastAPI | Latest |
| Agent Orchestration | LangGraph | Latest |
| LLM Abstraction | Custom (OpenAI/Gemini) | - |
| PDF Extraction | pdfplumber + PyMuPDF | Latest |
| Fuzzy Matching | rapidfuzz | Latest |
| Database | SQLite + SQLAlchemy | Latest |
| Real-time | WebSocket (FastAPI native) | - |
| Config Format | YAML + JSON Schema | - |
| Testing | pytest + pytest-asyncio | Latest |
