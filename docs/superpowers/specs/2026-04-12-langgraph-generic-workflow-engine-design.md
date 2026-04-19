# Design: Generic YAML-Driven LangGraph Workflow Engine

**Date:** 2026-04-12
**Branch:** 001-kyc-document-processing
**Status:** Approved for implementation

---

## Problem Statement

The codebase has a solid YAML-driven foundation but contains several critical gaps that prevent it from running end-to-end:

1. `ExtractorCriticFeedback` Pydantic class referenced in `agents.yaml` does not exist
2. `route_on_extractor_critic_decision` function referenced in `workflows.yaml` does not exist
3. `ExtractedPerson` schema is incompatible with the JSON example in `extractor.md`
4. `formatter` agent has no `output_schema` — factory crashes at startup
5. Custom LLM abstraction (`src/core/llm/`) uses manual JSON parsing instead of `with_structured_output()`
6. Legacy `graph.set_entry_point()` API used instead of modern `START` sentinel
7. Routing uses `add_conditional_edges` even where state mutation is required (retry count increment)
8. `state.py` contains ~200 lines of dead phase-specific helper code
9. `run_workflow` and `run_workflow_sync` duplicate ~150 lines of audit/event logic
10. `create_agent_node` wrapper hardcodes retry key names and output summary mappings

---

## Decisions

| Question | Decision |
|---|---|
| `WorkflowState` static vs dynamic | Static TypedDict — keep type safety |
| `ExtractedPerson` flatten vs enrich prompt | Flatten model to match prompt (Option A) |
| `extraction_id` | Drop entirely |
| `formatter` output schema | No schema — factory returns raw string (Option B) |
| LLM layer | Replace custom abstraction with LangChain `.with_structured_output()` |
| Retry counter increment | In routing node via `Command`, not in edge function |
| Sync vs async | Single async `run_workflow` only |

---

## Architecture

### Data Flow

```
documents
  └─► extractor ──────────────────────────────────────────────────────────────────────────►┐
        │ extracted_persons                                                                  │ (on retry)
        ▼                                                                                    │
  extractor_critic                                                                           │
        │ extractor_critic_feedback                                                          │
        ▼                                                                                    │
  extractor_critic_router ──── pass ──────────────────────────────────────────► formatter   │
        │                                                                           │        │
        └─── fail_retry (+ increment extraction_retry_count) ──────────────────────┼────────┘
        └─── fail_max ──────────────────────────────────────────────────────────► END
                                                                            csm_report
```

### Component Map

```
src/
├── config/
│   ├── agents.yaml          # agent definitions (model, prompts, schemas, retry)
│   ├── workflows.yaml       # graph topology (nodes, edges, router nodes, runtime)
│   └── loader.py            # YAML load + validate + build_agent_functions()
├── core/
│   ├── agent_factory.py     # builds agent callables from YAML config
│   │                          LLM agents: ChatModel + with_structured_output()
│   │                          Rule agents: resolve_callable(rule_fn)
│   ├── conditions.py        # router node functions returning Command
│   ├── state.py             # WorkflowState TypedDict + minimal helpers
│   └── workflow.py          # build_workflow_graph() + compile_workflow() + run_workflow()
├── models/
│   ├── person.py            # ExtractedPerson (flat), ReconciledPerson, ClassifiedPerson
│   └── workflow.py          # ExtractorCriticFeedback, CriticFeedback, WorkflowRun
```

---

## Section 1: Data Models

### `src/models/person.py` — `ExtractedPerson`

Flattened to match `extractor.md` JSON example exactly. LLM output maps directly to Pydantic fields with no post-processing.

```python
class ExtractedPerson(BaseModel):
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    job_title: str | None = None
    job_title_original: str | None = None
    doc_name: str = Field(..., description="Source document filename")
    page_number: int = Field(..., ge=1, description="Page where person was found")
```

`extraction_id` is dropped entirely. Downstream models (`ReconciledPerson`, `ClassifiedPerson`) are unchanged — they will be revisited when those agents are re-enabled.

### `src/models/workflow.py` — new classes

```python
class ExtractionIssueSimple(BaseModel):
    first_name: str
    last_name: str
    issue_description: str
    severity: Literal["error", "warning"]

class ExtractorCriticFeedback(BaseModel):
    status: Literal["pass", "fail"]
    issues: list[ExtractionIssueSimple]
    feedback: str
```

These match the `extractor_critic.md` JSON example exactly.

### `src/core/state.py` — `WorkflowState` additions

Two keys added:
- `extractor_critic_feedback: ExtractorCriticFeedback | None`
- `csm_report: str | None`

All phase-specific update helpers (`update_extraction_result`, `update_extraction_retry`, etc.) and `MAX_RETRY_COUNT` are deleted. They were never called by the factory pattern. Retained: `create_initial_state`, `update_workflow_started`, `update_workflow_failed`.

---

## Section 2: YAML Config

### `agents.yaml` changes

**`extractor.input_keys`** — add `extractor_critic_feedback`:
```yaml
extractor:
  input_keys: [documents, extractor_critic_feedback]
```
`_render_prompt` already handles `None` → empty string, so the first iteration renders cleanly.

**`formatter.output_schema`** — remove entirely. Absence of `output_schema` signals raw string output to the factory.

### `workflows.yaml` changes

**New router node:**
```yaml
nodes:
  extractor_critic_router:
    type: router
    fn: src.core.conditions.route_on_extractor_critic_decision
    routes:
      pass:       formatter
      fail_retry: extractor
      fail_max:   end
```

**Updated edges** — replace the conditional edge from `extractor_critic` with two unconditional edges:
```yaml
edges:
  - from: extractor_critic
    to: extractor_critic_router       # unconditional

  - from: extractor_critic_router     # router node handles routing via Command
    # no condition block — Command returned from node function handles routing
```

The old `condition:` block on the `extractor_critic` edge is removed.

---

## Section 3: Conditions Layer

`route_on_extractor_critic_decision` returns a `Command` — it both routes AND updates state in one step. No `add_conditional_edges` needed.

```python
from langgraph.types import Command
from langgraph.graph import END
from typing import Literal

def route_on_extractor_critic_decision(
    state: WorkflowState,
) -> Command[Literal["formatter", "extractor", END]]:
    feedback = state.get("extractor_critic_feedback")
    retry_count = state.get("extraction_retry_count", 0) or 0

    if feedback is None or getattr(feedback, "status", "pass") == "pass":
        return Command(goto="formatter")

    if retry_count >= 4:
        return Command(goto=END)

    return Command(
        goto="extractor",
        update={"extraction_retry_count": retry_count + 1},
    )
```

The routes dict from YAML is used by the graph builder to declare node destinations at compile time — the function itself hardcodes node names as Literal type args (required by LangGraph for graph validation).

---

## Section 4: Agent Factory

### Replace custom LLM layer with LangChain ChatModels

`src/core/llm/` is deleted. The factory uses `ChatOpenAI` / `ChatGoogleGenerativeAI` directly.

**Provider routing** from `model` field in `agents.yaml` (`openai/gpt-4o-mini` → provider prefix):

```python
def _build_chat_model(model_string: str, temperature: float, max_tokens: int):
    provider, model_name = model_string.split("/", 1)
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model_name, temperature=temperature, max_tokens=max_tokens)
    elif provider in ("gemini", "google"):
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model_name, temperature=temperature, max_tokens=max_tokens)
    raise ValueError(f"Unsupported provider: '{provider}'")
```

### Structured output — with `output_schema`

```python
if is_list:
    class _ListWrapper(BaseModel):
        items: list[schema_cls]
    structured_llm = llm.with_structured_output(_ListWrapper, method="json_schema")
    raw = structured_llm.invoke([SystemMessage(content=system_content)])
    result = raw.items
else:
    structured_llm = llm.with_structured_output(schema_cls, method="json_schema")
    result = structured_llm.invoke([SystemMessage(content=system_content)])
```

The LLM is constrained at the API level. `_parse_llm_response` is deleted.

### Raw string output — without `output_schema`

```python
result = llm.invoke([SystemMessage(content=system_content)]).content
```

The raw markdown string is stored directly in `output_key` (`csm_report`).

---

## Section 5: Workflow Engine

### `build_workflow_graph` changes

**Entry point** — modern `START` sentinel:
```python
from langgraph.graph import START, END
graph.add_edge(START, first_node)   # replaces graph.set_entry_point()
```

**Router node handling** — the builder detects `type: router` nodes and adds them as regular nodes. Their `Command` return handles routing — no `add_conditional_edges` needed:
```python
if node_def.get("type") == "router":
    routing_fn = resolve_callable(node_def["fn"])
    graph.add_node(node_name, routing_fn)
    continue  # no edge registration needed — Command handles it
```

**`create_agent_node` generalization** — `retry_count_key` and `output_key` passed in from agent config:
```python
def create_agent_node(agent_name, agent_fn, retry_count_key=None, output_key=None):
    def wrapped(state):
        retry_count = state.get(retry_count_key, 0) if retry_count_key else 0
        ...
```

### Async only

`run_workflow_sync` is deleted. All callers use `await run_workflow(...)` or `asyncio.run(run_workflow(...))`.

---

## Section 6: Dependencies

`requirements.txt` additions:
```
langchain-openai
langchain-google-genai
langgraph-checkpoint-sqlite
```

`src/core/llm/` directory deleted.

---

## Files Changed

| File | Change |
|---|---|
| `src/models/person.py` | Flatten `ExtractedPerson`, drop `extraction_id` |
| `src/models/workflow.py` | Add `ExtractorCriticFeedback`, `ExtractionIssueSimple` |
| `src/core/state.py` | Delete dead helpers; add `extractor_critic_feedback`, `csm_report` |
| `src/core/conditions.py` | Add `route_on_extractor_critic_decision` returning `Command` |
| `src/core/agent_factory.py` | Replace custom LLM layer; `.with_structured_output()`; optional schema |
| `src/core/workflow.py` | `START` sentinel; router node support; drop sync duplicate; generalize wrapper |
| `src/config/loader.py` | Handle `type: router` nodes in `build_agent_functions` |
| `src/config/agents.yaml` | `extractor.input_keys` + remove `formatter.output_schema` |
| `src/config/workflows.yaml` | Add `extractor_critic_router` node; replace condition edge with unconditional edges |
| `src/core/llm/` | Delete entirely |
| `requirements.txt` | Add `langchain-openai`, `langchain-google-genai`, `langgraph-checkpoint-sqlite` |
