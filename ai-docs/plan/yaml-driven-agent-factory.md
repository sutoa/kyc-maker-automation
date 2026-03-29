# Implementation Plan: YAML-Driven Agent Factory

**Status:** Complete (steps 8, 9, 13 intentionally skipped — see notes)
**Date:** 2026-03-28
**Branch:** 001-kyc-document-processing

---

## Progress Tracker

| Step | File(s) | Status |
|------|---------|--------|
| 1 | `src/config/agents.yaml` | `[x] done` |
| 2 | `src/config/workflows.yaml` | `[x] done` |
| 3 | `src/core/llm/base.py`, `openai.py`, `gemini.py` | `[x] done` |
| 4 | `src/core/conditions.py` | `[x] done` |
| 5 | `src/core/agent_factory.py` | `[x] done` |
| 6 | `src/config/loader.py` | `[x] done` |
| 7 | `src/core/workflow.py` | `[x] done` |
| 8 | `src/core/state.py` | `[-] skipped — MAX_RETRY_COUNT left; still used by legacy critic.py inner validation fns; user approved` |
| 9 | `src/services/matching.py` | `[-] skipped — DEFAULT_THRESHOLD left as default param; user approved` |
| 10 | `src/agents/extractor.py`, `critic.py`, `reconciler.py`, `classifier.py`, `formatter.py` | `[x] done — factory-compatible rule_fn wrappers added; render_prompt updated to {{key}} syntax; PROMPT_PATH left (still used by legacy render_prompt, user approved)` |
| 11 | `src/prompts/extractor.md`, `reconciler.md`, `classifier.md` | `[x] done` |
| 12 | `src/api/main.py` | `[x] done` |
| 13 | `src/api/routes/workflows.py` | `[-] skipped — hardcoded agent name strings left; user approved` |
| 14 | `tests/unit/test_config.py` | `[x] done` |
| 15 | `tests/integration/test_workflow.py` + other integration tests | `[x] done` |
| 16 | `pytest` (full suite) | `[x] done — 487 passed, 4 skipped, 0 failed` |

### Resume instructions
1. Open this file and find the first row with `[ ] pending`
2. Read the detail section for that file below
3. Read the current state of the file before editing
4. Continue from there — do not re-do completed steps

---

## What Went Wrong (Root Cause)

The previous implementation (phases 1–10) built the agent and workflow system correctly in
structure but **ignored both YAML config files at runtime**:

- `agents.yaml` was loaded and validated but never used to configure agents
- All agents read config values from hardcoded constants instead: `PROMPT_PATH`, `MAX_RETRY_COUNT`,
  model defaults in `LLMProvider`, phase names, state key strings
- `build_workflow_graph()` required pre-built function dicts instead of building them from YAML
- `conditions.py` had three near-identical routing functions instead of one generic one
- `on_traverse.increment_key` was declared in YAML but never implemented
- `runtime.*` and `observability.*` YAML blocks were completely ignored

This plan corrects all of it. After this plan, **every configurable value in the system comes
from a YAML file**. No hardcoding.

---

## Architecture After This Plan

```
workflows.yaml ──► build_workflow_graph()
     │                    │
     │ agents_ref         │ reads nodes/edges
     ▼                    ▼
agents.yaml ──► build_agent_functions()
                    │
                    ├── for each node with execution: llm
                    │       build_agent_fn(agent_cfg)
                    │           - loads system_prompt.file or inline
                    │           - prepends role/goal/backstory
                    │           - calls LLM with model/temperature/max_tokens
                    │           - parses output_schema.ref (+ is_list flag)
                    │           - writes to output_key in state
                    │           - increments retry_count_key on retry
                    │
                    └── for each node with execution: rule
                            build_agent_fn(agent_cfg)
                                - calls resolve_callable(rule_fn)(state)
                                - writes CriticFeedback to output_key in state
                                - increments retry_count_key on retry
```

---

## Key Design Decisions

### 1. No `type: critic` needed
Critics are just agents whose `output_schema.ref` is `CriticFeedback`. The routing is
edge-driven via `condition.fn`. No separate critic wrapper.

### 2. Single generic routing function
`src.core.conditions.route_on_critic_decision` handles all critic edges.
Reads `state["last_critic_feedback"].decision` → returns `"pass"` / `"fail_retry"` / `"fail_max"`.
All three critic edges in `workflows.yaml` point to this one function.

### 3. `on_traverse.increment_key` implemented in node wrapper
LangGraph edges cannot mutate state. The increment is done at the **start** of the retrying
agent's node wrapper: if `last_critic_feedback.decision == FAIL_RETRY`, increment
`state[retry_count_key]` before calling the agent. `retry_count_key` is declared per-agent in
`agents.yaml`.

### 4. `execution: llm | rule`
Declared per-agent in `agents.yaml`. `rule` agents point to a Python function via `rule_fn`
(dotted path). LLM agents use `system_prompt` + the configured LLM provider.

### 5. LLM provider bootstrapped from model string
`model: openai/gpt-4o-mini` is parsed as `provider=openai`, `model=gpt-4o-mini`.
`get_llm_provider(model_string, temperature, max_tokens, retry_cfg)` replaces the current
no-args factory.

---

## File-by-File Detail

### 1. `src/config/agents.yaml` *(add fields)*

Add to all agents:
```yaml
extractor:
  execution: llm
  retry_count_key: extraction_retry_count   # incremented by node wrapper on retry
  ...

reconciler:
  execution: llm
  retry_count_key: reconciliation_retry_count
  matching_threshold: 0.85                  # used by reconciler rule logic
  ...

classifier:
  execution: llm
  retry_count_key: classification_retry_count
  ...

critic_1:
  execution: llm                            # uses LLM for validation
  output_schema:
    ref: src.models.workflow.CriticFeedback
    is_list: false
  ...

critic_2:
  execution: rule
  rule_fn: src.agents.critic.validate_reconciliation
  output_schema:
    ref: src.models.workflow.CriticFeedback
    is_list: false
  # system_prompt not needed for rule-based agents

critic_3:
  execution: rule
  rule_fn: src.agents.critic.validate_classification
  output_schema:
    ref: src.models.workflow.CriticFeedback
    is_list: false
```

Add `is_list: true` where output is a list:
```yaml
extractor:
  output_schema:
    ref: src.models.person.ExtractedPerson
    is_list: true

reconciler:
  output_schema:
    ref: src.models.person.ReconciledPerson
    is_list: true

classifier:
  output_schema:
    ref: src.models.person.ClassifiedPerson
    is_list: true

formatter:
  output_schema:
    ref: src.models.output.WorkflowOutput
    is_list: false
```

---

### 2. `src/config/workflows.yaml` *(simplify)*

- Remove `defaults:` block entirely (single source of truth is `agents.yaml`)
- Update all three critic edges to use the single generic routing function:
  ```yaml
  - from: critic_1
    condition:
      fn: src.core.conditions.route_on_critic_decision
      ...
  - from: critic_2
    condition:
      fn: src.core.conditions.route_on_critic_decision
      ...
  - from: critic_3
    condition:
      fn: src.core.conditions.route_on_critic_decision
      ...
  ```

---

### 3. `src/core/llm/base.py`, `openai.py`, `gemini.py` *(remove hardcoded defaults)*

`get_llm_provider()` new signature:
```python
def get_llm_provider(
    model_string: str,          # "openai/gpt-4o-mini" or "gemini/gemini-1.5-pro"
    temperature: float,
    max_tokens: int,
    retry_cfg: dict,            # {max_attempts, backoff, delay_seconds}
) -> LLMProvider
```

- Parse `model_string` → `provider, model_name`
- Pass `temperature`, `max_tokens` through to `llm.complete()`
- Configure tenacity retry from `retry_cfg.backoff` + `retry_cfg.delay_seconds`
- Remove all hardcoded defaults (`temperature=0.7`, `model="gpt-4o"`)

---

### 4. `src/core/conditions.py` *(replace 3 functions with 1)*

Delete `route_critic_1`, `route_critic_2`, `route_critic_3`.

Add single generic function:
```python
def route_on_critic_decision(state: WorkflowState) -> str:
    feedback = state.get("last_critic_feedback")
    if feedback is None:
        return "pass"
    decision = getattr(feedback, "decision", None)
    return {
        CriticDecision.PASS:       "pass",
        CriticDecision.FAIL_RETRY: "fail_retry",
        CriticDecision.FAIL_MAX:   "fail_max",
    }.get(decision, "fail_max")
```

---

### 5. `src/core/agent_factory.py` *(new file)*

Two public functions:

**`build_agent_fn(agent_name, agent_cfg, agents_dir) -> Callable[[WorkflowState], WorkflowState]`**

For `execution: llm`:
1. Load prompt: resolve `system_prompt.file` relative to `agents_dir`, or use `system_prompt.inline`
2. Build system message: prepend role/goal/backstory preamble to prompt content
3. Resolve output schema: `resolve_callable(output_schema.ref)` → Pydantic class; note `is_list`
4. Get effective config: `model`, `temperature`, `max_tokens`, `retry`
5. Return a closure that at call time:
   - Extracts `input_keys` from state → builds context dict
   - Renders prompt template with context values (replaces `{{key}}` placeholders)
   - Instantiates LLM via `get_llm_provider(model, temperature, max_tokens, retry)`
   - Calls `llm.complete([system_msg, user_msg])`
   - Parses response as `list[Schema]` or `Schema` depending on `is_list`
   - Checks `retry_count_key`: if present and `last_critic_feedback.decision == FAIL_RETRY`,
     increments `state[retry_count_key]`
   - Also checks retry vs `retry.max_attempts`: if count >= max, sets decision to FAIL_MAX
     (for critic agents whose `output_schema.ref` is `CriticFeedback`)
   - Writes result to `state[output_key]`
   - Returns updated `WorkflowState`

For `execution: rule`:
1. Resolve `rule_fn` via `resolve_callable()`
2. Return a closure that at call time:
   - Calls `rule_fn(state)` → returns `CriticFeedback`
   - Checks retry count vs `retry.max_attempts`, overrides decision to FAIL_MAX if exceeded
   - Increments `retry_count_key` if FAIL_RETRY
   - Writes result to `state[output_key]`
   - Returns updated `WorkflowState`

---

### 6. `src/config/loader.py` *(add `build_agent_functions()`)*

**`build_agent_functions(agents_cfg, workflows_cfg) -> dict[str, Callable]`**
- Iterates `workflows_cfg["nodes"]`
- For each node, looks up agent key in `agents_cfg["agents"]`
- Calls `get_effective_agent_config(agent_name, agents_cfg)` to merge defaults
- Calls `build_agent_fn(agent_name, effective_cfg, agents_dir)`
- Returns single `{node_name: wrapped_fn}` dict (no more split agent/critic dicts)

**`resolve_agents_ref(workflows_cfg) -> Path`**
- Reads `workflows_cfg["agents_ref"]`
- Resolves path relative to `workflows.yaml` location
- Returns absolute Path — used by loader and factory

Update `load_workflows_config()` to follow `agents_ref` when loading agents.

---

### 7. `src/core/workflow.py` *(major simplification)*

**`build_workflow_graph(functions, workflows_config=None)`**
- Now accepts ONE `functions` dict (no more `agent_functions` + `critic_functions` split)
- Wires `runtime.checkpointer` → creates `SqliteSaver` / `MemorySaver` and passes to `compile()`
- Wires `runtime.interrupt_before` / `interrupt_after` → `compile(interrupt_before=[...])`
- Wires `workflow.max_steps` → passed as `{"recursion_limit": max_steps}` at invoke time

**`compile_workflow(workflows_config=None, agents_config=None)`**
- Takes no external function dicts
- Loads both configs if not provided
- Calls `build_agent_functions(agents_cfg, workflows_cfg)` to build functions
- Calls `build_workflow_graph(functions, workflows_cfg)`
- Wires checkpointer from `runtime` config
- Returns compiled graph

**`run_workflow_sync` / `run_workflow`**
- Passes `{"recursion_limit": max_steps, "tags": observability.tags}` as config to invoke

**Delete:**
- `create_critic_node()` — merged into `build_agent_fn()` in factory
- `_phase_for_critic()` — no longer needed

**Keep:**
- `create_agent_node()` — still used for non-factory wrapping (logging, audit, events)
  BUT simplify: remove phase-specific state update calls (now handled by factory via output_key)

**Wire observability at startup:**
```python
if observability_cfg.get("provider") == "langsmith":
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = observability_cfg["project"]
```

---

### 8. `src/core/state.py` *(remove hardcoded constant)*

Remove `MAX_RETRY_COUNT = 4`.

Any code that referenced this constant now reads from the agent's effective config at runtime.
The factory handles this — no callers outside the factory need the constant.

---

### 9. `src/services/matching.py` *(remove hardcoded threshold)*

Remove `DEFAULT_THRESHOLD = 0.85`.

`ReconcilerAgent` factory passes `matching_threshold` from `agents.yaml` to the matching
service. The reconciler's `rule_fn` or LLM agent closure receives it from its config closure.

---

### 10. `src/agents/*.py` *(remove hardcoded constants, keep core logic)*

For each agent file:
- Remove `PROMPT_PATH` / `PROMPTS_DIR` constants
- Remove direct `get_llm_provider()` calls inside agent functions (factory handles this)
- Keep the **pure logic functions** that don't depend on config:
  - `parse_llm_response()` in `extractor.py`
  - `validate_extraction()`, `validate_reconciliation()`, `validate_classification()` in `critic.py`
  - `reconcile_persons()` in `reconciler.py`
  - `classify_persons()` in `classifier.py`
- The top-level `*_agent()` functions become wrappers that delegate to the factory-built
  closures, or are removed entirely if the factory fully replaces them

**Rule-based critic functions** (`validate_reconciliation`, `validate_classification`) must
match the `rule_fn` contract: `(state: WorkflowState) -> CriticFeedback`.
Currently they return `Critic2Output` / `Critic3Output` — update return types.

---

### 11. `src/prompts/extractor.md`, `reconciler.md`, `classifier.md`

Add feedback placeholders for retry context:
- `extractor.md`: add `{{extraction_feedback}}` section (shown only when value present)
- `reconciler.md`: add `{{reconciliation_feedback}}` section
- `classifier.md`: add `{{classification_feedback}}` section

The factory's prompt renderer replaces `{{key}}` with `state[key]` for all `input_keys`.
Absent / null values render as empty string so the placeholder disappears cleanly.

---

### 12. `src/api/main.py` *(startup bootstrap)*

Add lifespan handler:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.compiled_workflow = compile_workflow()   # reads both YAMLs, builds all agents
    yield
```

Remove any inline `get_llm_provider()` calls in API layer.

---

### 13. `src/api/routes/workflows.py` *(remove hardcoded agent names)*

Replace hardcoded agent name strings with dynamic lookup from loaded agents config:
```python
agents_cfg = load_agents_config()
agent_names = list(agents_cfg["agents"].keys())
```

---

### 14. `tests/unit/test_config.py` *(add factory tests)*

New test classes:
- `TestBuildAgentFn` — LLM agent closure: prompt loaded, model/temperature/max_tokens passed, output written to correct key
- `TestBuildAgentFnRule` — rule agent closure: rule_fn called, CriticFeedback written to output_key
- `TestBuildAgentFunctions` — full dict built from YAML nodes
- `TestRetryCountIncrement` — node wrapper increments retry_count_key on FAIL_RETRY
- `TestMaxAttemptsEnforcement` — decision overridden to FAIL_MAX when count >= max_attempts

---

### 15. `tests/integration/test_workflow.py` + other integration tests

- `compile_workflow()` now takes no args → remove all `agent_functions` / `critic_functions`
  dict construction from test setup
- Mock at the **LLM layer** (`get_llm_provider`) instead of passing mock agent functions
- `test_build_graph_missing_agent_raises` → trigger by removing agent from agents.yaml fixture
  rather than passing incomplete function dict

---

## Testing Checklist

- [x] `pytest tests/unit/test_config.py` — all factory + config tests
- [x] `pytest tests/integration/test_workflow.py` — YAML-driven build, no function dicts
- [x] `pytest tests/contract/` — agent contract tests, no regressions
- [x] `pytest tests/unit/test_state.py` — state management, no regressions
- [x] `pytest` (full suite) — 487 passed, 4 skipped, 0 failed (2026-03-29)
