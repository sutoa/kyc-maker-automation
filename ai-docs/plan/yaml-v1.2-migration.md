# Implementation Plan: YAML v1.0 → v1.2 Migration

**Status:** Complete ✓
**Date:** 2026-03-28
**Branch:** 001-kyc-document-processing

---

## Progress Tracker

Update this section after each step is completed. If context is lost mid-session,
resume from the first item marked `[ ]`.

| Step | File | Status |
|------|------|--------|
| 1 | `src/config/schemas/agent.schema.json` | `[x] done` |
| 2 | `src/config/schemas/workflow.schema.json` | `[x] done` |
| 3 | `src/core/conditions.py` | `[x] done` |
| 4 | `src/config/loader.py` | `[x] done` |
| 5 | `src/core/workflow.py` | `[x] done` |
| 6 | `tests/unit/test_config.py` | `[x] done` |
| 7 | `tests/integration/test_workflow.py` | `[x] done` |
| 8 | Run full test suite (`pytest`) | `[x] done` |

### Resume instructions
1. Open this file and find the first row with `[ ] pending`
2. Read the detail section for that file below
3. Read the current state of the file before editing
4. Continue from there — do not re-do completed steps

---

## Background

`src/config/workflows.yaml` and `src/config/agents.yaml` were migrated from a custom v1.0
structure to the AGENTFLOW v1.2 specification. The backend orchestration code still reads the
old field names and must be updated to match the new structure.

---

## Scope Summary

The v1.2 YAML change breaks **6 areas** of code, all of which reference old field names
(`transitions`, `validates_phase`, `on_complete`, `on_pass`, `name`, `type`, `prompt_file`, etc.).
The graph construction in `workflow.py` is currently **hardcoded** rather than YAML-driven —
this migration is the opportunity to fix that properly.

---

## Key Structural Differences: v1.0 vs v1.2

### agents.yaml

| v1.0 field | v1.2 field |
|---|---|
| `name` | *(removed — key name is the identifier)* |
| `type` (enum) | *(removed)* |
| `description` | `backstory` |
| `prompt_file: extractor.md` | `system_prompt.file: ../prompts/extractor.md` |
| `output_schema: ExtractorOutput` (string) | `output_schema.ref: src.models.person.ExtractedPerson` |
| `llm.model`, `llm.temperature`, `llm.max_tokens` | flat `model`, `temperature`, `max_tokens` |
| `retry.max_retries`, `retry.backoff_seconds` | `retry.max_attempts`, `retry.backoff`, `retry.delay_seconds` |
| `validates_phase`, `validation_rules` | *(removed — live in prompt .md files)* |
| `matching_threshold`, `csm_definition_file` | *(removed)* |
| *(absent)* | `role`, `goal`, `input_keys`, `output_key`, `defaults` block |

### workflows.yaml

| v1.0 field | v1.2 field |
|---|---|
| `workflows.kyc_document_processing.*` (named map) | `workflow.*` (top-level, single workflow) |
| `initial_state: extractor` | `workflow.entry_point: __start__` |
| `terminal_states: [COMPLETED, FAILED]` | `end` node in `nodes:` |
| `transitions.extractor.on_complete: critic_1` | unconditional edge `{from: extractor, to: critic_1}` |
| `transitions.critic_1.on_pass / on_fail_retry / on_fail_max` | conditional edge with `condition.fn` + `condition.routes` |
| `states:` block | *(removed)* |
| `events:` block | *(removed)* |
| *(absent)* | `agents_ref`, `defaults`, `state`, `nodes`, `edges`, `observability`, `runtime`, `vars` |

---

## Files to Change

### Execution Order

```
1. src/config/schemas/agent.schema.json      — replace with v1.2 schema
2. src/config/schemas/workflow.schema.json   — new file, validates workflow structure
3. src/core/conditions.py                    — new file, routing functions for critics
4. src/config/loader.py                      — rewrite parsing + validation logic
5. src/core/workflow.py                      — update graph construction to be YAML-driven
6. tests/unit/test_config.py                 — rewrite all tests for v1.2 structure
7. tests/integration/test_workflow.py        — update for new graph construction
```

---

## File-by-File Detail

### 1. `src/config/schemas/agent.schema.json` *(replace)*

Replace entirely. New schema validates:
- Top-level `defaults` block (model, temperature, max_tokens, retry)
- Per-agent fields: `role`, `goal`, `backstory` (strings)
- `input_keys` (array of strings), `output_key` (string)
- `system_prompt` object — exactly one of `file` or `inline` required
- `output_schema` object — exactly one of `ref` or `example` required
- Flat `model`, `temperature`, `max_tokens` (override defaults)
- `retry` with `max_attempts` (int), `backoff` (enum: linear|exponential|fixed), `delay_seconds`

Removed from schema: `name`, `type`, `description`, `prompt_file`, `llm` nested block,
`validates_phase`, `validation_rules`, `matching_threshold`, `csm_definition_file`, `output_format`,
`retry.max_retries`, `retry.backoff_seconds`.

---

### 2. `src/config/schemas/workflow.schema.json` *(new file)*

New schema validates:
- `workflow` block: `id`, `name`, `description`, `entry_point`, `max_steps`, `timeout_seconds`
- `agents_ref` (string path)
- `defaults` block
- `state` map (field definitions with `type` and optional `default`)
- `nodes` map — each node has `type` (agent|parallel|merger|human|subgraph|end) and optional `agent` key
- `edges` array — unconditional (`from`/`to`) and conditional (`from`/`condition.fn`/`condition.routes`)
- `observability`, `runtime`, `vars` blocks

---

### 3. `src/core/conditions.py` *(new file)*

The YAML edges reference Python callables:
```yaml
condition:
  fn: src.core.conditions.route_critic_1
```

This file does not yet exist. Three routing functions, all reading `last_critic_feedback.decision`:

```python
route_critic_1(state: WorkflowState) -> str   # "pass" | "fail_retry" | "fail_max"
route_critic_2(state: WorkflowState) -> str
route_critic_3(state: WorkflowState) -> str
```

These replace the fragile `should_continue_after_critic()` logic in `workflow.py` that currently
infers the decision by checking `state.current_agent` (a workaround, not a proper read of the
critic output).

---

### 4. `src/config/loader.py` *(rewrite 4 functions, replace 1, add 1)*

**`validate_agents_config()`** (lines 122–172)
- Remove checks for `type`, `validates_phase`, `name`, `prompt_file`
- Add checks for: `role`, `goal`, `backstory`, `input_keys`, `output_key`
- Add check: `system_prompt` must have exactly one of `file` or `inline`
- Add check: `output_schema` must have exactly one of `ref` or `example`
- Remove the critic `validates_phase` check entirely

**`validate_workflows_config()`** (lines 175–232)
- Remove all traversal of `workflows.kyc_document_processing.transitions`
- Add: check `workflow.entry_point` resolves to a node in `nodes`
- Add: check every `nodes[n].agent` key exists in agents config
- Add: check every edge `to` / `condition.routes` value resolves to a valid node name

**`get_workflow_config()`** (lines 353–376)
- Currently reads `config.get("workflows", {})["kyc_document_processing"]`
- Rewrite: return `config.get("workflow", {})` directly (single workflow per file, no named map)

**`load_workflows_config()`** (lines 270–302)
- Fix log line that counts `config.get("workflows", {})` — update to new structure

**`get_transition()`** (lines 379–411) → **replace** with `get_edge_routes(from_node, workflow_config)`
- Old: reads `transitions.critic_1.on_pass` → `"reconciler"`
- New: scans `edges` list for `{from: critic_1}`, returns `condition.routes` dict
- Old callers in `workflow.py` updated to use `get_edge_routes()`

**New: `get_effective_agent_config(agent_name, agents_config)`**
- Merges agent-level `defaults` → per-agent overrides, returns resolved config dict

---

### 5. `src/core/workflow.py` *(update 2 functions)*

**`build_workflow_graph()`** (lines 602–722) — currently fully hardcoded.

Update to be YAML-driven:
- Load `nodes:` from `workflows.yaml` → determine which agent nodes to add dynamically
  (instead of hardcoded `graph.add_node("extractor", ...)` calls)
- Load `edges:` → for unconditional edges call `graph.add_edge(from, to)`;
  for conditional edges dynamically import `edge.condition.fn` callable and call
  `graph.add_conditional_edges(from, fn, routes_map)`
- Entry point from `workflow.entry_point` (currently hardcoded as `"extractor"`)
- Result: graph topology changes require only YAML edits, not Python changes

**`should_continue_after_critic()`** (lines 544–585) — **delete**
- Replaced by `conditions.py` routing functions wired via YAML-driven conditional edges
- Current implementation infers routing from `state.current_agent` (fragile workaround)
- New implementation reads `last_critic_feedback.decision` directly (correct)

`create_agent_node()` and `create_critic_node()` wrappers — **unchanged**.
Logging, audit trail, and state update logic is independent of YAML structure.

---

### 6. `tests/unit/test_config.py` *(rewrite)*

All test fixtures and assertions reference v1.0 field names. Full rewrite required.

| Test / assertion | Change |
|---|---|
| `test_agent_has_required_fields` — asserts `name`, `type`, `prompt_file` | Replace with `role`, `goal`, `system_prompt` |
| `test_critic_agents_have_validates_phase` | **Delete** — `validates_phase` removed |
| `TestValidateAgentsConfig` fixtures | Rewrite with v1.2 fields |
| `TestLoadWorkflowsConfig` — asserts `"workflows" in config`, `"transitions" in workflow` | Replace with `"workflow" in config`, `"nodes"` and `"edges"` present |
| `TestValidateWorkflowsConfig` fixtures | Rewrite with `nodes`/`edges` instead of `transitions` |
| `TestGetWorkflowConfig` — asserts `config["initial_state"] == "extractor"` | Replace with `config["entry_point"] == "__start__"` |
| `TestGetTransition` — all tests | Replace with `TestGetEdgeRoutes` testing new accessor |
| `TestConfigIntegration.test_full_workflow_path` — uses `get_transition()` loop | Rewrite to traverse `edges` list |

---

### 7. `tests/integration/test_workflow.py` *(minor updates)*

- `build_workflow_graph()` signature preserved — most call sites survive unchanged
- Remove any direct tests of `should_continue_after_critic()` (function deleted)
- Add test: confirm `build_workflow_graph()` reads nodes/edges from YAML (not hardcoded)
- Review tests that assert on specific graph edge topology

---

## What Is NOT Changing

| File / area | Reason |
|---|---|
| `src/agents/extractor.py`, `critic.py`, `reconciler.py`, `classifier.py`, `formatter.py` | Use hardcoded `PROMPT_PATH` constants; do not read `agents.yaml` at runtime |
| `src/core/state.py` | `WorkflowState` TypedDict already matches v1.2 `state:` schema exactly |
| `src/prompts/*.md` | Prompt files unchanged |
| `tests/unit/test_state.py`, `test_matching.py`, contract tests, other integration tests | Not affected by YAML structure change |

---

## Testing Checklist

- [x] `pytest tests/unit/test_config.py` — **52 passed** — all v1.2 config parsing and validation tests
- [x] `pytest tests/integration/test_workflow.py` — **12 passed** — YAML-driven graph construction
- [x] `pytest tests/contract/` — **135 passed** — agent input/output contract tests, no regressions
- [x] `pytest tests/unit/test_state.py` — **27 passed** — state management, no regressions
- [x] `pytest` (full suite, excl. LLM-dependent flow tests) — **461 passed, 1 failed, 4 skipped** — 1 pre-existing flaky failure in `test_audit.py::TestAgentEvents::test_log_agent_completed` (timing rounding off-by-one, unrelated to migration); 4 skipped tests require live LLM API key (test_extraction_flow, test_reconciliation_flow, test_classification_flow, test_edge_cases use real critic agents)
